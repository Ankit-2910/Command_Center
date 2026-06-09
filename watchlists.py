"""
OBSIDIAN — Watchlists Blueprint (Stage 1)
Targeting layer for CAP 11 routing + CAP 3 alert matching.
"""
from flask import Blueprint, request, jsonify, session
from sqlalchemy import text
from db import get_session
from auth import login_required

watch_bp = Blueprint("watch", __name__, url_prefix="/api/watchlists")

VALID_ENTITY_TYPES = {
    "region", "country", "chokepoint", "company",
    "industry", "commodity", "keyword"
}


@watch_bp.route("", methods=["GET"])
@login_required
def list_watchlists():
    uid = session["user_id"]
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, name, entity_type, entity_value, priority, created_at
            FROM obs_watchlists
            WHERE user_id = :uid
            ORDER BY priority DESC, created_at DESC
        """), {"uid": uid}).fetchall()

        items = []
        for r in rows:
            d = dict(r._mapping)
            d["id"] = str(d["id"])
            d["created_at"] = d["created_at"].isoformat()
            items.append(d)

        return jsonify({"watchlists": items, "count": len(items)})


@watch_bp.route("", methods=["POST"])
@login_required
def create_watchlist():
    uid = session["user_id"]
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    entity_type = (data.get("entity_type") or "").strip().lower()
    entity_value = (data.get("entity_value") or "").strip()
    priority = data.get("priority", 5)

    if not name or len(name) > 100:
        return jsonify({"error": "invalid_name"}), 400
    if entity_type not in VALID_ENTITY_TYPES:
        return jsonify({"error": "invalid_entity_type",
                        "allowed": list(VALID_ENTITY_TYPES)}), 400
    if not entity_value or len(entity_value) > 200:
        return jsonify({"error": "invalid_entity_value"}), 400
    try:
        priority = int(priority)
        if not (1 <= priority <= 10):
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_priority"}), 400

    with get_session() as s:
        row = s.execute(text("""
            INSERT INTO obs_watchlists (user_id, name, entity_type, entity_value, priority)
            VALUES (:uid, :name, :etype, :evalue, :prio)
            RETURNING id
        """), {
            "uid": uid, "name": name,
            "etype": entity_type, "evalue": entity_value, "prio": priority
        }).fetchone()

    return jsonify({"ok": True, "id": str(row.id)}), 201


@watch_bp.route("/<watchlist_id>", methods=["DELETE"])
@login_required
def delete_watchlist(watchlist_id):
    uid = session["user_id"]
    with get_session() as s:
        result = s.execute(text("""
            DELETE FROM obs_watchlists
            WHERE id = :wid AND user_id = :uid
            RETURNING id
        """), {"wid": watchlist_id, "uid": uid}).fetchone()

        if not result:
            return jsonify({"error": "not_found"}), 404

    return jsonify({"ok": True})