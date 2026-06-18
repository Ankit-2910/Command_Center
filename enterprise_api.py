"""
OBSIDIAN — Enterprise Read API (Stage 6B, pull side)

Authenticated JSON API for partners to pull intelligence programmatically.

Auth model:
  - Partner sends:  Authorization: Bearer <raw_api_key>
  - We SHA-256 the raw key and look up the hash in obs_api_keys.
  - Plaintext keys are NEVER stored. A DB leak exposes only hashes.

Endpoints (all require a valid key):
  GET /api/v1/events?severity_min=70&limit=50   → list events
  GET /api/v1/events/<event_id>                 → single event
  GET /api/v1/briefs/<brief_id>                 → single brief

Register the blueprint in app.py:
    from enterprise_api import api_v1_bp
    app.register_blueprint(api_v1_bp)
"""
import hashlib
import logging
from functools import wraps
from datetime import datetime

from flask import Blueprint, request, jsonify, g
from sqlalchemy import text
from db import get_session

log = logging.getLogger("obsidian.enterprise_api")

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


def _hash_key(raw_key: str) -> str:
    """SHA-256 hex digest of a raw API key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def require_api_key(fn):
    """
    Decorator: validates the Bearer token against obs_api_keys.
    On success, stashes the key row on flask.g and updates last_used_at.
    On failure, returns 401 with a clear JSON error.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({
                "error": "unauthorized",
                "detail": "Missing or malformed Authorization header. "
                          "Use: Authorization: Bearer <api_key>"
            }), 401

        raw_key = auth[7:].strip()
        if not raw_key:
            return jsonify({"error": "unauthorized", "detail": "Empty API key"}), 401

        key_hash = _hash_key(raw_key)
        with get_session() as s:
            row = s.execute(text("""
                SELECT id, partner_name, scopes, active
                FROM obs_api_keys
                WHERE key_hash = :kh
            """), {"kh": key_hash}).fetchone()

            if not row:
                return jsonify({"error": "unauthorized", "detail": "Invalid API key"}), 401
            if not row.active:
                return jsonify({"error": "forbidden", "detail": "API key is disabled"}), 403

            # Touch last_used_at (best-effort)
            s.execute(text("""
                UPDATE obs_api_keys SET last_used_at = NOW() WHERE id = :id
            """), {"id": row.id})

            g.partner_name = row.partner_name
            g.api_key_id = str(row.id)

        return fn(*args, **kwargs)
    return wrapper


# ── ENDPOINTS ───────────────────────────────────────────────────────────────

@api_v1_bp.route("/events", methods=["GET"])
@require_api_key
def list_events():
    """
    List events, newest first.
    Query params:
      severity_min (int, default 0)
      limit        (int, default 50, max 200)
    """
    try:
        severity_min = int(request.args.get("severity_min", 0))
    except ValueError:
        severity_min = 0
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
    except ValueError:
        limit = 50

    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, headline, summary, severity, confidence,
                   event_type, geographic_scope, detected_at
            FROM obs_events
            WHERE severity >= :smin
            ORDER BY detected_at DESC NULLS LAST
            LIMIT :lim
        """), {"smin": severity_min, "lim": limit}).fetchall()

    events = [{
        "id": str(r.id),
        "headline": r.headline,
        "summary": r.summary,
        "severity": r.severity,
        "confidence": r.confidence,
        "event_type": r.event_type,
        "geographic_scope": r.geographic_scope,
        "detected_at": r.detected_at.isoformat() if r.detected_at else None,
    } for r in rows]

    return jsonify({
        "partner": g.partner_name,
        "count": len(events),
        "events": events,
    })


@api_v1_bp.route("/events/<event_id>", methods=["GET"])
@require_api_key
def get_event(event_id):
    with get_session() as s:
        r = s.execute(text("""
            SELECT id, headline, summary, severity, confidence,
                   event_type, geographic_scope, entities, industries, detected_at
            FROM obs_events WHERE id = :eid
        """), {"eid": event_id}).fetchone()

    if not r:
        return jsonify({"error": "not_found", "detail": "Event not found"}), 404

    return jsonify({
        "id": str(r.id),
        "headline": r.headline,
        "summary": r.summary,
        "severity": r.severity,
        "confidence": r.confidence,
        "event_type": r.event_type,
        "geographic_scope": r.geographic_scope,
        "entities": r.entities,
        "industries": r.industries,
        "detected_at": r.detected_at.isoformat() if r.detected_at else None,
    })


@api_v1_bp.route("/briefs/<brief_id>", methods=["GET"])
@require_api_key
def get_brief(brief_id):
    with get_session() as s:
        r = s.execute(text("""
            SELECT b.id, b.event_id, b.role_view, b.content_md,
                   b.confidence, b.generated_at,
                   e.headline, e.severity
            FROM obs_briefs b
            LEFT JOIN obs_events e ON e.id = b.event_id
            WHERE b.id = :bid
        """), {"bid": brief_id}).fetchone()

    if not r:
        return jsonify({"error": "not_found", "detail": "Brief not found"}), 404

    return jsonify({
        "id": str(r.id),
        "event_id": str(r.event_id) if r.event_id else None,
        "headline": r.headline,
        "role_view": r.role_view,
        "content_md": r.content_md,
        "severity": r.severity,
        "confidence": r.confidence,
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
    })


@api_v1_bp.route("/ping", methods=["GET"])
@require_api_key
def ping():
    """Auth smoke-test endpoint for partners."""
    return jsonify({"ok": True, "partner": g.partner_name, "ts": datetime.utcnow().isoformat()})
