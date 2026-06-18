"""
OBSIDIAN — Slack Sender (Stage 5A)

Sends intelligence alerts to Slack channels via incoming webhooks.
Uses Block Kit for rich, scannable formatting matching OBSIDIAN's aesthetic.

Setup for users:
  1. Go to https://api.slack.com/apps → Create App → Incoming Webhooks
  2. Enable webhooks, add to channel
  3. Copy webhook URL → paste into /settings under Slack webhook URL
  4. Toggle Slack channel ON in /settings
"""
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

log = logging.getLogger("obsidian.slack")

# Severity → color sidebars in Slack attachments
SEVERITY_COLOR = {
    "critical": "#ff3838",
    "high":     "#ff8c00",
    "elevated": "#ffd166",
    "low":      "#888888",
}

def _severity_tier(sev: int) -> str:
    if sev >= 85: return "critical"
    if sev >= 70: return "high"
    if sev >= 50: return "elevated"
    return "low"

def _severity_emoji(sev: int) -> str:
    if sev >= 85: return "🔴"
    if sev >= 70: return "🟠"
    if sev >= 50: return "🟡"
    return "⚪"


def build_slack_payload(
    *,
    event: dict,
    user_name: str,
    user_role: str,
    watchlist_entries: list,
    app_base_url: str,
) -> dict:
    """
    Build a Slack Block Kit message for an OBSIDIAN intelligence event.
    Returns a dict ready to POST to a Slack webhook URL.
    """
    sev = int(event.get("severity") or 0)
    tier = _severity_tier(sev)
    emoji = _severity_emoji(sev)
    color = SEVERITY_COLOR[tier]
    headline = event.get("headline") or "Intelligence update"
    summary = (event.get("summary") or "")[:300]
    scope = event.get("geographic_scope") or "Global"
    event_id = str(event.get("id") or "")

    # Watchlist match line
    wl_text = ""
    if watchlist_entries:
        wl_text = f"*◎ Matched watchlist:* {', '.join(watchlist_entries[:4])}\n"

    # Role framing for the footer
    role_labels = {
        "ceo": "CEO STRATEGIC VIEW",
        "coo": "COO OPERATIONS VIEW",
        "analyst": "ANALYST VIEW",
        "procurement": "PROCUREMENT VIEW",
        "logistics": "LOGISTICS VIEW",
        "risk": "RISK ANALYST VIEW",
    }
    role_label = role_labels.get(user_role.lower(), "INTELLIGENCE VIEW")

    brief_url = f"{app_base_url}/?event={event_id}" if event_id else app_base_url

    payload = {
        "text": f"{emoji} *OBSIDIAN ALERT* — {headline}",
        "attachments": [
            {
                "color": color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"OBSIDIAN // INTELLIGENCE ALERT",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Severity*\n{emoji} `{sev}` · {tier.upper()}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Scope*\n{scope}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Delivered to*\n{user_name} · {role_label}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Time*\n{datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y · %H:%M IST')}"
                            }
                        ]
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{headline}*\n{summary}"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": wl_text if wl_text else "_No watchlist match — routed by severity threshold._"
                        }
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "▶ Open Brief",
                                    "emoji": True
                                },
                                "url": brief_url,
                                "style": "primary"
                            },
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "◎ Command Center",
                                    "emoji": True
                                },
                                "url": app_base_url
                            }
                        ]
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"OBSIDIAN Intelligence · Shivanchal Consultants · <{app_base_url}/settings|Manage preferences>"
                            }
                        ]
                    }
                ]
            }
        ]
    }
    return payload


def send_slack_message(webhook_url: str, payload: dict) -> dict:
    """
    POST the Block Kit payload to a Slack webhook URL.
    Returns {"ok": bool, "error": str | None}
    """
    if not webhook_url or not webhook_url.startswith("https://hooks.slack.com/"):
        return {"ok": False, "error": "invalid_webhook_url"}

    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            response_text = resp.read().decode("utf-8")
            if response_text.strip() == "ok":
                log.info(f"slack_send_ok | webhook=...{webhook_url[-20:]}")
                return {"ok": True, "error": None}
            else:
                return {"ok": False, "error": f"unexpected_response: {response_text[:100]}"}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8")[:200]
        log.error(f"slack_http_error | {e.code} | {err}")
        return {"ok": False, "error": f"http_{e.code}: {err}"}
    except Exception as e:
        log.error(f"slack_send_failed | {e}")
        return {"ok": False, "error": str(e)[:200]}
        # ══════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR — deliver_slack_alerts()   (Stage 5A glue)
# Append this block to the bottom of slack_sender.py.
# Depends on existing build_slack_payload() and send_slack_message() above.
# ══════════════════════════════════════════════════════════════════════════

import os
from sqlalchemy import text as _sql_text
from db import get_session as _get_session

# App base URL for "Open Brief" / "Command Center" buttons in the card.
# Falls back to the Render URL if env var not set.
APP_BASE_URL = os.environ.get(
    "APP_BASE_URL",
    "https://command-center-jst4.onrender.com"
)


def _deliver_one_slack_row(row, webhook_url, event, watchlist_names, session) -> dict:
    """
    Build + send one Slack delivery, then flip its obs_deliveries status.
    Returns {"delivered": bool, "delivery_id": str, "error": str|None}.
    """
    delivery_id = str(row.id)
    try:
        payload = build_slack_payload(
            event=event,
            user_name=row.user_name or row.user_email or "Subscriber",
            user_role=row.user_role or "",
            watchlist_entries=watchlist_names,
            app_base_url=APP_BASE_URL,
        )
        result = send_slack_message(webhook_url, payload)

        if result["ok"]:
            session.execute(_sql_text("""
                UPDATE obs_deliveries
                SET status = 'sent', sent_at = NOW(), failure_reason = NULL
                WHERE id = :did
            """), {"did": delivery_id})
            log.info(f"slack_delivered | delivery={delivery_id} | event={event.get('id')}")
            return {"delivered": True, "delivery_id": delivery_id, "error": None}
        else:
            err = (result.get("error") or "unknown")[:200]
            session.execute(_sql_text("""
                UPDATE obs_deliveries
                SET status = 'failed',
                    failure_reason = :err,
                    retry_count = COALESCE(retry_count, 0) + 1
                WHERE id = :did
            """), {"did": delivery_id, "err": err})
            log.warning(f"slack_failed | delivery={delivery_id} | {err}")
            return {"delivered": False, "delivery_id": delivery_id, "error": err}

    except Exception as e:
        err = str(e)[:200]
        try:
            session.execute(_sql_text("""
                UPDATE obs_deliveries
                SET status = 'failed',
                    failure_reason = :err,
                    retry_count = COALESCE(retry_count, 0) + 1
                WHERE id = :did
            """), {"did": delivery_id, "err": err})
        except Exception:
            pass
        log.error(f"slack_deliver_exception | delivery={delivery_id} | {err}")
        return {"delivered": False, "delivery_id": delivery_id, "error": err}


def deliver_slack_alerts() -> dict:
    """
    Find all queued Slack deliveries, send each to its user's webhook,
    and mark sent/failed. Called by scheduler.task_send_slack_alerts (06:05 IST)
    and by the manual test trigger below.

    A delivery qualifies when:
      - obs_deliveries.channel = 'slack'
      - obs_deliveries.status  = 'queued'
      - the user has channel_slack = TRUE and a non-empty slack_webhook_url

    Returns {"delivered": int, "failed": int, "skipped": int, "details": [...]}.
    """
    delivered = 0
    failed = 0
    skipped = 0
    details = []

    with _get_session() as s:
        rows = s.execute(_sql_text("""
            SELECT d.id, d.user_id, d.event_id, d.severity, d.routing_log,
                   u.email AS user_email, u.name AS user_name, u.role AS user_role,
                   p.slack_webhook_url
            FROM obs_deliveries d
            JOIN obs_users u            ON u.id = d.user_id
            JOIN obs_user_preferences p ON p.user_id = d.user_id
            WHERE d.channel = 'slack'
              AND d.status  = 'queued'
              AND p.channel_slack = TRUE
              AND p.slack_webhook_url IS NOT NULL
              AND p.slack_webhook_url <> ''
            ORDER BY d.routed_at ASC
        """)).fetchall()

        if not rows:
            log.info("slack_orchestrator | no queued slack deliveries")
            return {"delivered": 0, "failed": 0, "skipped": 0, "details": []}

        # Cache events so we don't re-fetch per row
        event_cache = {}

        for row in rows:
            webhook = (row.slack_webhook_url or "").strip()
            if not webhook.startswith("https://hooks.slack.com/"):
                skipped += 1
                details.append({"delivery_id": str(row.id), "skipped": "bad_webhook"})
                continue

            eid = str(row.event_id)
            if eid not in event_cache:
                ev = s.execute(_sql_text("""
                    SELECT id, headline, summary, severity,
                           geographic_scope, event_type
                    FROM obs_events WHERE id = :eid
                """), {"eid": eid}).fetchone()
                if not ev:
                    event_cache[eid] = None
                else:
                    ed = dict(ev._mapping)
                    ed["id"] = str(ed["id"])
                    event_cache[eid] = ed
            event = event_cache[eid]

            if event is None:
                skipped += 1
                details.append({"delivery_id": str(row.id), "skipped": "event_not_found"})
                continue

            # Pull watchlist match names out of routing_log if present
            wl_names = []
            rlog = row.routing_log
            if isinstance(rlog, dict):
                wl_names = rlog.get("watchlist_entries", []) or []

            res = _deliver_one_slack_row(row, webhook, event, wl_names, s)
            if res["delivered"]:
                delivered += 1
            else:
                failed += 1
            details.append(res)

    log.info(f"slack_orchestrator_done | delivered={delivered} | failed={failed} | skipped={skipped}")
    return {"delivered": delivered, "failed": failed, "skipped": skipped, "details": details}


# ── Manual one-shot trigger (for testing without waiting for 06:05 IST) ──────
# Run from Render shell or a local Flask shell:
#     from slack_sender import deliver_slack_alerts
#     deliver_slack_alerts()
# Or wire a temporary admin route POST /api/admin/test-slack that calls it.
if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO)
    print(deliver_slack_alerts())