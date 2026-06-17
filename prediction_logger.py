"""
OBSIDIAN — CAP 12 Prediction Logger (Stage 5B)

Every time OBSIDIAN routes an event, it implicitly makes predictions:
  - Severity score (how bad is this?)
  - Duration estimate (how long will this last?)
  - Industry impact (which sectors are affected?)
  - Confidence score (how sure are we?)

This module captures those predictions IMMUTABLY the moment they're made.
They cannot be edited after the fact — this is what makes them defensible.
Ground truth (what actually happened) gets added later in Stage 8.
The calibration metrics in Stage 9 compare predictions vs ground truth.

Why this matters: by Month 12, you'll have 12 months of timestamped,
immutable predictions with verified outcomes. No competitor can replicate
this without waiting 12 months themselves. This is the moat.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import text
from db import get_session

log = logging.getLogger("obsidian.predictions")

MODEL_VERSION = "obsidian-v0.4"  # bump this when routing logic changes


# ──────────────────────────────────────────────────────────
# PREDICTION EXTRACTORS
# These translate raw event data into structured predictions
# ──────────────────────────────────────────────────────────

def _predict_duration_days(severity: int, event_type: str) -> dict:
    """
    Estimate event duration based on severity and type.
    Returns a range dict with modal estimate.
    This will be calibrated against reality in Stage 9.
    """
    base_ranges = {
        "maritime_disruption": {"min": 30, "modal": 90, "max": 180},
        "geopolitical":        {"min": 60, "modal": 180, "max": 365},
        "sanctions":           {"min": 180, "modal": 365, "max": 730},
        "maritime_update":     {"min": 7,  "modal": 30,  "max": 90},
        "commodity_shock":     {"min": 14, "modal": 60,  "max": 120},
        "natural_disaster":    {"min": 7,  "modal": 21,  "max": 60},
        "regulatory":          {"min": 30, "modal": 90,  "max": 365},
    }

    base = base_ranges.get(event_type, {"min": 14, "modal": 45, "max": 120})

    # Severity modifier: higher severity = longer duration
    modifier = 1.0
    if severity >= 85: modifier = 1.5
    elif severity >= 70: modifier = 1.2
    elif severity < 50: modifier = 0.7

    return {
        "min_days": int(base["min"] * modifier),
        "modal_days": int(base["modal"] * modifier),
        "max_days": int(base["max"] * modifier),
    }


def _predict_scenarios(severity: int, event_type: str) -> list:
    """
    Generate probability-weighted scenario forecasts.
    Three scenarios: de-escalation, sustained, escalation.
    Probabilities sum to 1.0.
    """
    if severity >= 85:
        return [
            {"scenario": "de_escalation", "probability": 0.20, "timeline_days": 45},
            {"scenario": "sustained",      "probability": 0.50, "timeline_days": 120},
            {"scenario": "escalation",     "probability": 0.30, "timeline_days": 365},
        ]
    elif severity >= 70:
        return [
            {"scenario": "de_escalation", "probability": 0.35, "timeline_days": 30},
            {"scenario": "sustained",      "probability": 0.45, "timeline_days": 90},
            {"scenario": "escalation",     "probability": 0.20, "timeline_days": 180},
        ]
    elif severity >= 50:
        return [
            {"scenario": "de_escalation", "probability": 0.55, "timeline_days": 14},
            {"scenario": "sustained",      "probability": 0.35, "timeline_days": 45},
            {"scenario": "escalation",     "probability": 0.10, "timeline_days": 90},
        ]
    else:
        return [
            {"scenario": "de_escalation", "probability": 0.70, "timeline_days": 7},
            {"scenario": "sustained",      "probability": 0.25, "timeline_days": 21},
            {"scenario": "escalation",     "probability": 0.05, "timeline_days": 60},
        ]


def _predict_industry_impact(industries: list, severity: int) -> list:
    """
    Score impact per affected industry (0-10 scale).
    """
    base_impact = min(10, int(severity / 10))
    return [
        {"industry": ind, "predicted_impact": base_impact, "confidence": 0.65}
        for ind in (industries or [])
    ]


# ──────────────────────────────────────────────────────────
# CORE: LOG ALL PREDICTIONS FOR AN EVENT
# ──────────────────────────────────────────────────────────

def log_predictions_for_event(event_id: str, brief_id: Optional[str] = None) -> dict:
    """
    Extract and immutably log all predictions for an event.
    Called automatically when routing engine processes an event.

    Returns:
        {"logged": int, "skipped": bool, "prediction_ids": [...]}
    """
    try:
        with get_session() as s:
            # Fetch event
            ev = s.execute(text("""
                SELECT id, severity, confidence, event_type, industries
                FROM obs_events WHERE id = :eid
            """), {"eid": event_id}).fetchone()

            if not ev:
                return {"logged": 0, "skipped": True, "reason": "event_not_found"}

            # Skip if already logged (idempotent)
            existing = s.execute(text("""
                SELECT COUNT(*) AS cnt FROM obs_predictions WHERE event_id = :eid
            """), {"eid": event_id}).fetchone()

            if existing and existing.cnt > 0:
                return {"logged": 0, "skipped": True, "reason": "already_logged"}

            severity = int(ev.severity or 0)
            confidence = int(ev.confidence or 60)
            event_type = ev.event_type or "unknown"
            industries = ev.industries if isinstance(ev.industries, list) else []
            if isinstance(ev.industries, str):
                try:
                    industries = json.loads(ev.industries)
                except Exception:
                    industries = []

            prediction_ids = []

            # PREDICTION 1: Severity score
            row = s.execute(text("""
                INSERT INTO obs_predictions
                (event_id, brief_id, prediction_type, predicted_value, 
                 confidence_score, horizon_days, model_version, is_locked)
                VALUES (:eid, :bid, 'severity',
                        :val::jsonb, :conf, 30, :mv, TRUE)
                RETURNING id
            """), {
                "eid": event_id, "bid": brief_id,
                "val": json.dumps({"severity_score": severity}),
                "conf": confidence, "mv": MODEL_VERSION
            }).fetchone()
            prediction_ids.append(str(row.id))

            # PREDICTION 2: Duration estimate
            duration = _predict_duration_days(severity, event_type)
            row = s.execute(text("""
                INSERT INTO obs_predictions
                (event_id, brief_id, prediction_type, predicted_value,
                 confidence_score, horizon_days, model_version, is_locked)
                VALUES (:eid, :bid, 'duration',
                        :val::jsonb, :conf, :horizon, :mv, TRUE)
                RETURNING id
            """), {
                "eid": event_id, "bid": brief_id,
                "val": json.dumps(duration),
                "conf": max(40, confidence - 15),
                "horizon": duration["modal_days"],
                "mv": MODEL_VERSION
            }).fetchone()
            prediction_ids.append(str(row.id))

            # PREDICTION 3: Scenarios
            scenarios = _predict_scenarios(severity, event_type)
            row = s.execute(text("""
                INSERT INTO obs_predictions
                (event_id, brief_id, prediction_type, predicted_value,
                 confidence_score, horizon_days, model_version, is_locked)
                VALUES (:eid, :bid, 'scenario',
                        :val::jsonb, :conf, :horizon, :mv, TRUE)
                RETURNING id
            """), {
                "eid": event_id, "bid": brief_id,
                "val": json.dumps({"scenarios": scenarios}),
                "conf": max(35, confidence - 20),
                "horizon": max(s["timeline_days"] for s in scenarios),
                "mv": MODEL_VERSION
            }).fetchone()
            prediction_ids.append(str(row.id))

            # PREDICTION 4: Industry impact
            if industries:
                impacts = _predict_industry_impact(industries, severity)
                row = s.execute(text("""
                    INSERT INTO obs_predictions
                    (event_id, brief_id, prediction_type, predicted_value,
                     confidence_score, horizon_days, model_version, is_locked)
                    VALUES (:eid, :bid, 'industry_impact',
                            :val::jsonb, :conf, 60, :mv, TRUE)
                    RETURNING id
                """), {
                    "eid": event_id, "bid": brief_id,
                    "val": json.dumps({"impacts": impacts}),
                    "conf": max(45, confidence - 10),
                    "mv": MODEL_VERSION
                }).fetchone()
                prediction_ids.append(str(row.id))

            log.info(f"predictions_logged | event={event_id} | count={len(prediction_ids)}")
            return {
                "logged": len(prediction_ids),
                "skipped": False,
                "prediction_ids": prediction_ids
            }

    except Exception as e:
        log.error(f"prediction_log_failed | event={event_id} | {e}")
        return {"logged": 0, "skipped": True, "reason": str(e)[:200]}