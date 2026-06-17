"""
OBSIDIAN — Routing Engine (Stage 2 / CAP 11 brain)

The pure-logic decision function that takes an event and emits
delivery decisions for every active user. Does NOT send anything —
writes decisions to obs_deliveries with status='queued'. Stage 3
picks up queued deliveries and actually sends emails.

Architecture: see CAP 11 routing decision cube in design docs.
"""

import json
import logging
from prediction_logger import log_predictions_for_event
from datetime import datetime, timedelta, time
from typing import Optional
from zoneinfo import ZoneInfo
from sqlalchemy import text
from db import get_session

log = logging.getLogger("obsidian.routing")

# ──────────────────────────────────────────────────────────
# ROUTING CUBE — Severity × Channel matrix
# Source of truth for "given severity X on channel Y, what cadence?"
# ──────────────────────────────────────────────────────────

# Severity tier mapping
def severity_tier(severity: int) -> str:
    if severity >= 85:  return "critical"
    if severity >= 70:  return "high"
    if severity >= 50:  return "elevated"
    return "low"

# Channel → (severity_tier → delivery_type)
# delivery_type: "immediate" / "bundled" / "digest" / "off"
ROUTING_CUBE = {
    "email": {
        "critical": "immediate",
        "high":     "immediate",
        "elevated": "bundled",       # bundle into morning digest
        "low":      "digest",
    },
    "push": {
        "critical": "immediate",
        "high":     "immediate",
        "elevated": "digest",
        "low":      "off",
    },
    "sms": {
        "critical": "immediate",
        "high":     "off",
        "elevated": "off",
        "low":      "off",
    },
    "slack": {
        "critical": "immediate",
        "high":     "immediate",
        "elevated": "digest",
        "low":      "digest",
    },
    "teams": {
        "critical": "immediate",
        "high":     "immediate",
        "elevated": "digest",
        "low":      "digest",
    },
}

# Fatigue rule constants
SEVERITY_DECAY_WINDOW_HRS = 6
SEVERITY_DECAY_DELTA_MIN  = 10
PUSH_WATCHLIST_OR_CRITICAL = 80
QUIET_HOURS_BREAK_THRESHOLD = 90


# ──────────────────────────────────────────────────────────
# WATCHLIST MATCHING
# ──────────────────────────────────────────────────────────

def _match_watchlist(user_id: str, event: dict, session) -> dict:
    """
    Returns:
        {
          "matched": bool,
          "max_priority": int (0-10, 0 if no match),
          "matched_entries": [{name, entity_type, entity_value, priority}, ...]
        }
    """
    rows = session.execute(text("""
        SELECT name, entity_type, entity_value, priority
        FROM obs_watchlists WHERE user_id = :uid
    """), {"uid": user_id}).fetchall()

    if not rows:
        return {"matched": False, "max_priority": 0, "matched_entries": []}

    event_text = " ".join([
        (event.get("headline") or ""),
        (event.get("summary") or ""),
        " ".join(event.get("entities", []) if isinstance(event.get("entities"), list) else []),
        " ".join(event.get("industries", []) if isinstance(event.get("industries"), list) else []),
        (event.get("geographic_scope") or ""),
    ]).lower()

    matches = []
    for r in rows:
        entity_value = (r.entity_value or "").lower().strip()
        if not entity_value:
            continue
        if entity_value in event_text:
            matches.append({
                "name": r.name,
                "entity_type": r.entity_type,
                "entity_value": r.entity_value,
                "priority": r.priority
            })

    if not matches:
        return {"matched": False, "max_priority": 0, "matched_entries": []}

    return {
        "matched": True,
        "max_priority": max(m["priority"] for m in matches),
        "matched_entries": matches
    }


# ──────────────────────────────────────────────────────────
# QUIET HOURS CHECK
# ──────────────────────────────────────────────────────────

def _is_quiet_hours(prefs: dict, user_tz: str) -> bool:
    """Returns True if current time in user's timezone is within quiet hours."""
    qstart = prefs.get("quiet_hours_start")
    qend = prefs.get("quiet_hours_end")
    if not qstart or not qend:
        return False

    try:
        tz = ZoneInfo(user_tz or "Asia/Kolkata")
    except Exception:
        tz = ZoneInfo("Asia/Kolkata")
    
    now_local = datetime.now(tz).time()
    
    # Handle overnight quiet hours (e.g., 22:00 - 07:00)
    if qstart <= qend:
        return qstart <= now_local <= qend
    else:
        return now_local >= qstart or now_local <= qend


# ──────────────────────────────────────────────────────────
# FATIGUE RULES
# ──────────────────────────────────────────────────────────

def _check_severity_decay(user_id: str, event_id: str, current_severity: int, session) -> dict:
    """
    Rule 1: Don't re-alert same event within 6 hrs unless severity +10.
    Returns: {"blocked": bool, "reason": str}
    """
    cutoff = datetime.now() - timedelta(hours=SEVERITY_DECAY_WINDOW_HRS)
    
    row = session.execute(text("""
        SELECT severity, routed_at FROM obs_deliveries
        WHERE user_id = :uid AND event_id = :eid
          AND routed_at >= :cutoff
          AND status IN ('queued', 'sent', 'delivered', 'opened')
        ORDER BY routed_at DESC LIMIT 1
    """), {"uid": user_id, "eid": event_id, "cutoff": cutoff}).fetchone()

    if not row:
        return {"blocked": False, "reason": "first_alert_in_window"}
    
    severity_delta = current_severity - (row.severity or 0)
    if severity_delta < SEVERITY_DECAY_DELTA_MIN:
        return {
            "blocked": True,
            "reason": f"recent_alert_severity_delta_only_{severity_delta}"
        }
    
    return {"blocked": False, "reason": f"severity_escalated_+{severity_delta}"}


# ──────────────────────────────────────────────────────────
# CORE: EVALUATE ONE USER FOR ONE EVENT
# ──────────────────────────────────────────────────────────

def _evaluate_user(user: dict, prefs: dict, event: dict, session) -> list[dict]:
    """
    Returns list of delivery decisions for this user (may be empty if suppressed).
    Each decision dict has channel, delivery_type, severity, routing_log.
    """
    decisions = []
    user_id = str(user["id"])
    severity = event.get("severity", 0) or 0
    tier = severity_tier(severity)
    
    # ── Watchlist match
    wl = _match_watchlist(user_id, event, session)
    
    # ── Vacation mode (Rule 6)
    if prefs.get("vacation_mode"):
        # Only severity 90+ + watchlist match breaks through
        if not (severity >= 90 and wl["matched"]):
            return [{
                "channel": "suppressed",
                "delivery_type": "suppressed",
                "severity": severity,
                "status": "suppressed",
                "routing_log": {
                    "reason": "vacation_mode_active",
                    "severity_tier": tier,
                    "watchlist_match": wl["matched"]
                }
            }]
    
    # ── Severity threshold gate
    threshold = prefs.get("severity_threshold", 50) or 50
    # Watchlist match lowers effective threshold by 10
    effective_threshold = threshold - 10 if wl["matched"] else threshold
    
    if severity < effective_threshold:
        return [{
            "channel": "suppressed",
            "delivery_type": "below_threshold",
            "severity": severity,
            "status": "suppressed",
            "routing_log": {
                "reason": "below_severity_threshold",
                "user_threshold": threshold,
                "effective_threshold": effective_threshold,
                "event_severity": severity,
                "watchlist_match": wl["matched"]
            }
        }]
    
    # ── Quiet hours check
    in_quiet = _is_quiet_hours(prefs, user.get("timezone"))
    quiet_breaks_through = severity >= QUIET_HOURS_BREAK_THRESHOLD and wl["matched"]
    
    # ── Channel preferences
    channels_enabled = []
    if prefs.get("channel_email"): channels_enabled.append("email")
    if prefs.get("channel_push"):  channels_enabled.append("push")
    if prefs.get("channel_sms"):   channels_enabled.append("sms")
    if prefs.get("channel_slack"): channels_enabled.append("slack")
    if prefs.get("channel_teams"): channels_enabled.append("teams")
    
    if not channels_enabled:
        return [{
            "channel": "suppressed",
            "delivery_type": "no_channels_enabled",
            "severity": severity,
            "status": "suppressed",
            "routing_log": {"reason": "user_has_no_active_channels"}
        }]
    
    # ── Severity decay (Rule 1) — check against existing event_id
    event_id = event.get("id")
    decay = {"blocked": False, "reason": "no_event_id"}
    if event_id:
        decay = _check_severity_decay(user_id, event_id, severity, session)
    
    if decay["blocked"]:
        return [{
            "channel": "suppressed",
            "delivery_type": "fatigue_decay",
            "severity": severity,
            "status": "suppressed",
            "routing_log": {
                "reason": decay["reason"],
                "rule": "severity_decay_rule_1"
            }
        }]
    
    # ── Evaluate each enabled channel through the cube
    for channel in channels_enabled:
        cube_decision = ROUTING_CUBE[channel][tier]
        
        if cube_decision == "off":
            continue
        
        # ── Rule 2: Push needs watchlist match OR severity >= 80
        if channel == "push":
            if not wl["matched"] and severity < PUSH_WATCHLIST_OR_CRITICAL:
                continue  # skip push, doesn't qualify
        
        # ── Rule 3: Quiet hours throttling (push/sms only)
        if in_quiet and channel in ("push", "sms"):
            if not quiet_breaks_through:
                # Demote to digest instead of suppressing entirely
                cube_decision = "digest"
        
        # Determine delivery_type for the obs_deliveries row
        # immediate → 'alert' / bundled → 'morning_digest' / digest → 'morning_digest'
        delivery_type_map = {
            "immediate": "alert",
            "bundled":   "morning_digest",
            "digest":    "morning_digest",
        }
        
        decisions.append({
            "channel": channel,
            "delivery_type": delivery_type_map[cube_decision],
            "severity": severity,
            "status": "queued",
            "routing_log": {
                "severity_tier": tier,
                "cube_decision": cube_decision,
                "watchlist_match": wl["matched"],
                "watchlist_priority": wl["max_priority"],
                "watchlist_entries": [m["name"] for m in wl["matched_entries"]],
                "effective_threshold": effective_threshold,
                "in_quiet_hours": in_quiet,
                "quiet_hours_breakthrough": quiet_breaks_through,
                "decay_status": decay["reason"]
            }
        })
    
    if not decisions:
        return [{
            "channel": "suppressed",
            "delivery_type": "all_channels_filtered",
            "severity": severity,
            "status": "suppressed",
            "routing_log": {
                "reason": "channels_enabled_but_none_qualified",
                "channels_checked": channels_enabled
            }
        }]
    
    return decisions


# ──────────────────────────────────────────────────────────
# PUBLIC API: route_event
# ──────────────────────────────────────────────────────────

def route_event(event_id: str, dry_run: bool = False) -> dict:
    """
    Main entry point. Given an event ID, evaluate all active users
    and write delivery decisions to obs_deliveries.
    
    Args:
        event_id: UUID of event in obs_events
        dry_run: If True, returns decisions without writing to DB
    
    Returns:
        {
          "event_id": str,
          "event_headline": str,
          "users_evaluated": int,
          "deliveries_queued": int,
          "suppressions": int,
          "decisions": [...]  # per-user breakdown
        }
    """
    with get_session() as s:
        # Fetch event
        ev_row = s.execute(text("""
            SELECT id, headline, summary, event_type, severity, confidence,
                   geographic_scope, entities, industries
            FROM obs_events WHERE id = :eid
        """), {"eid": event_id}).fetchone()
        
        if not ev_row:
            return {"error": "event_not_found", "event_id": event_id}
        
        event = dict(ev_row._mapping)
        event["id"] = str(event["id"])
        # Coerce JSONB fields
        for fld in ("entities", "industries"):
            if isinstance(event.get(fld), str):
                try:
                    event[fld] = json.loads(event[fld])
                except Exception:
                    event[fld] = []
            if event.get(fld) is None:
                event[fld] = []
        
        # Fetch all active users + their preferences
        users = s.execute(text("""
            SELECT u.id, u.email, u.name, u.role, u.timezone,
                   p.channel_email, p.channel_push, p.channel_sms,
                   p.channel_slack, p.channel_teams,
                   p.severity_threshold, p.quiet_hours_start, p.quiet_hours_end,
                   p.vacation_mode
            FROM obs_users u
            LEFT JOIN obs_user_preferences p ON p.user_id = u.id
            WHERE u.is_active = TRUE
        """)).fetchall()
        
        all_decisions = []
        queued = 0
        suppressed = 0
        
        for u in users:
            udict = {
                "id": u.id, "email": u.email, "name": u.name,
                "role": u.role, "timezone": u.timezone
            }
            pdict = {
                "channel_email": u.channel_email,
                "channel_push": u.channel_push,
                "channel_sms": u.channel_sms,
                "channel_slack": u.channel_slack,
                "channel_teams": u.channel_teams,
                "severity_threshold": u.severity_threshold,
                "quiet_hours_start": u.quiet_hours_start,
                "quiet_hours_end": u.quiet_hours_end,
                "vacation_mode": u.vacation_mode,
            }
            
            decisions = _evaluate_user(udict, pdict, event, s)
            
            for d in decisions:
                d["user_id"] = str(u.id)
                d["user_email"] = u.email
                d["user_role"] = u.role
                all_decisions.append(d)
                
                if d["status"] == "queued":
                    queued += 1
                    if not dry_run:
                        s.execute(text("""
                            INSERT INTO obs_deliveries
                            (user_id, event_id, channel, delivery_type,
                             severity, status, routing_log, routed_at, queued_at)
                            VALUES
                            (:uid, :eid, :channel, :dtype,
                             :sev, 'queued', :rlog, NOW(), NOW())
                        """), {
                            "uid": u.id, "eid": event_id,
                            "channel": d["channel"], "dtype": d["delivery_type"],
                            "sev": d["severity"],
                            "rlog": json.dumps(d["routing_log"])
                        })
                else:
                    suppressed += 1
                    if not dry_run:
                        # Log suppression for audit
                        s.execute(text("""
                            INSERT INTO obs_deliveries
                            (user_id, event_id, channel, delivery_type,
                             severity, status, routing_log, routed_at, queued_at)
                            VALUES
                            (:uid, :eid, :channel, :dtype,
                             :sev, 'suppressed', :rlog, NOW(), NOW())
                        """), {
                            "uid": u.id, "eid": event_id,
                            "channel": d["channel"][:50],
                            "dtype": d["delivery_type"][:50],
                            "sev": d["severity"],
                            "rlog": json.dumps(d["routing_log"])
                        })
                        # CAP 12 — Log predictions silently (fail-soft, never blocks routing)
        try:
            pred_result = log_predictions_for_event(event_id)
            log.info(f"cap12_predictions | event={event_id} | logged={pred_result.get('logged')}")
        except Exception as pe:
            log.warning(f"cap12_prediction_skip | event={event_id} | {pe}")
        
        return {
            "event_id": event_id,
            "event_headline": event.get("headline"),
            "event_severity": event.get("severity"),
            "users_evaluated": len(users),
            "deliveries_queued": queued,
            "suppressions": suppressed,
            "decisions": all_decisions,
            "dry_run": dry_run
        }