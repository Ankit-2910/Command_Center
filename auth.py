"""
OBSIDIAN — Auth Blueprint (Stage 1)
Passwordless identification. Magic link auth in Stage 3.
"""
import re
from flask import Blueprint, request, session, jsonify
from functools import wraps
from sqlalchemy import text
from db import get_session

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
VALID_ROLES = {"ceo", "cfo", "coo", "procurement", "logistics", "risk", "analyst", "custom"}


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "auth_required"}), 401
        return fn(*args, **kwargs)
    return wrapper


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    with get_session() as s:
        row = s.execute(text("""
            SELECT id, email, name, role, timezone
            FROM obs_users WHERE id = :uid AND is_active = TRUE
        """), {"uid": uid}).fetchone()
        return dict(row._mapping) if row else None


@auth_bp.route("/claim", methods=["POST"])
def claim_profile():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip()
    role = (data.get("role") or "analyst").strip().lower()

    if not EMAIL_RE.match(email):
        return jsonify({"error": "invalid_email"}), 400
    if not name or len(name) > 100:
        return jsonify({"error": "invalid_name"}), 400
    if role not in VALID_ROLES:
        role = "analyst"

    with get_session() as s:
        existing = s.execute(text("""
            SELECT id FROM obs_users WHERE email = :email
        """), {"email": email}).fetchone()

        if existing:
            user_id = existing.id
            s.execute(text("""
                UPDATE obs_users
                SET name = :name, role = :role,
                    last_active_at = NOW(), is_active = TRUE
                WHERE id = :uid
            """), {"name": name, "role": role, "uid": user_id})
        else:
            row = s.execute(text("""
                INSERT INTO obs_users (email, name, role)
                VALUES (:email, :name, :role)
                RETURNING id
            """), {"email": email, "name": name, "role": role}).fetchone()
            user_id = row.id

            s.execute(text("""
                INSERT INTO obs_user_preferences (user_id)
                VALUES (:uid) ON CONFLICT (user_id) DO NOTHING
            """), {"uid": user_id})

    session.permanent = True
    session["user_id"] = str(user_id)
    session["email"] = email

    return jsonify({
        "ok": True,
        "user": {"id": str(user_id), "email": email, "name": name, "role": role}
    })


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@auth_bp.route("/me", methods=["GET"])
def me():
    user = current_user()
    if not user:
        return jsonify({"authenticated": False}), 200
    return jsonify({
        "authenticated": True,
        "user": {
            "id": str(user["id"]),
            "email": user["email"],
            "name": user["name"],
            "role": user["role"],
            "timezone": user["timezone"]
        }
    })