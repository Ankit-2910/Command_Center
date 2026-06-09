"""
OBSIDIAN — Preferences Blueprint (Stage 1)
CAP 11 routing inputs.
"""
from flask import Blueprint, request, jsonify, session
from sqlalchemy import text
from db import get_session
from auth import login_required

prefs_bp = Blueprint("prefs", __name__, url_prefix="/api/preferences")


@prefs_bp.route("", methods=["GET"])
@login_required
def get_preferences():
    uid = session["user_id"]
    with get_session() as s:
        row = s.execute(text("""
            SELECT channel_email, channel_push, channel_slack, channel_teams, channel_sms,
                   slack_webhook_url, teams_webhook_url, phone_e164,
                   severity_threshold, quiet_hours_start, quiet_hours_end,
                   vacation_mode, vacation_until,
                   morning_digest_time, evening_digest_time, weekly_brief_enabled,
                   updated_at
            FROM obs_user_preferences WHERE user_id = :uid
        """), {"uid": uid}).fetchone()

        if not row:
            return jsonify({"error": "not_found"}), 404

        d = dict(row._mapping)
        for k in ("quiet_hours_start", "quiet_hours_end",
                  "morning_digest_time", "evening_digest_time"):
            if d.get(k):
                d[k] = d[k].strftime("%H:%M")
        if d.get("vacation_until"):
            d["vacation_until"] = d["vacation_until"].isoformat()
        if d.get("updated_at"):
            d["updated_at"] = d["updated_at"].isoformat()

        return jsonify({"preferences": d})


@prefs_bp.route("", methods=["PUT"])
@login_required
def update_preferences():
    uid = session["user_id"]
    data = request.get_json(silent=True) or {}

    allowed = {
        "channel_email", "channel_push", "channel_slack", "channel_teams", "channel_sms",
        "slack_webhook_url", "teams_webhook_url", "phone_e164",
        "severity_threshold", "quiet_hours_start", "quiet_hours_end",
        "vacation_mode", "vacation_until",
        "morning_digest_time", "evening_digest_time", "weekly_brief_enabled"
    }
    payload = {k: v for k, v in data.items() if k in allowed}

    if not payload:
        return jsonify({"error": "no_valid_fields"}), 400

    if "severity_threshold" in payload:
        try:
            val = int(payload["severity_threshold"])
            if not (0 <= val <= 100):
                raise ValueError
            payload["severity_threshold"] = val
        except (TypeError, ValueError):
            return jsonify({"error": "invalid_severity_threshold"}), 400

    set_clauses = ", ".join(f"{k} = :{k}" for k in payload.keys())
    payload["uid"] = uid

    with get_session() as s:
        s.execute(text(f"""
            UPDATE obs_user_preferences
            SET {set_clauses}, updated_at = NOW()
            WHERE user_id = :uid
        """), payload)

    return jsonify({"ok": True, "updated_fields": list(payload.keys() - {"uid"})})