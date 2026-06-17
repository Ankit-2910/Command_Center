"""
OBSIDIAN — Slack Sender (Stage 5A)

Sends intelligence alerts to Slack channels via incoming webhooks.
Uses Block Kit for rich, scannable formatting matching OBSIDIAN's aesthetic.

Setup for users:
  1. Go to https://api.slack.com/apps → Create App → Incoming Webhooks
  2. Enable webhooks, add to channel
  3. Copy webhook URL → paste into /settings under Slack webhook URL
  4. Toggle Slack channel ON in /settings
"""
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

log = logging.getLogger("obsidian.slack")

# Severity → color sidebars in Slack attachments
SEVERITY_COLOR = {
    "critical": "#ff3838",
    "high":     "#ff8c00",
    "elevated": "#ffd166",
    "low":      "#888888",
}

def _severity_tier(sev: int) -> str:
    if sev >= 85: return "critical"
    if sev >= 70: return "high"
    if sev >= 50: return "elevated"
    return "low"

def _severity_emoji(sev: int) -> str:
    if sev >= 85: return "🔴"
    if sev >= 70: return "🟠"
    if sev >= 50: return "🟡"
    return "⚪"


def build_slack_payload(
    *,
    event: dict,
    user_name: str,
    user_role: str,
    watchlist_entries: list,
    app_base_url: str,
) -> dict:
    """
    Build a Slack Block Kit message for an OBSIDIAN intelligence event.
    Returns a dict ready to POST to a Slack webhook URL.
    """
    sev = int(event.get("severity") or 0)
    tier = _severity_tier(sev)
    emoji = _severity_emoji(sev)
    color = SEVERITY_COLOR[tier]
    headline = event.get("headline") or "Intelligence update"
    summary = (event.get("summary") or "")[:300]
    scope = event.get("geographic_scope") or "Global"
    event_id = str(event.get("id") or "")

    # Watchlist match line
    wl_text = ""
    if watchlist_entries:
        wl_text = f"*◎ Matched watchlist:* {', '.join(watchlist_entries[:4])}\n"

    # Role framing for the footer
    role_labels = {
        "ceo": "CEO STRATEGIC VIEW",
        "coo": "COO OPERATIONS VIEW",
        "analyst": "ANALYST VIEW",
        "procurement": "PROCUREMENT VIEW",
        "logistics": "LOGISTICS VIEW",
        "risk": "RISK ANALYST VIEW",
    }
    role_label = role_labels.get(user_role.lower(), "INTELLIGENCE VIEW")

    brief_url = f"{app_base_url}/?event={event_id}" if event_id else app_base_url

    payload = {
        "text": f"{emoji} *OBSIDIAN ALERT* — {headline}",
        "attachments": [
            {
                "color": color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"OBSIDIAN // INTELLIGENCE ALERT",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Severity*\n{emoji} `{sev}` · {tier.upper()}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Scope*\n{scope}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Delivered to*\n{user_name} · {role_label}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Time*\n{datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y · %H:%M IST')}"
                            }
                        ]
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{headline}*\n{summary}"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": wl_text if wl_text else "_No watchlist match — routed by severity threshold._"
                        }
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "▶ Open Brief",
                                    "emoji": True
                                },
                                "url": brief_url,
                                "style": "primary"
                            },
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "◎ Command Center",
                                    "emoji": True
                                },
                                "url": app_base_url
                            }
                        ]
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"OBSIDIAN Intelligence · Shivanchal Consultants · <{app_base_url}/settings|Manage preferences>"
                            }
                        ]
                    }
                ]
            }
        ]
    }
    return payload


def send_slack_message(webhook_url: str, payload: dict) -> dict:
    """
    POST the Block Kit payload to a Slack webhook URL.
    Returns {"ok": bool, "error": str | None}
    """
    if not webhook_url or not webhook_url.startswith("https://hooks.slack.com/"):
        return {"ok": False, "error": "invalid_webhook_url"}

    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            response_text = resp.read().decode("utf-8")
            if response_text.strip() == "ok":
                log.info(f"slack_send_ok | webhook=...{webhook_url[-20:]}")
                return {"ok": True, "error": None}
            else:
                return {"ok": False, "error": f"unexpected_response: {response_text[:100]}"}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8")[:200]
        log.error(f"slack_http_error | {e.code} | {err}")
        return {"ok": False, "error": f"http_{e.code}: {err}"}
    except Exception as e:
        log.error(f"slack_send_failed | {e}")
        return {"ok": False, "error": str(e)[:200]}