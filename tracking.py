"""
OBSIDIAN — Engagement Tracking (Stage 4)

Two endpoints:
  GET /api/email/track-open/<batch_id>.png   — 1x1 pixel, logs 'open'
  GET /api/email/track-click/<batch_id>      — logs 'click', redirects to ?to=

Both endpoints:
  - Update obs_digest_batches (opened_at / first_click_at) on FIRST occurrence
  - Always append a row to obs_email_events (full history)
  - Are intentionally fail-soft: tracking errors never break the user experience
"""
import hashlib
import logging
from datetime import datetime
from urllib.parse import unquote

from flask import Blueprint, request, redirect, Response
from sqlalchemy import text
from db import get_session

log = logging.getLogger("obsidian.tracking")

tracking_bp = Blueprint("tracking", __name__, url_prefix="/api/email")

# 1x1 transparent PNG (43 bytes) — the smallest valid PNG possible
TRANSPARENT_PIXEL = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "89000000017352474200aece1ce90000000467414d410000b18f0bfc6105"
    "0000000d49444154789c6360000002000154a24f5a0000000049454e44ae426082"
)


def _hash_ip(ip: str) -> str:
    """One-way hash of IP for privacy-respecting analytics."""
    if not ip:
        return ""
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def _log_event(batch_id: str, event_type: str, extra: dict | None = None):
    """
    Record an engagement event. Updates the batch's first-occurrence
    timestamp and always appends to obs_email_events.
    Fails silently — tracking must never break delivery or redirects.
    """
    try:
        ua = request.headers.get("User-Agent", "")[:300]
        ip_hash = _hash_ip(request.headers.get("X-Forwarded-For", request.remote_addr or ""))
        event_data = extra or {}

        with get_session() as s:
            # Append full history row
            s.execute(text("""
                INSERT INTO obs_email_events (batch_id, event_type, event_data, user_agent, ip_hash)
                VALUES (:bid, :etype, :edata, :ua, :iph)
            """), {
                "bid": batch_id, "etype": event_type,
                "edata": __import__("json").dumps(event_data),
                "ua": ua, "iph": ip_hash
            })

            # Update first-occurrence timestamp on the batch (idempotent)
            if event_type == "open":
                s.execute(text("""
                    UPDATE obs_digest_batches
                    SET opened_at = COALESCE(opened_at, NOW())
                    WHERE id = :bid
                """), {"bid": batch_id})
            elif event_type == "click":
                s.execute(text("""
                    UPDATE obs_digest_batches
                    SET first_click_at = COALESCE(first_click_at, NOW()),
                        opened_at = COALESCE(opened_at, NOW())
                    WHERE id = :bid
                """), {"bid": batch_id})
    except Exception as e:
        log.warning(f"tracking_log_failed | batch={batch_id} | type={event_type} | err={e}")


# ──────────────────────────────────────────────────────────
# OPEN TRACKING — 1x1 pixel
# ──────────────────────────────────────────────────────────

@tracking_bp.route("/track-open/<batch_id>.png")
def track_open(batch_id):
    _log_event(batch_id, "open")
    return Response(TRANSPARENT_PIXEL, mimetype="image/png", headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    })


# ──────────────────────────────────────────────────────────
# CLICK TRACKING — log then redirect
# ──────────────────────────────────────────────────────────

@tracking_bp.route("/track-click/<batch_id>")
def track_click(batch_id):
    target = request.args.get("to", "")
    target = unquote(target)

    # Safety: only allow redirecting to http(s) URLs
    if not (target.startswith("http://") or target.startswith("https://")):
        target = "https://command-center-jst4.onrender.com/"

    _log_event(batch_id, "click", extra={"target": target})

    return redirect(target, code=302)