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
    "adi.obsidian@gmail.com",
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