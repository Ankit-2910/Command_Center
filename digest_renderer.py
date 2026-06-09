"""
OBSIDIAN — Digest Renderer (Stage 3)

Builds role-based HTML and plaintext email bodies for queued deliveries.
The morning brief is the soul of CAP 11 — this is what closes prospects.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import text
from db import get_session

APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://command-center-jst4.onrender.com")

# ──────────────────────────────────────────────────────────
# ROLE-BASED FRAMING
# ──────────────────────────────────────────────────────────

ROLE_FRAMING = {
    "ceo": {
        "greeting_label": "STRATEGIC INTELLIGENCE",
        "tagline": "Top-level signals, financial exposure, board-ready decisions.",
        "decision_prompt_label": "DECISIONS THIS WEEK",
        "view_label": "CEO"
    },
    "coo": {
        "greeting_label": "OPERATIONS INTELLIGENCE",
        "tagline": "What's breaking, what needs action, what to brief tomorrow.",
        "decision_prompt_label": "OPERATIONAL ACTIONS",
        "view_label": "COO"
    },
    "cfo": {
        "greeting_label": "FINANCIAL EXPOSURE BRIEF",
        "tagline": "Revenue at risk, freight cost shifts, working capital impact.",
        "decision_prompt_label": "FINANCIAL DECISIONS",
        "view_label": "CFO"
    },
    "procurement": {
        "greeting_label": "PROCUREMENT INTELLIGENCE",
        "tagline": "Supplier risk, sourcing alternatives, contract exposure.",
        "decision_prompt_label": "SOURCING ACTIONS",
        "view_label": "PROCUREMENT"
    },
    "logistics": {
        "greeting_label": "LOGISTICS INTELLIGENCE",
        "tagline": "Route disruptions, freight rates, transit time changes.",
        "decision_prompt_label": "ROUTE DECISIONS",
        "view_label": "LOGISTICS"
    },
    "risk": {
        "greeting_label": "RISK INTELLIGENCE",
        "tagline": "Scenario probabilities, escalation signals, calibration data.",
        "decision_prompt_label": "RISK SCENARIOS",
        "view_label": "RISK ANALYST"
    },
    "analyst": {
        "greeting_label": "ANALYST DAILY BRIEF",
        "tagline": "Multi-domain coverage. Scenarios. Source breakdown.",
        "decision_prompt_label": "ANALYSIS PROMPTS",
        "view_label": "ANALYST"
    }
}

DEFAULT_FRAMING = ROLE_FRAMING["analyst"]


# ──────────────────────────────────────────────────────────
# SEVERITY HELPERS
# ──────────────────────────────────────────────────────────

def severity_badge_color(sev: int) -> str:
    if sev >= 85: return "#ff3838"  # red
    if sev >= 70: return "#ff8c00"  # orange
    if sev >= 50: return "#ffd166"  # yellow
    return "#888"                    # gray

def severity_label(sev: int) -> str:
    if sev >= 85: return "CRITICAL"
    if sev >= 70: return "HIGH"
    if sev >= 50: return "ELEVATED"
    return "LOW"


# ──────────────────────────────────────────────────────────
# EVENT FETCHER FOR A USER'S DIGEST
# ──────────────────────────────────────────────────────────

def fetch_pending_events_for_user(user_id: str) -> list[dict]:
    """
    Pulls all queued email deliveries for this user.
    Returns list of event dicts joined with their delivery routing log.
    """
    with get_session() as s:
        rows = s.execute(text("""
            SELECT 
                d.id AS delivery_id,
                d.severity AS routed_severity,
                d.routing_log,
                e.id AS event_id,
                e.headline, e.summary, e.event_type,
                e.severity, e.geographic_scope, e.entities, e.industries,
                e.detected_at
            FROM obs_deliveries d
            JOIN obs_events e ON e.id = d.event_id
            WHERE d.user_id = :uid
              AND d.status = 'queued'
              AND d.channel = 'email'
            ORDER BY e.severity DESC, e.detected_at DESC
            LIMIT 10
        """), {"uid": user_id}).fetchall()
        
        return [dict(r._mapping) for r in rows]


# ──────────────────────────────────────────────────────────
# SUBJECT LINE BUILDER
# ──────────────────────────────────────────────────────────

def build_subject(events: list[dict], role: str, digest_type: str) -> str:
    if not events:
        return f"OBSIDIAN // Morning Brief — quiet overnight"
    
    top = events[0]
    sev = top.get("severity", 0)
    sev_label = severity_label(sev)
    
    if len(events) == 1:
        if digest_type == "alert":
            return f"🔴 {sev_label} — {top['headline'][:80]}"
        return f"OBSIDIAN // {top['headline'][:80]}"
    
    return f"OBSIDIAN // {len(events)} signals — top: {sev_label} {top['headline'][:60]}"


# ──────────────────────────────────────────────────────────
# WATCHLIST MATCHES (which entries matched this event)
# ──────────────────────────────────────────────────────────

def matched_watchlist_names(routing_log) -> list[str]:
    """Extract human-readable watchlist match names from routing_log JSONB."""
    if not routing_log:
        return []
    if isinstance(routing_log, str):
        import json
        try:
            routing_log = json.loads(routing_log)
        except Exception:
            return []
    return routing_log.get("watchlist_entries", []) or []


# ──────────────────────────────────────────────────────────
# HTML EMAIL RENDERER
# ──────────────────────────────────────────────────────────

def render_html_digest(
    *,
    user_name: str,
    user_role: str,
    user_timezone: str,
    events: list[dict],
    digest_type: str,
    batch_id: str
) -> str:
    framing = ROLE_FRAMING.get(user_role, DEFAULT_FRAMING)
    
    try:
        tz = ZoneInfo(user_timezone or "Asia/Kolkata")
    except Exception:
        tz = ZoneInfo("Asia/Kolkata")
    now_local = datetime.now(tz).strftime("%a, %b %d · %H:%M %Z")
    
    # Tracking pixel for open detection
    tracking_pixel = (
        f'<img src="{APP_BASE_URL}/api/email/track-open/{batch_id}.png" '
        f'width="1" height="1" alt="" style="display:block;border:0;" />'
    )
    
    # Build event blocks
    event_blocks_html = ""
    if not events:
        event_blocks_html = """
        <tr><td style="padding:30px 20px;text-align:center;color:#8a8a8a;
            font-size:13px;font-style:italic;">
            No signals matched your watchlist overnight. System monitoring 247 hotspots.
        </td></tr>
        """
    else:
        for i, ev in enumerate(events, 1):
            sev = int(ev.get("severity") or 0)
            color = severity_badge_color(sev)
            label = severity_label(sev)
            headline = (ev.get("headline") or "—")[:200]
            summary = (ev.get("summary") or "")[:400]
            scope = ev.get("geographic_scope") or ""
            wl_matches = matched_watchlist_names(ev.get("routing_log"))
            
            wl_html = ""
            if wl_matches:
                wl_html = (
                    f'<div style="margin-top:8px;font-size:11px;color:#FFA500;'
                    f'letter-spacing:1px;">'
                    f'◎ MATCHED WATCHLIST: {", ".join(wl_matches[:4])}'
                    f'</div>'
                )
            
            event_blocks_html += f"""
            <tr><td style="padding:18px 22px;border-bottom:1px solid #1a1a1a;">
                <div style="margin-bottom:8px;">
                    <span style="display:inline-block;background:{color};
                        color:#000;padding:2px 9px;font-size:10px;font-weight:700;
                        letter-spacing:1px;border-radius:2px;font-family:monospace;">
                        {sev} · {label}
                    </span>
                    <span style="color:#8a8a8a;font-size:11px;margin-left:10px;
                        font-family:monospace;letter-spacing:1px;">
                        #{i:02d} · {scope}
                    </span>
                </div>
                <div style="font-size:15px;color:#e8e8e8;font-weight:600;
                    margin-bottom:6px;line-height:1.35;">
                    {headline}
                </div>
                <div style="font-size:13px;color:#bababa;line-height:1.5;">
                    {summary}
                </div>
                {wl_html}
                <div style="margin-top:12px;">
                    <a href="{APP_BASE_URL}/?event={ev.get('event_id')}"
                       style="color:#FFA500;text-decoration:none;font-size:11px;
                              letter-spacing:1px;font-family:monospace;
                              border:1px solid #FFA500;padding:4px 10px;
                              border-radius:2px;">
                      ▶ OPEN BRIEF
                    </a>
                </div>
            </td></tr>
            """
    
    # Top severity stat
    top_sev = max((e.get("severity") or 0) for e in events) if events else 0
    top_label = severity_label(top_sev) if events else "—"
    top_color = severity_badge_color(top_sev) if events else "#444"
    
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OBSIDIAN Intelligence</title>
</head>
<body style="margin:0;padding:0;background:#0a0a0a;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
    'JetBrains Mono','Consolas',monospace;color:#e8e8e8;">

<table width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:#0a0a0a;padding:30px 0;">
  <tr><td align="center">
    <table width="640" cellpadding="0" cellspacing="0" border="0"
           style="max-width:640px;background:#141414;
                  border:1px solid #2a2a2a;border-radius:4px;">

      <!-- HEADER -->
      <tr><td style="padding:24px;border-bottom:1px solid #2a2a2a;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="font-family:monospace;font-size:13px;
                       letter-spacing:3px;color:#FFA500;font-weight:600;">
              OBSIDIAN
            </td>
            <td style="text-align:right;font-family:monospace;font-size:10px;
                       letter-spacing:1px;color:#8a8a8a;">
              {now_local}
            </td>
          </tr>
        </table>
        <div style="margin-top:14px;font-size:11px;color:#8a8a8a;
                    letter-spacing:2px;text-transform:uppercase;font-family:monospace;">
          {framing['greeting_label']} · {framing['view_label']} VIEW
        </div>
        <div style="margin-top:6px;font-size:13px;color:#bababa;">
          For {user_name}
        </div>
        <div style="margin-top:4px;font-size:11px;color:#666;font-style:italic;">
          {framing['tagline']}
        </div>
      </td></tr>

      <!-- TOP STAT BAR -->
      <tr><td style="padding:16px 24px;background:#0a0a0a;border-bottom:1px solid #2a2a2a;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="font-family:monospace;font-size:11px;color:#8a8a8a;letter-spacing:1px;">
              SIGNALS DETECTED
            </td>
            <td style="text-align:right;">
              <span style="font-family:monospace;font-size:18px;color:#FFA500;
                font-weight:700;">{len(events)}</span>
              <span style="font-family:monospace;font-size:10px;color:#666;
                margin-left:8px;letter-spacing:1px;">EVENTS</span>
              <span style="display:inline-block;margin-left:14px;background:{top_color};
                color:#000;padding:2px 9px;font-size:10px;font-weight:700;
                letter-spacing:1px;border-radius:2px;font-family:monospace;">
                TOP: {top_label}
              </span>
            </td>
          </tr>
        </table>
      </td></tr>

      <!-- EVENT BLOCKS -->
      <tr><td>
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          {event_blocks_html}
        </table>
      </td></tr>

      <!-- CTA FOOTER -->
      <tr><td style="padding:24px;text-align:center;background:#0a0a0a;
                     border-top:1px solid #2a2a2a;">
        <a href="{APP_BASE_URL}/"
           style="display:inline-block;background:#FFA500;color:#000;
                  padding:12px 28px;text-decoration:none;font-weight:600;
                  letter-spacing:2px;font-size:11px;border-radius:3px;
                  font-family:monospace;">
          ▶ OPEN COMMAND CENTER
        </a>
        <div style="margin-top:14px;font-family:monospace;font-size:10px;
                    color:#666;letter-spacing:1px;">
          <a href="{APP_BASE_URL}/settings" style="color:#666;text-decoration:none;">
            ◎ MANAGE PREFERENCES
          </a>
        </div>
      </td></tr>

      <!-- FOOTER FINE PRINT -->
      <tr><td style="padding:16px 24px;border-top:1px solid #1a1a1a;
                     font-family:monospace;font-size:9px;color:#444;
                     letter-spacing:1px;line-height:1.6;text-align:center;">
        OBSIDIAN INTELLIGENCE COMMAND CENTER<br>
        SHIVANCHAL CONSULTANTS · CO-FOUNDED BY ADI & ANKIT DUBEY<br>
        DELIVERED VIA SECURE UPLINK · {now_local}
      </td></tr>

    </table>
  </td></tr>
</table>

{tracking_pixel}
</body></html>"""


# ──────────────────────────────────────────────────────────
# PLAINTEXT FALLBACK
# ──────────────────────────────────────────────────────────

def render_text_digest(
    *,
    user_name: str,
    user_role: str,
    events: list[dict],
    digest_type: str
) -> str:
    framing = ROLE_FRAMING.get(user_role, DEFAULT_FRAMING)
    
    lines = [
        "════════════════════════════════════════════",
        f"OBSIDIAN // {framing['greeting_label']}",
        f"For: {user_name} ({framing['view_label']} view)",
        "════════════════════════════════════════════",
        "",
        f"Signals detected: {len(events)}",
        ""
    ]
    
    if not events:
        lines.append("No signals matched your watchlist. System monitoring globally.")
    else:
        for i, ev in enumerate(events, 1):
            sev = int(ev.get("severity") or 0)
            label = severity_label(sev)
            lines.append(f"#{i:02d}  [{sev} · {label}]  {ev.get('headline','—')}")
            lines.append(f"      Scope: {ev.get('geographic_scope','—')}")
            
            wl = matched_watchlist_names(ev.get("routing_log"))
            if wl:
                lines.append(f"      Matched watchlist: {', '.join(wl[:3])}")
            
            summary = (ev.get("summary") or "")[:200]
            if summary:
                lines.append(f"      {summary}")
            lines.append(f"      → {APP_BASE_URL}/?event={ev.get('event_id')}")
            lines.append("")
    
    lines.extend([
        "──────────────────────────────────────────────",
        f"Open Command Center: {APP_BASE_URL}/",
        f"Manage preferences:  {APP_BASE_URL}/settings",
        "──────────────────────────────────────────────",
        "OBSIDIAN Intelligence · SHIVANCHAL CONSULTANTS",
    ])
    
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────
# CONVENIENCE: render a complete digest for one user
# ──────────────────────────────────────────────────────────

def build_digest_for_user(user_id: str, digest_type: str = "morning_digest") -> dict | None:
    """
    Returns dict ready to pass to send_batch(), or None if no pending events.
    
    {
      "user_email": str,
      "subject": str,
      "html": str,
      "text": str,
      "delivery_ids": [uuid],
      "severity_max": int,
      "event_count": int
    }
    """
    with get_session() as s:
        urow = s.execute(text("""
            SELECT id, email, name, role, timezone
            FROM obs_users WHERE id = :uid AND is_active = TRUE
        """), {"uid": user_id}).fetchone()
        if not urow:
            return None
        
        user = dict(urow._mapping)
    
    events = fetch_pending_events_for_user(user_id)
    if not events and digest_type != "manual_test":
        return None
    
    role = (user.get("role") or "analyst").lower()
    subject = build_subject(events, role, digest_type)
    
    # We'll need the batch_id BEFORE rendering (for tracking pixel)
    # Caller will pass batch_id back in. For now, placeholder.
    return {
        "user_id": str(user["id"]),
        "user_email": user["email"],
        "user_name": user["name"],
        "user_role": role,
        "user_timezone": user.get("timezone") or "Asia/Kolkata",
        "subject": subject,
        "events": events,
        "delivery_ids": [str(e["delivery_id"]) for e in events],
        "severity_max": max((int(e.get("severity") or 0) for e in events), default=0),
        "event_count": len(events),
        "digest_type": digest_type
    }