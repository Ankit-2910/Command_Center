"""
OBSIDIAN — Ground Truth Labeling API (Stage 7)

Lets an analyst record the ACTUAL outcome of a locked prediction.
Outcomes are stored in obs_ground_truth, keyed by prediction_id.
Predictions themselves are never modified — they remain immutable.

This is the data layer Stage 8 (calibration metrics) consumes:
  predicted_value (obs_predictions) vs outcome_value (obs_ground_truth)
  → Brier score, MAE, accuracy.

Endpoints:
  GET  /admin/labeling                  → the analyst UI page
  GET  /api/labeling/pending            → predictions awaiting a label
  GET  /api/labeling/labeled            → already-labeled predictions
  POST /api/labeling/submit             → save an outcome label

Register in app.py:
    from labeling import labeling_bp
    app.register_blueprint(labeling_bp)
"""
import json
import logging
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, render_template_string
from sqlalchemy import text
from db import get_session

log = logging.getLogger("obsidian.labeling")

labeling_bp = Blueprint("labeling", __name__)


# ──────────────────────────────────────────────────────────
# Outcome schema per prediction type
# Defines what the analyst records for each type.
# ──────────────────────────────────────────────────────────

OUTCOME_SCHEMA = {
    "severity": {
        "label": "What severity did the event actually reach? (0-100)",
        "field": "actual_severity",
        "input": "number",
    },
    "duration": {
        "label": "How many days did the event actually last?",
        "field": "actual_days",
        "input": "number",
    },
    "scenario": {
        "label": "Which scenario actually occurred?",
        "field": "actual_scenario",
        "input": "choice",
        "choices": ["de_escalation", "sustained", "escalation"],
    },
    "industry_impact": {
        "label": "Did the predicted sectors actually get materially impacted?",
        "field": "sectors_impacted",
        "input": "boolean",
    },
}


# ──────────────────────────────────────────────────────────
# GET pending predictions (no label yet)
# ──────────────────────────────────────────────────────────

@labeling_bp.route("/api/labeling/pending", methods=["GET"])
def pending_labels():
    """
    Return locked predictions that have NO ground-truth row yet.
    Joins the event for context (headline, severity).
    """
    with get_session() as s:
        rows = s.execute(text("""
            SELECT p.id, p.event_id, p.prediction_type, p.predicted_value,
                   p.confidence_score, p.horizon_days, p.made_at,
                   e.headline, e.severity AS event_severity, e.geographic_scope
            FROM obs_predictions p
            LEFT JOIN obs_events e ON e.id = p.event_id
            WHERE NOT EXISTS (
                SELECT 1 FROM obs_ground_truth g WHERE g.prediction_id = p.id
            )
            ORDER BY p.made_at ASC
        """)).fetchall()

    items = []
    for r in rows:
        schema = OUTCOME_SCHEMA.get(r.prediction_type, {})
        items.append({
            "prediction_id": str(r.id),
            "event_id": str(r.event_id),
            "prediction_type": r.prediction_type,
            "predicted_value": r.predicted_value,
            "confidence_score": r.confidence_score,
            "horizon_days": r.horizon_days,
            "made_at": r.made_at.isoformat() if r.made_at else None,
            "headline": r.headline,
            "event_severity": r.event_severity,
            "geographic_scope": r.geographic_scope,
            "outcome_schema": schema,
        })

    return jsonify({"count": len(items), "pending": items})


# ──────────────────────────────────────────────────────────
# GET already-labeled predictions
# ──────────────────────────────────────────────────────────

@labeling_bp.route("/api/labeling/labeled", methods=["GET"])
def labeled_predictions():
    with get_session() as s:
        rows = s.execute(text("""
            SELECT g.id, g.prediction_id, g.outcome_value, g.accuracy_score,
                   g.miss_reason, g.labeled_by, g.labeled_at, g.notes,
                   p.prediction_type, p.predicted_value,
                   e.headline
            FROM obs_ground_truth g
            JOIN obs_predictions p ON p.id = g.prediction_id
            LEFT JOIN obs_events e ON e.id = g.event_id
            ORDER BY g.labeled_at DESC
        """)).fetchall()

    items = [{
        "ground_truth_id": str(r.id),
        "prediction_id": str(r.prediction_id),
        "prediction_type": r.prediction_type,
        "predicted_value": r.predicted_value,
        "outcome_value": r.outcome_value,
        "accuracy_score": float(r.accuracy_score) if r.accuracy_score is not None else None,
        "miss_reason": r.miss_reason,
        "labeled_by": r.labeled_by,
        "labeled_at": r.labeled_at.isoformat() if r.labeled_at else None,
        "notes": r.notes,
        "headline": r.headline,
    } for r in rows]

    return jsonify({"count": len(items), "labeled": items})


# ──────────────────────────────────────────────────────────
# POST submit a label
# ──────────────────────────────────────────────────────────

@labeling_bp.route("/api/labeling/submit", methods=["POST"])
def submit_label():
    """
    Save an outcome label for a prediction.

    Expected JSON body:
      {
        "prediction_id": "<uuid>",
        "outcome_value": { ... },        # the actual outcome, shape per type
        "labeled_by": "Ankit",           # analyst name
        "miss_reason": "optional text",
        "accuracy_score": optional number,
        "review_window_days": optional int,
        "notes": "optional text"
      }
    """
    data = request.get_json(silent=True) or {}
    prediction_id = data.get("prediction_id")
    outcome_value = data.get("outcome_value")
    labeled_by = (data.get("labeled_by") or "").strip() or "unknown"

    if not prediction_id:
        return jsonify({"error": "missing_prediction_id"}), 400
    if outcome_value is None:
        return jsonify({"error": "missing_outcome_value"}), 400

    with get_session() as s:
        # Verify the prediction exists and grab its event_id
        pred = s.execute(text("""
            SELECT id, event_id, prediction_type FROM obs_predictions WHERE id = :pid
        """), {"pid": prediction_id}).fetchone()

        if not pred:
            return jsonify({"error": "prediction_not_found"}), 404

        # Prevent double-labeling
        existing = s.execute(text("""
            SELECT id FROM obs_ground_truth WHERE prediction_id = :pid
        """), {"pid": prediction_id}).fetchone()

        if existing:
            return jsonify({
                "error": "already_labeled",
                "detail": "This prediction already has a ground-truth label.",
                "ground_truth_id": str(existing.id),
            }), 409

        row = s.execute(text("""
            INSERT INTO obs_ground_truth
            (prediction_id, event_id, outcome_value, accuracy_score,
             miss_reason, labeled_by, review_window_days, notes, labeled_at)
            VALUES
            (:pid, :eid, CAST(:ov AS jsonb), :acc,
             :miss, :by, :rwd, :notes, NOW())
            RETURNING id
        """), {
            "pid": prediction_id,
            "eid": str(pred.event_id),
            "ov": json.dumps(outcome_value),
            "acc": data.get("accuracy_score"),
            "miss": data.get("miss_reason"),
            "by": labeled_by,
            "rwd": data.get("review_window_days"),
            "notes": data.get("notes"),
        }).fetchone()

    log.info(f"ground_truth_labeled | prediction={prediction_id} | by={labeled_by}")
    return jsonify({
        "ok": True,
        "ground_truth_id": str(row.id),
        "prediction_id": prediction_id,
    })


# ──────────────────────────────────────────────────────────
# GET the labeling UI page
# ──────────────────────────────────────────────────────────

@labeling_bp.route("/admin/labeling", methods=["GET"])
def labeling_page():
    return render_template_string(LABELING_HTML)


# UI is defined in labeling_ui.py to keep this file focused; imported lazily.
from labeling_ui import LABELING_HTML  # noqa: E402
