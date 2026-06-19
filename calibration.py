"""
OBSIDIAN — Calibration Metrics Engine (Stage 8)

Joins obs_predictions (predicted) against obs_ground_truth (actual) and
computes calibration metrics that turn the prediction log into a trust asset:

  - MAE (Mean Absolute Error)  : severity, duration  (numeric error)
  - Brier score                : scenario            (probability calibration)
  - Accuracy / hit-rate        : industry_impact     (did predicted sectors hit?)
  - Calibration curve          : all confidence-scored predictions
        (does "70% confidence" actually come true ~70% of the time?)

Reads ONLY. No new tables, no writes. Predictions and ground truth are immutable.

Low-data handling: with few labels, returns honest "insufficient data" flags
instead of misleading point estimates. Auto-populates as labels accrue.

Endpoints:
  GET /admin/calibration          → the calibration dashboard
  GET /api/calibration/metrics    → the metrics JSON

Register in app.py:
    from calibration import calibration_bp
    app.register_blueprint(calibration_bp)
"""
import json
import logging

from flask import Blueprint, jsonify, render_template_string
from sqlalchemy import text
from db import get_session

log = logging.getLogger("obsidian.calibration")

calibration_bp = Blueprint("calibration", __name__)

# Below this many labels of a given type, metrics are shown but flagged unstable.
MIN_STABLE_SAMPLES = 30


# ══════════════════════════════════════════════════════════════════════════
# PURE MATH CORE  (no DB — unit-tested against hand-calculations)
# ══════════════════════════════════════════════════════════════════════════

def mae(pairs):
    """pairs: list of (predicted_number, actual_number). Returns MAE or None."""
    vals = [abs(a - p) for p, a in pairs if p is not None and a is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def brier_scenario(forecast_probs, actual_scenario):
    """
    forecast_probs: dict {scenario_name: probability}
    actual_scenario: the scenario that actually occurred
    Returns Brier score (0 = perfect, higher = worse) across all options.
    """
    if not forecast_probs or actual_scenario is None:
        return None
    n = len(forecast_probs)
    if n == 0:
        return None
    total = 0.0
    for name, p in forecast_probs.items():
        outcome = 1.0 if name == actual_scenario else 0.0
        total += (p - outcome) ** 2
    return total / n


def accuracy(hits):
    """hits: list of bool. Returns fraction correct or None."""
    if not hits:
        return None
    return sum(1 for h in hits if h) / len(hits)


def calibration_curve(buckets):
    """
    buckets: list of (confidence_0_to_1, was_correct_bool).
    Bins into deciles, returns per-bin {claimed, observed, count}.
    Lets you see if claimed confidence matches observed hit-rate.
    """
    bins = {}
    for conf, correct in buckets:
        if conf is None:
            continue
        b = min(9, int(conf * 10))  # 0-9 decile
        bins.setdefault(b, {"correct": 0, "total": 0})
        bins[b]["total"] += 1
        if correct:
            bins[b]["correct"] += 1
    out = []
    for b in sorted(bins):
        d = bins[b]
        claimed = (b * 10 + 5) / 100.0  # bin midpoint, e.g. bin 8 -> 0.85
        observed = d["correct"] / d["total"] if d["total"] else 0.0
        out.append({
            "band": f"{b*10}-{b*10+10}%",
            "claimed": round(claimed, 3),
            "observed": round(observed, 3),
            "count": d["total"],
        })
    return out


# ══════════════════════════════════════════════════════════════════════════
# DB LAYER — pull paired predictions + outcomes, run the math
# ══════════════════════════════════════════════════════════════════════════

def _safe_json(v):
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return {}


def compute_all_metrics():
    """
    Pull every labeled prediction, compute per-type metrics + calibration curve.
    Returns a dict ready to serialize for the dashboard.
    """
    with get_session() as s:
        rows = s.execute(text("""
            SELECT p.prediction_type, p.predicted_value, p.confidence_score,
                   g.outcome_value
            FROM obs_ground_truth g
            JOIN obs_predictions p ON p.id = g.prediction_id
        """)).fetchall()

    severity_pairs = []
    duration_pairs = []
    scenario_briers = []
    industry_hits = []
    curve_points = []  # (confidence, correct_bool)

    for r in rows:
        pv = _safe_json(r.predicted_value)
        ov = _safe_json(r.outcome_value)
        conf = (r.confidence_score or 0) / 100.0
        ptype = r.prediction_type

        if ptype == "severity":
            p = pv.get("severity_score")
            a = ov.get("actual_severity")
            if p is not None and a is not None:
                severity_pairs.append((p, a))
                # "correct" if within 10 points, for the calibration curve
                curve_points.append((conf, abs(a - p) <= 10))

        elif ptype == "duration":
            p = pv.get("modal_days")
            a = ov.get("actual_days")
            if p is not None and a is not None:
                duration_pairs.append((p, a))
                # within 25% of modal counts as "correct"
                tol = max(7, 0.25 * p)
                curve_points.append((conf, abs(a - p) <= tol))

        elif ptype == "scenario":
            scenarios = pv.get("scenarios", [])
            probs = {sc.get("scenario"): sc.get("probability", 0) for sc in scenarios}
            actual = ov.get("actual_scenario")
            b = brier_scenario(probs, actual)
            if b is not None:
                scenario_briers.append(b)
                # "correct" if the highest-probability scenario is what happened
                if probs:
                    top = max(probs, key=probs.get)
                    curve_points.append((conf, top == actual))

        elif ptype == "industry_impact":
            hit = ov.get("sectors_impacted")
            if hit is not None:
                industry_hits.append(bool(hit))
                curve_points.append((conf, bool(hit)))

    def wrap(value, count, label):
        return {
            "value": round(value, 4) if value is not None else None,
            "count": count,
            "stable": count >= MIN_STABLE_SAMPLES,
            "label": label,
        }

    sev_mae = mae(severity_pairs)
    dur_mae = mae(duration_pairs)
    scn_brier = (sum(scenario_briers) / len(scenario_briers)) if scenario_briers else None
    ind_acc = accuracy(industry_hits)

    total_labeled = len(rows)

    return {
        "total_labeled": total_labeled,
        "min_stable_samples": MIN_STABLE_SAMPLES,
        "metrics": {
            "severity_mae": wrap(sev_mae, len(severity_pairs), "Severity MAE (points off)"),
            "duration_mae": wrap(dur_mae, len(duration_pairs), "Duration MAE (days off)"),
            "scenario_brier": wrap(scn_brier, len(scenario_briers), "Scenario Brier (0=perfect)"),
            "industry_accuracy": wrap(ind_acc, len(industry_hits), "Industry hit-rate"),
        },
        "calibration_curve": calibration_curve(curve_points),
    }


# ══════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════

@calibration_bp.route("/api/calibration/metrics", methods=["GET"])
def api_calibration_metrics():
    return jsonify(compute_all_metrics())


@calibration_bp.route("/admin/calibration", methods=["GET"])
def calibration_page():
    return render_template_string(CALIBRATION_HTML)


from calibration_ui import CALIBRATION_HTML  # noqa: E402
