"""
OBSIDIAN — Outbound Webhook Sender (Stage 6B, push side)

When routing processes a high/critical event, OBSIDIAN POSTs it to every
active partner webhook whose min_severity threshold is met.

Security:
  - Each webhook has a signing_secret.
  - We send an HMAC-SHA256 signature in the X-OBSIDIAN-Signature header so the
    partner can verify the payload genuinely came from us and wasn't forged.

Reliability:
  - A dead/failing partner URL logs, increments failure_count, and is skipped —
    it NEVER blocks or crashes routing (same discipline as the Slack orchestrator).

Public API:
  push_event_to_webhooks(event_id) -> dict
"""
import os
import json
import hmac
import hashlib
import logging
import urllib.request
import urllib.error
from datetime import datetime

from sqlalchemy import text
from db import get_session

log = logging.getLogger("obsidian.webhooks")

FAILURE_DISABLE_THRESHOLD = 10  # auto-disable a webhook after N consecutive failures


def _sign(secret: str, body: bytes) -> str:
    """HMAC-SHA256 hex signature of the raw body."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _post(url: str, body: bytes, signature: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-OBSIDIAN-Signature": f"sha256={signature}",
            "User-Agent": "OBSIDIAN-Webhook/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"ok": 200 <= resp.status < 300, "status": resp.status}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "error": str(e)[:160]}
    except Exception as e:
        return {"ok": False, "status": None, "error": str(e)[:160]}


def push_event_to_webhooks(event_id: str) -> dict:
    """
    POST an event to all active webhooks whose min_severity <= event severity.
    Returns {"pushed": int, "skipped": int, "failed": int, "details": [...]}.
    Safe to call from routing; never raises.
    """
    pushed = failed = skipped = 0
    details = []

    try:
        with get_session() as s:
            ev = s.execute(text("""
                SELECT id, headline, summary, severity, confidence,
                       event_type, geographic_scope, detected_at
                FROM obs_events WHERE id = :eid
            """), {"eid": event_id}).fetchone()

            if not ev:
                return {"pushed": 0, "skipped": 0, "failed": 0, "details": [], "reason": "event_not_found"}

            severity = int(ev.severity or 0)

            hooks = s.execute(text("""
                SELECT id, partner_name, target_url, signing_secret,
                       min_severity, failure_count
                FROM obs_webhooks
                WHERE active = TRUE AND min_severity <= :sev
            """), {"sev": severity}).fetchall()

            if not hooks:
                return {"pushed": 0, "skipped": 0, "failed": 0, "details": []}

            payload = {
                "type": "event",
                "delivered_at": datetime.utcnow().isoformat() + "Z",
                "event": {
                    "id": str(ev.id),
                    "headline": ev.headline,
                    "summary": ev.summary,
                    "severity": severity,
                    "confidence": ev.confidence,
                    "event_type": ev.event_type,
                    "geographic_scope": ev.geographic_scope,
                    "detected_at": ev.detected_at.isoformat() if ev.detected_at else None,
                },
            }
            body = json.dumps(payload).encode("utf-8")

            for h in hooks:
                url = (h.target_url or "").strip()
                if not url.startswith(("http://", "https://")):
                    skipped += 1
                    details.append({"webhook_id": str(h.id), "skipped": "bad_url"})
                    continue

                sig = _sign(h.signing_secret or "", body)
                res = _post(url, body, sig)

                if res["ok"]:
                    pushed += 1
                    s.execute(text("""
                        UPDATE obs_webhooks
                        SET last_fired_at = NOW(), failure_count = 0
                        WHERE id = :id
                    """), {"id": h.id})
                    details.append({"webhook_id": str(h.id), "partner": h.partner_name, "ok": True})
                    log.info(f"webhook_pushed | partner={h.partner_name} | event={event_id}")
                else:
                    failed += 1
                    new_fail = (h.failure_count or 0) + 1
                    disable = new_fail >= FAILURE_DISABLE_THRESHOLD
                    s.execute(text("""
                        UPDATE obs_webhooks
                        SET failure_count = :fc, active = :act
                        WHERE id = :id
                    """), {"fc": new_fail, "act": not disable, "id": h.id})
                    details.append({
                        "webhook_id": str(h.id), "partner": h.partner_name,
                        "ok": False, "error": res.get("error"), "disabled": disable
                    })
                    log.warning(f"webhook_failed | partner={h.partner_name} | fails={new_fail} | {res.get('error')}")

    except Exception as e:
        # Never let webhook delivery break routing
        log.error(f"webhook_push_exception | event={event_id} | {e}")
        return {"pushed": pushed, "skipped": skipped, "failed": failed,
                "details": details, "exception": str(e)[:160]}

    return {"pushed": pushed, "skipped": skipped, "failed": failed, "details": details}
