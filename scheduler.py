"""
OBSIDIAN Command Center Intelligence
scheduler.py  —  APScheduler Background Task Engine
Stage 5: Email Digest + Slack Webhook Delivery + CAP 12 Prediction Logging
Shivanchal Consultants (c) 2025
"""

import logging
import os
from datetime import datetime

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

log = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# ─────────────────────────────────────────────────────────────────────────────
# Scheduler singleton
# ─────────────────────────────────────────────────────────────────────────────

_scheduler = None


def start_scheduler():
    """Return the module-level BackgroundScheduler instance, creating it if needed."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone=IST)
    return _scheduler


# ─────────────────────────────────────────────────────────────────────────────
# Task: Feed cache refresh
# ─────────────────────────────────────────────────────────────────────────────

def task_refresh_feeds(app):
    """Fetch and cache all active RSS / API intelligence feeds."""
    with app.app_context():
        try:
            from feed_cache import refresh_all_feeds
            count = refresh_all_feeds()
            log.info("[SCHEDULER] Feed refresh complete — %d sources updated", count)
        except Exception as exc:
            log.error("[SCHEDULER] Feed refresh failed: %s", exc, exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Task: Daily email digest
# ─────────────────────────────────────────────────────────────────────────────

def task_send_daily_digest(app):
    """
    Build and dispatch the daily intelligence digest to all active subscribers
    via Resend (intel@shivanchal.in).
    """
    with app.app_context():
        try:
            from email_sender import send_daily_digest
            result = send_daily_digest()
            sent = result.get("sent", 0) if isinstance(result, dict) else 0
            log.info("[SCHEDULER] Email digest dispatched — %d recipients", sent)
        except Exception as exc:
            log.error("[SCHEDULER] Email digest failed: %s", exc, exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Task: Slack webhook delivery  (Stage 5)
# ─────────────────────────────────────────────────────────────────────────────

def task_send_slack_alerts(app):
    """
    Push routed intelligence items to each user's configured Slack webhook.
    Block Kit formatted. Fires 5 min after email digest to avoid thundering-herd
    on the Resend queue.
    """
    with app.app_context():
        try:
            from slack_sender import deliver_slack_alerts
            result = deliver_slack_alerts()
            delivered = result.get("delivered", 0) if isinstance(result, dict) else 0
            failed = result.get("failed", 0) if isinstance(result, dict) else 0
            log.info(
                "[SCHEDULER] Slack delivery complete — %d delivered, %d failed",
                delivered,
                failed,
            )
        except Exception as exc:
            log.error("[SCHEDULER] Slack delivery failed: %s", exc, exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Task: CAP 12 — Silent prediction logging  (Stage 5)
# ─────────────────────────────────────────────────────────────────────────────

def task_log_predictions(app):
    """
    CAP 12: Record a silent daily prediction snapshot for every active
    intelligence item that passed through the CAP 11 routing engine today.

    This task produces zero user-facing output. Its sole purpose is to build
    the 90-day track record needed for Brier score calculation, calibration
    curve visualisation, and the predictive moat that cannot be back-filled.
    Resolution and scoring columns are populated by a separate resolver job
    once outcomes are known.
    """
    with app.app_context():
        try:
            from prediction_logger import run_prediction_snapshot
            logged = run_prediction_snapshot()
            log.info("[SCHEDULER] CAP 12 snapshot complete — %d predictions recorded", logged)
        except Exception as exc:
            log.error("[SCHEDULER] CAP 12 prediction log failed: %s", exc, exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Task: Engagement telemetry rollup
# ─────────────────────────────────────────────────────────────────────────────

def task_telemetry_rollup(app):
    """Aggregate raw engagement events into the daily summary table (23:55 IST)."""
    with app.app_context():
        try:
            from tracking import run_daily_rollup
            run_daily_rollup()
            log.info("[SCHEDULER] Telemetry rollup complete")
        except Exception as exc:
            log.error("[SCHEDULER] Telemetry rollup failed: %s", exc, exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler initialisation
# ─────────────────────────────────────────────────────────────────────────────

def init_scheduler(app):
    """
    Register all background jobs and start the APScheduler BackgroundScheduler.

    Call exactly once from app.py after the Flask app and DB are initialised.

    Job schedule (all times IST):
        05:00  feed_prime          — warm the cache before digest runs
        06:00  daily_digest        — email digest via Resend
        06:05  slack_alerts        — Slack Block Kit delivery
        06:10  cap12_snapshot      — CAP 12 silent prediction logging
        23:55  telemetry_rollup    — end-of-day engagement aggregation
        every  feed_refresh_roll   — rolling 30-min feed refresh (daytime cache)
    """
    scheduler = get_scheduler()

    if scheduler.running:
        log.warning(
            "[SCHEDULER] init_scheduler called but scheduler already running — skipping"
        )
        return scheduler

    # ── 05:00 IST  Feed prime ────────────────────────────────────────────────
    scheduler.add_job(
        func=task_refresh_feeds,
        trigger=CronTrigger(hour=5, minute=0, timezone=IST),
        args=[app],
        id="feed_prime",
        name="Feed Prime (05:00 IST)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # ── 06:00 IST  Daily email digest ────────────────────────────────────────
    scheduler.add_job(
        func=task_send_daily_digest,
        trigger=CronTrigger(hour=6, minute=0, timezone=IST),
        args=[app],
        id="daily_digest",
        name="Daily Email Digest (06:00 IST)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # ── 06:05 IST  Slack delivery ────────────────────────────────────────────
    scheduler.add_job(
        func=task_send_slack_alerts,
        trigger=CronTrigger(hour=6, minute=5, timezone=IST),
        args=[app],
        id="slack_alerts",
        name="Slack Alert Delivery (06:05 IST)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # ── 06:10 IST  CAP 12 prediction snapshot ────────────────────────────────
    scheduler.add_job(
        func=task_log_predictions,
        trigger=CronTrigger(hour=6, minute=10, timezone=IST),
        args=[app],
        id="cap12_snapshot",
        name="CAP 12 Prediction Snapshot (06:10 IST)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # ── 23:55 IST  Telemetry rollup ──────────────────────────────────────────
    scheduler.add_job(
        func=task_telemetry_rollup,
        trigger=CronTrigger(hour=23, minute=55, timezone=IST),
        args=[app],
        id="telemetry_rollup",
        name="Telemetry Rollup (23:55 IST)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # ── Rolling 30-min feed refresh ──────────────────────────────────────────
    scheduler.add_job(
        func=task_refresh_feeds,
        trigger=IntervalTrigger(minutes=30, timezone=IST),
        args=[app],
        id="feed_refresh_roll",
        name="Feed Refresh Rolling (30 min)",
        replace_existing=True,
        misfire_grace_time=120,
    )

    scheduler.start()
    log.info("[SCHEDULER] BackgroundScheduler started — 6 jobs registered")
    _log_job_table(scheduler)
    return scheduler


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _log_job_table(scheduler):
    """Log next-run times for all registered jobs at startup."""
    now_ist = datetime.now(IST)
    log.info(
        "[SCHEDULER] Current IST: %s",
        now_ist.strftime("%Y-%m-%d %H:%M:%S %Z"),
    )
    for job in scheduler.get_jobs():
        nrt = job.next_run_time
        if nrt:
            nrt_ist = nrt.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S %Z")
        else:
            nrt_ist = "not scheduled"
        log.info("  -> [%s] next run: %s", job.id, nrt_ist)


def shutdown_scheduler():
    """Gracefully stop the scheduler. Call from Flask app teardown / Gunicorn hooks."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("[SCHEDULER] BackgroundScheduler stopped")
        _scheduler = None


def get_scheduler_status():
    """
    Return scheduler health info for the admin / engagement dashboard.

    Returns:
        dict with keys:
            running   (bool)   — whether the scheduler is active
            job_count (int)    — number of registered jobs
            jobs      (list)   — list of {id, name, next_run} dicts
    """
    scheduler = get_scheduler()
    jobs = []
    for job in scheduler.get_jobs():
        nrt = job.next_run_time
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run": (
                    nrt.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S IST")
                    if nrt
                    else "—"
                ),
            }
        )
    return {
        "running": scheduler.running,
        "job_count": len(jobs),
        "jobs": jobs,
    }
