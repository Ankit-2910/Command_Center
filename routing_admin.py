"""
OBSIDIAN — Routing Admin Blueprint (Stage 2)

Admin-facing routes for visualizing and testing the routing engine.
- GET  /admin/routing-simulator         — UI page
- GET  /api/admin/recent-events         — list recent events for picker
- POST /api/admin/route-event           — trigger routing on an event
- GET  /api/admin/deliveries/<event_id> — show all decisions for an event
"""
from flask import Blueprint, request, jsonify, session, render_template
from sqlalchemy import text
from db import get_session
from auth import login_required, current_user
from routing import route_event

admin_bp = Blueprint("routing_admin", __name__)

# Master accounts that get admin access
MASTER_EMAILS = {
    "adi.obsdian@gmail.com",
    "ankitdubey.aitech@gmail.com"
}


def admin_required(fn):
    """Decorator: only master accounts can hit admin routes."""
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "auth_required"}), 401
        user = current_user()
        if not user or user["email"] not in MASTER_EMAILS:
            return jsonify({"error": "admin_only"}), 403
        return fn(*args, **kwargs)
    return wrapper


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
            SELECT id, headline, severity, event_type, geographic_scope,
                   detected_at
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
                   d.routing_log, d.routed_at,
                   u.email, u.name, u.role
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
    @admin_bp.route("/admin/engagement")
@admin_required
def engagement_page():
    return render_template("engagement.html")


@admin_bp.route("/api/admin/engagement-summary", methods=["GET"])
@admin_required
def engagement_summary():
    """
    Returns per-user engagement stats + recent batch-level detail.
    """
    with get_session() as s:
        # Per-user rollup
        user_rows = s.execute(text("""
            SELECT 
                u.email, u.role,
                COUNT(b.id) AS total_sent,
                COUNT(b.opened_at) AS total_opened,
                COUNT(b.first_click_at) AS total_clicked,
                MAX(b.sent_at) AS last_sent,
                MAX(b.opened_at) AS last_opened
            FROM obs_users u
            LEFT JOIN obs_digest_batches b ON b.user_id = u.id AND b.status IN ('sent','delivered','opened')
            WHERE u.is_active = TRUE
            GROUP BY u.email, u.role
            ORDER BY u.role
        """)).fetchall()

        users = []
        for r in user_rows:
            total_sent = r.total_sent or 0
            total_opened = r.total_opened or 0
            total_clicked = r.total_clicked or 0
            users.append({
                "email": r.email,
                "role": r.role,
                "total_sent": total_sent,
                "total_opened": total_opened,
                "total_clicked": total_clicked,
                "open_rate": round(100 * total_opened / total_sent, 1) if total_sent else 0,
                "click_rate": round(100 * total_clicked / total_sent, 1) if total_sent else 0,
                "last_sent": r.last_sent.isoformat() if r.last_sent else None,
                "last_opened": r.last_opened.isoformat() if r.last_opened else None,
            })

        # Recent batches (last 20)
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