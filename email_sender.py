"""
OBSIDIAN — Email Sender (Stage 3 / CAP 11 Soul)

Thin wrapper around Resend SDK. Handles:
  - Sending HTML + plaintext emails
  - Tracking Resend's returned email_id (for webhook correlation)
  - Daily quota enforcement (free tier: 100/day default)
  - Graceful failure handling with status capture
"""
import os
import json
import logging
from datetime import datetime, date
from typing import Optional

import resend
from sqlalchemy import text
from db import get_session

log = logging.getLogger("obsidian.email")

RESEND_API_KEY    = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "OBSIDIAN <onboarding@resend.dev>")
DAILY_LIMIT       = int(os.environ.get("RESEND_DAILY_LIMIT", "100"))

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY
else:
    log.warning("RESEND_API_KEY not set — email sending disabled")


# ──────────────────────────────────────────────────────────
# QUOTA CHECK
# ──────────────────────────────────────────────────────────

def emails_sent_today() -> int:
    """Returns number of emails marked as sent today (UTC)."""
    with get_session() as s:
        row = s.execute(text("""
            SELECT COUNT(*) AS cnt FROM obs_digest_batches
            WHERE DATE(sent_at) = CURRENT_DATE
              AND status IN ('sent','delivered','opened','bounced')
        """)).fetchone()
        return int(row.cnt) if row else 0


def quota_remaining() -> int:
    return max(0, DAILY_LIMIT - emails_sent_today())


# ──────────────────────────────────────────────────────────
# SENDER
# ──────────────────────────────────────────────────────────

def send_email(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    batch_id: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> dict:
    """
    Send a single email via Resend.
    
    Args:
        to_email: recipient email
        subject: email subject line
        html_body: HTML content
        text_body: optional plaintext fallback (Gmail prefers this)
        batch_id: UUID of obs_digest_batches row (for tracking)
        reply_to: optional reply-to address
    
    Returns:
        {"ok": bool, "email_id": str | None, "error": str | None}
    """
    if not RESEND_API_KEY:
        return {"ok": False, "email_id": None, "error": "RESEND_API_KEY not configured"}
    
    if quota_remaining() <= 0:
        return {"ok": False, "email_id": None, "error": "daily_quota_exhausted"}
    
    if not to_email or "@" not in to_email:
        return {"ok": False, "email_id": None, "error": "invalid_recipient"}
    
    params = {
        "from": RESEND_FROM_EMAIL,
        "to": [to_email],
        "subject": subject,
        "html": html_body,
    }
    
    if text_body:
        params["text"] = text_body
    if reply_to:
        params["reply_to"] = [reply_to]
    if batch_id:
        params["headers"] = {"X-Obsidian-Batch-Id": str(batch_id)}
    
    try:
        result = resend.Emails.send(params)
        email_id = result.get("id") if isinstance(result, dict) else None
        
        if email_id:
            log.info(f"Resend send ok | to={to_email} | id={email_id}")
            return {"ok": True, "email_id": email_id, "error": None}
        else:
            return {"ok": False, "email_id": None, "error": f"unexpected_response: {result}"}
    
    except Exception as e:
        err = str(e)[:500]
        log.error(f"Resend send failed | to={to_email} | err={err}")
        return {"ok": False, "email_id": None, "error": err}


# ──────────────────────────────────────────────────────────
# BATCH-LEVEL SEND (with status update)
# ──────────────────────────────────────────────────────────

def send_batch(batch_id: str, to_email: str, subject: str,
               html_body: str, text_body: Optional[str] = None) -> dict:
    """
    Send a batch and update obs_digest_batches.status atomically.
    """
    # Mark as sending
    with get_session() as s:
        s.execute(text("""
            UPDATE obs_digest_batches
            SET status = 'sending', subject_line = :sub
            WHERE id = :bid
        """), {"bid": batch_id, "sub": subject[:255]})
    
    result = send_email(
        to_email=to_email, subject=subject,
        html_body=html_body, text_body=text_body,
        batch_id=batch_id
    )
    
    # Update final status
    with get_session() as s:
        if result["ok"]:
            s.execute(text("""
                UPDATE obs_digest_batches
                SET status = 'sent',
                    sent_at = NOW(),
                    resend_email_id = :eid
                WHERE id = :bid
            """), {"bid": batch_id, "eid": result["email_id"]})
            
            # Also mark all the deliveries this batch covers as sent
            s.execute(text("""
                UPDATE obs_deliveries
                SET status = 'sent', sent_at = NOW()
                WHERE id = ANY(
                    SELECT unnest(delivery_ids) FROM obs_digest_batches WHERE id = :bid
                )
            """), {"bid": batch_id})
        else:
            s.execute(text("""
                UPDATE obs_digest_batches
                SET status = 'failed',
                    failure_reason = :err,
                    retry_count = retry_count + 1
                WHERE id = :bid
            """), {"bid": batch_id, "err": result["error"][:500]})
    
    return result