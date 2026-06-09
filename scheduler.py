"""
OBSIDIAN — Scheduler (Stage 3)

Two responsibilities:
  1. process_pending_alerts()       — fires real-time alert emails (severity ≥ HIGH)
  2. process_morning_digests()      — runs every 15 min; fires user-specific
                                       morning digests when their time arrives
  3. process_evening_digests()      — same for evening
  4. process_weekly_briefs()        — Monday mornings only

Background scheduler runs via APScheduler when app starts.
"""
import os
import json
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import text
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from db import get_session
from digest_renderer import build_digest_for_user, render_html_digest, render_text_digest
from email_sender import send_batch, quota_remaining

log = logging.getLogger("obsidian.scheduler")

scheduler = BackgroundScheduler(timezone="UTC")


# ──────────────────────────────────────────────────────────
# CORE: send digest to a single user
# ──────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────
# CORE: send digest to a single user
# ──────────────────────────────────────────────────────────

def _send_digest_to_user(user_id: str, digest_type: str) -> dict:
    """
    Builds and sends one digest. Returns send result dict.
    """
    digest = build_digest_for_user(user_id, digest_type=digest_type)
    if not digest:
        return {"ok": False, "reason": "no_pending_events"}

    if quota_remaining() <= 0:
        return {"ok": False, "reason": "daily_quota_exhausted"}

    # Insert batch first to get ID for tracking pixel
    with get_session() as s:
        row = s.execute(text("""
            INSERT INTO obs_digest_batches
            (user_id, digest_type, delivery_ids, severity_max, event_count, subject_line)
            VALUES
            (:uid, :dtype, CAST(:dids AS uuid[]), :smax, :cnt, :sub)
            RETURNING id
        """), {
            "uid": digest["user_id"],
            "dtype": digest_type,
            "dids": digest["delivery_ids"],
            "smax": digest["severity_max"],
            "cnt": digest["event_count"],
            "sub": digest["subject"][:255]
        }).fetchone()
        batch_id = str(row.id)

    # Render HTML with batch_id for tracking pixel
    html_body = render_html_digest(
        user_name=digest["user_name"],
        user_role=digest["user_role"],
        user_timezone=digest["user_timezone"],
        events=digest["events"],
        digest_type=digest_type,
        batch_id=batch_id
    )
    text_body = render_text_digest(
        user_name=digest["user_name"],
        user_role=digest["user_role"],
        events=digest["events"],
        digest_type=digest_type
    )

    result = send_batch(
        batch_id=batch_id,
        to_email=digest["user_email"],
        subject=digest["subject"],
        html_body=html_body,
        text_body=text_body
    )

    result["batch_id"] = batch_id
    result["event_count"] = digest["event_count"]
    result["user_email"] = digest["user_email"]
    return result
# ──────────────────────────────────────────────────────────
# JOB 1: Process real-time alerts (severity ≥ HIGH, every 5 min)
# ──────────────────────────────────────────────────────────

def process_pending_alerts():
    """Find queued 'alert' deliveries with severity ≥ 70 → send immediately."""
    try:
        with get_session() as s:
            rows = s.execute(text("""
                SELECT DISTINCT user_id
                FROM obs_deliveries
                WHERE status = 'queued'
                  AND channel = 'email'
                  AND delivery_type = 'alert'
                  AND severity >= 70
            """)).fetchall()
        
        user_ids = [str(r.user_id) for r in rows]
        if not user_ids:
            return
        
        log.info(f"alerts_job | candidates={len(user_ids)}")
        for uid in user_ids:
            result = _send_digest_to_user(uid, digest_type="alert")
            log.info(f"alerts_job | user={uid} | result={result.get('ok')} | reason={result.get('reason') or result.get('error')}")
    except Exception as e:
        log.error(f"alerts_job_error | {e}")


# ──────────────────────────────────────────────────────────
# JOB 2: Process scheduled morning/evening digests (every 15 min)
# ──────────────────────────────────────────────────────────

def _users_due_for_digest(digest_type: str) -> list[str]:
    """
    Returns user_ids whose configured digest_time has just passed in their local TZ.
    digest_type: 'morning_digest' or 'evening_digest'
    """
    time_col = "morning_digest_time" if digest_type == "morning_digest" else "evening_digest_time"
    
    with get_session() as s:
        users = s.execute(text(f"""
            SELECT u.id, u.timezone, p.{time_col} AS digest_time
            FROM obs_users u
            JOIN obs_user_preferences p ON p.user_id = u.id
            WHERE u.is_active = TRUE
              AND p.channel_email = TRUE
              AND COALESCE(p.vacation_mode, FALSE) = FALSE
              AND p.{time_col} IS NOT NULL
        """)).fetchall()
    
    due = []
    now_utc = datetime.now(ZoneInfo("UTC"))
    
    for u in users:
        try:
            tz = ZoneInfo(u.timezone or "Asia/Kolkata")
        except Exception:
            tz = ZoneInfo("Asia/Kolkata")
        local_now = now_utc.astimezone(tz)
        digest_t = u.digest_time
        
        # Send if within 15 min of scheduled time AND not sent today
        target = datetime.combine(local_now.date(), digest_t, tzinfo=tz)
        delta_minutes = (local_now - target).total_seconds() / 60
        
        if -1 <= delta_minutes <= 15:
            # Check if already sent today
            with get_session() as s:
                already = s.execute(text("""
                    SELECT 1 FROM obs_digest_batches
                    WHERE user_id = :uid
                      AND digest_type = :dtype
                      AND DATE(queued_at AT TIME ZONE :tz) = DATE(:local_today)
                """), {
                    "uid": u.id,
                    "dtype": digest_type,
                    "tz": str(tz),
                    "local_today": local_now.isoformat()
                }).fetchone()
            
            if not already:
                due.append(str(u.id))
    
    return due


def process_morning_digests():
    try:
        due = _users_due_for_digest("morning_digest")
        if not due:
            return
        log.info(f"morning_digest_job | due={len(due)}")
        for uid in due:
            result = _send_digest_to_user(uid, digest_type="morning_digest")
            log.info(f"morning_digest_job | user={uid} | {result}")
    except Exception as e:
        log.error(f"morning_digest_error | {e}")


def process_evening_digests():
    try:
        due = _users_due_for_digest("evening_digest")
        if not due:
            return
        log.info(f"evening_digest_job | due={len(due)}")
        for uid in due:
            result = _send_digest_to_user(uid, digest_type="evening_digest")
            log.info(f"evening_digest_job | user={uid} | {result}")
    except Exception as e:
        log.error(f"evening_digest_error | {e}")


# ──────────────────────────────────────────────────────────
# SCHEDULER LIFECYCLE
# ──────────────────────────────────────────────────────────

def start_scheduler():
    """Call this once on Flask app startup."""
    if scheduler.running:
        return
    
    # Real-time alerts: every 5 minutes
    scheduler.add_job(
        process_pending_alerts,
        trigger=CronTrigger(minute="*/5"),
        id="alerts_realtime",
        replace_existing=True,
        max_instances=1
    )
    
    # Morning digests: every 15 minutes (catches users across timezones)
    scheduler.add_job(
        process_morning_digests,
        trigger=CronTrigger(minute="*/15"),
        id="morning_digests",
        replace_existing=True,
        max_instances=1
    )
    
    # Evening digests: every 15 minutes
    scheduler.add_job(
        process_evening_digests,
        trigger=CronTrigger(minute="*/15"),
        id="evening_digests",
        replace_existing=True,
        max_instances=1
    )
    
    scheduler.start()
    log.info("obsidian_scheduler_started")