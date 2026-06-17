"""
OBSIDIAN — Routing Admin Blueprint (Stage 2 + Stage 4 + Stage 5)

Admin-facing routes for routing simulator, engagement, Slack testing,
and CAP 12 prediction visibility.
Only master accounts (Adi + Ankit) can access these routes.
"""
from functools import wraps
from flask import Blueprint, request, jsonify, session, render_template
from sqlalchemy import text
from db import get_session
from auth import login_required, current_user
from routing import route_event

admin_bp = Blueprint("routing_admin", __name__)

MASTER_EMAILS = {
    "adi.obsdian@gmail.com",
    "ankitdubey.aitech@gmail.com"
}


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "auth_required"}), 401
        user = current_user()
        if not user or user["email"] not in MASTER_EMAILS:
            return jsonify({"error": "admin_only"}), 403
        return fn(*args, **kwargs)
    return wrapper


# ──────────────────────────────────────────────────────────
# ROUTING SIMULATOR
# ──────────────────────────────────────────────────────────

@admin_bp.route("/admin/routing-simulator")
@admin_required
def simulator_page():
    return render_template("routing_simulator.html")


@admin_bp.route("/api/admin/recent-events", methods=["GET"])
@admin_required
def recent_events():
    limit = min(int(request.args.get("limit", 20)), 50)
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, headline, severity, event_type, geographic_scope, detected_at
            FROM obs_events
            ORDER BY detected_at DESC LIMIT :lim
        """), {"lim": limit}).fetchall()
        items = []
        for r in rows:
            d = dict(r._mapping)
            d["id"] = str(d["id"])
            d["detected_at"] = d["detected_at"].isoformat()
            items.append(d)
        return jsonify({"events": items, "count": len(items)})


@admin_bp.route("/api/admin/route-event", methods=["POST"])
@admin_required
def trigger_routing():
    data = request.get_json(silent=True) or {}
    event_id = data.get("event_id")
    dry_run = bool(data.get("dry_run", False))
    if not event_id:
        return jsonify({"error": "event_id_required"}), 400
    try:
        result = route_event(event_id, dry_run=dry_run)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "routing_failed", "detail": str(e)[:300]}), 500


@admin_bp.route("/api/admin/deliveries/<event_id>", methods=["GET"])
@admin_required
def event_deliveries(event_id):
    with get_session() as s:
        rows = s.execute(text("""
            SELECT d.id, d.channel, d.delivery_type, d.severity, d.status,
                   d.routing_log, d.routed_at, u.email, u.name, u.role
            FROM obs_deliveries d
            LEFT JOIN obs_users u ON u.id = d.user_id
            WHERE d.event_id = :eid
            ORDER BY d.routed_at DESC
        """), {"eid": event_id}).fetchall()
        items = []
        for r in rows:
            d = dict(r._mapping)
            d["id"] = str(d["id"])
            d["routed_at"] = d["routed_at"].isoformat() if d["routed_at"] else None
            items.append(d)
        return jsonify({"deliveries": items, "count": len(items)})


# ──────────────────────────────────────────────────────────
# MANUAL TEST DIGEST
# ──────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/send-test-digest", methods=["POST"])
@admin_required
def manual_test_digest():
    from scheduler import _send_digest_to_user
    data = request.get_json(silent=True) or {}
    target_email = (data.get("user_email") or "").strip().lower()
    dtype = data.get("digest_type", "manual_test")
    if not target_email:
        return jsonify({"error": "user_email_required"}), 400
    with get_session() as s:
        row = s.execute(
            text("SELECT id FROM obs_users WHERE email = :e AND is_active = TRUE"),
            {"e": target_email}
        ).fetchone()
        if not row:
            return jsonify({"error": "user_not_found"}), 404
        uid = str(row.id)
    result = _send_digest_to_user(uid, digest_type=dtype)
    return jsonify(result)


# ──────────────────────────────────────────────────────────
# ENGAGEMENT DASHBOARD (Stage 4)
# ──────────────────────────────────────────────────────────

@admin_bp.route("/admin/engagement")
@admin_required
def engagement_page():
    return render_template("engagement.html")


@admin_bp.route("/api/admin/engagement-summary", methods=["GET"])
@admin_required
def engagement_summary():
    with get_session() as s:
        user_rows = s.execute(text("""
            SELECT
                u.email, u.role,
                COUNT(b.id) AS total_sent,
                COUNT(b.opened_at) AS total_opened,
                COUNT(b.first_click_at) AS total_clicked,
                MAX(b.sent_at) AS last_sent,
                MAX(b.opened_at) AS last_opened
            FROM obs_users u
            LEFT JOIN obs_digest_batches b
                ON b.user_id = u.id
                AND b.status IN ('sent', 'delivered', 'opened')
            WHERE u.is_active = TRUE
            GROUP BY u.email, u.role
            ORDER BY u.role
        """)).fetchall()

        users = []
        for r in user_rows:
            total_sent = r.total_sent or 0
            total_opened = r.total_opened or 0
            total_clicked = r.total_clicked or 0
            open_rate = round(100 * total_opened / total_sent, 1) if total_sent else 0
            click_rate = round(100 * total_clicked / total_sent, 1) if total_sent else 0
            users.append({
                "email": r.email,
                "role": r.role,
                "total_sent": total_sent,
                "total_opened": total_opened,
                "total_clicked": total_clicked,
                "open_rate": open_rate,
                "click_rate": click_rate,
                "last_sent": r.last_sent.isoformat() if r.last_sent else None,
                "last_opened": r.last_opened.isoformat() if r.last_opened else None,
            })

        batch_rows = s.execute(text("""
            SELECT
                u.email, b.digest_type, b.subject_line, b.event_count,
                b.severity_max, b.status, b.sent_at, b.opened_at, b.first_click_at
            FROM obs_digest_batches b
            JOIN obs_users u ON u.id = b.user_id
            WHERE b.sent_at IS NOT NULL
            ORDER BY b.sent_at DESC
            LIMIT 20
        """)).fetchall()

        batches = []
        for r in batch_rows:
            batches.append({
                "email": r.email,
                "digest_type": r.digest_type,
                "subject": r.subject_line,
                "event_count": r.event_count,
                "severity_max": r.severity_max,
                "status": r.status,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
                "opened_at": r.opened_at.isoformat() if r.opened_at else None,
                "first_click_at": r.first_click_at.isoformat() if r.first_click_at else None,
                "was_opened": r.opened_at is not None,
                "was_clicked": r.first_click_at is not None,
            })

        return jsonify({"users": users, "recent_batches": batches})


@admin_bp.route("/api/admin/health-scores", methods=["GET"])
@admin_required
def health_scores():
    with get_session() as s:
        rows = s.execute(text("""
            SELECT
                u.email, u.role,
                COUNT(b.id) AS sent_7d,
                COUNT(b.opened_at) AS opened_7d
            FROM obs_users u
            LEFT JOIN obs_digest_batches b
                ON b.user_id = u.id
                AND b.sent_at >= NOW() - INTERVAL '7 days'
                AND b.status IN ('sent', 'delivered', 'opened')
            WHERE u.is_active = TRUE
            GROUP BY u.email, u.role
        """)).fetchall()

        result = []
        for r in rows:
            sent = r.sent_7d or 0
            opened = r.opened_7d or 0
            open_rate = round(100 * opened / sent, 1) if sent else None
            result.append({
                "email": r.email,
                "role": r.role,
                "sent_7d": sent,
                "opened_7d": opened,
                "open_rate_7d": open_rate,
                "health_flag": "pre_churn" if (open_rate is not None and open_rate < 40) else "healthy"
            })
        return jsonify({"users": result})


# ──────────────────────────────────────────────────────────
# SLACK TEST (Stage 5A)
# ──────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/test-slack", methods=["POST"])
@admin_required
def test_slack():
    """Test Slack delivery for a user. Body: {"user_email": "..."}"""
    import os
    from slack_sender import build_slack_payload, send_slack_message

    data = request.get_json(silent=True) or {}
    target_email = (data.get("user_email") or "").strip().lower()

    if not target_email:
        return jsonify({"error": "user_email_required"}), 400

    with get_session() as s:
        row = s.execute(text("""
            SELECT u.email, u.name, u.role, p.slack_webhook_url, p.channel_slack
            FROM obs_users u
            JOIN obs_user_preferences p ON p.user_id = u.id
            WHERE u.email = :e AND u.is_active = TRUE
        """), {"e": target_email}).fetchone()

        if not row:
            return jsonify({"error": "user_not_found"}), 404
        if not row.slack_webhook_url:
            return jsonify({"error": "no_webhook_url_configured"}), 400

    app_base_url = os.environ.get("APP_BASE_URL", "https://command-center-jst4.onrender.com")

    test_event = {
        "id": "test-event-001",
        "headline": "TEST — Red Sea Houthi escalation severity 92",
        "summary": "This is a test message from OBSIDIAN intelligence platform. "
                   "Your Slack integration is working correctly.",
        "severity": 92,
        "geographic_scope": "Red Sea / Bab el-Mandeb"
    }

    payload = build_slack_payload(
        event=test_event,
        user_name=row.name or row.email,
        user_role=row.role or "analyst",
        watchlist_entries=["Red Sea Trade", "India Domestic Risk"],
        app_base_url=app_base_url
    )

    result = send_slack_message(row.slack_webhook_url, payload)
    return jsonify(result)


# ──────────────────────────────────────────────────────────
# CAP 12 PREDICTIONS (Stage 5B)
# ──────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/predictions", methods=["GET"])
@admin_required
def list_predictions():
    """CAP 12 — View all logged predictions with outcome status."""
    limit = min(int(request.args.get("limit", 50)), 200)
    with get_session() as s:
        rows = s.execute(text("""
            SELECT
                p.id, p.prediction_type, p.predicted_value,
                p.confidence_score, p.horizon_days, p.made_at, p.model_version,
                e.headline, e.severity, e.event_type,
                (SELECT COUNT(*) FROM obs_ground_truth gt
                 WHERE gt.prediction_id = p.id) AS has_outcome
            FROM obs_predictions p
            JOIN obs_events e ON e.id = p.event_id
            ORDER BY p.made_at DESC
            LIMIT :lim
        """), {"lim": limit}).fetchall()

        items = []
        for r in rows:
            items.append({
                "id": str(r.id),
                "prediction_type": r.prediction_type,
                "predicted_value": r.predicted_value,
                "confidence_score": r.confidence_score,
                "horizon_days": r.horizon_days,
                "made_at": r.made_at.isoformat() if r.made_at else None,
                "model_version": r.model_version,
                "event_headline": r.headline,
                "event_severity": r.severity,
                "event_type": r.event_type,
                "outcome_logged": r.has_outcome > 0
            })

        return jsonify({
            "predictions": items,
            "count": len(items),
            "note": "Immutable. Ground truth added in Stage 8."
        })