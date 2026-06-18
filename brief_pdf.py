"""
OBSIDIAN — Brief PDF Generator (Stage 6A)

Renders an intelligence brief to a branded PDF using ReportLab.
Pure-Python, no system dependencies (no cairo/pango) — deploys clean on Render.

Source priority:
  1. If a brief row exists (obs_briefs.content_md) → render the role-specific brief.
  2. Else fall back to the raw event (obs_events) → headline/summary/severity/scope.

Public API:
  generate_brief_pdf(brief_id=..., event_id=...) -> bytes
  Returns the PDF as raw bytes, ready to stream from a Flask route.
"""
import io
import re
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Flowable, HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from sqlalchemy import text as _sql_text
from db import get_session

log = logging.getLogger("obsidian.pdf")

# ── OBSIDIAN palette (matches Slack/email aesthetic) ────────────────────────
INK        = HexColor("#0d1117")   # near-black header
PANEL      = HexColor("#161b22")
ACCENT     = HexColor("#f5a623")   # OBSIDIAN amber
TEXT_DARK  = HexColor("#1a1a1a")
TEXT_MUTE  = HexColor("#6b7280")
RULE       = HexColor("#e5e7eb")

SEVERITY_COLOR = {
    "critical": HexColor("#ff3838"),
    "high":     HexColor("#ff8c00"),
    "elevated": HexColor("#e0a800"),
    "low":      HexColor("#888888"),
}

def _severity_tier(sev: int) -> str:
    if sev >= 85: return "critical"
    if sev >= 70: return "high"
    if sev >= 50: return "elevated"
    return "low"

ROLE_LABELS = {
    "ceo": "CEO STRATEGIC VIEW",
    "coo": "COO OPERATIONS VIEW",
    "analyst": "ANALYST VIEW",
    "procurement": "PROCUREMENT VIEW",
    "logistics": "LOGISTICS VIEW",
    "risk": "RISK ANALYST VIEW",
}


# ── A colored severity bar flowable ─────────────────────────────────────────
class SeverityBar(Flowable):
    def __init__(self, width, tier, sev):
        super().__init__()
        self.width = width
        self.height = 22
        self.tier = tier
        self.sev = sev

    def draw(self):
        c = self.canv
        color = SEVERITY_COLOR[self.tier]
        c.setFillColor(color)
        c.roundRect(0, 0, self.width, self.height, 3, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(8, 6, f"SEVERITY {self.sev}  ·  {self.tier.upper()}")


def _md_to_paragraphs(md_text: str, body_style, h_style):
    """
    Minimal, safe markdown → ReportLab flowables.
    Handles: # / ## headings, - bullets, **bold**, paragraphs.
    Not a full markdown engine — intentionally small and predictable.
    """
    flows = []
    if not md_text:
        return flows
    lines = md_text.split("\n")
    buf = []

    def flush_buf():
        if buf:
            txt = " ".join(buf).strip()
            if txt:
                flows.append(Paragraph(_inline(txt), body_style))
            buf.clear()

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush_buf()
            flows.append(Spacer(1, 4))
        elif line.startswith("## "):
            flush_buf()
            flows.append(Spacer(1, 6))
            flows.append(Paragraph(_inline(line[3:].strip()), h_style))
        elif line.startswith("# "):
            flush_buf()
            flows.append(Spacer(1, 6))
            flows.append(Paragraph(_inline(line[2:].strip()), h_style))
        elif line.lstrip().startswith(("- ", "* ")):
            flush_buf()
            item = line.lstrip()[2:].strip()
            flows.append(Paragraph(f"•&nbsp;&nbsp;{_inline(item)}", body_style))
        else:
            buf.append(line.strip())
    flush_buf()
    return flows


def _inline(text: str) -> str:
    """Convert **bold** and *italic*, escape stray XML chars for ReportLab."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    return text


def _header_footer(canvas, doc, headline, role_label):
    canvas.saveState()
    w, h = A4
    # Top ink band
    canvas.setFillColor(INK)
    canvas.rect(0, h - 28*mm, w, 28*mm, fill=1, stroke=0)
    canvas.setFillColor(ACCENT)
    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawString(18*mm, h - 15*mm, "OBSIDIAN")
    canvas.setFillColor(white)
    canvas.setFont("Helvetica", 8.5)
    canvas.drawString(18*mm, h - 20*mm, "INTELLIGENCE BRIEF")
    canvas.setFillColor(HexColor("#9ca3af"))
    canvas.drawRightString(w - 18*mm, h - 15*mm, role_label)
    canvas.drawRightString(
        w - 18*mm, h - 20*mm,
        datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y · %H:%M IST")
    )
    # Footer
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(18*mm, 14*mm, w - 18*mm, 14*mm)
    canvas.setFillColor(TEXT_MUTE)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(18*mm, 9*mm, "OBSIDIAN Intelligence · Shivanchal Consultants · Confidential")
    canvas.drawRightString(w - 18*mm, 9*mm, f"Page {doc.page}")
    canvas.restoreState()


def _build_pdf(*, headline, summary_md, severity, scope, role_view,
               confidence, event_type, generated_at) -> bytes:
    buf = io.BytesIO()
    sev = int(severity or 0)
    tier = _severity_tier(sev)
    role_label = ROLE_LABELS.get((role_view or "").lower(), "INTELLIGENCE VIEW")

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=34*mm, bottomMargin=20*mm,
        title=f"OBSIDIAN Brief — {headline[:60]}",
        author="OBSIDIAN Intelligence",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("OBSH1", parent=styles["Heading1"],
                        fontName="Helvetica-Bold", fontSize=17, leading=21,
                        textColor=TEXT_DARK, spaceAfter=2)
    h2 = ParagraphStyle("OBSH2", parent=styles["Heading2"],
                        fontName="Helvetica-Bold", fontSize=12, leading=15,
                        textColor=INK, spaceBefore=8, spaceAfter=3)
    body = ParagraphStyle("OBSBody", parent=styles["BodyText"],
                          fontName="Helvetica", fontSize=10, leading=15,
                          textColor=TEXT_DARK, alignment=TA_LEFT, spaceAfter=2)
    meta = ParagraphStyle("OBSMeta", parent=styles["BodyText"],
                          fontName="Helvetica", fontSize=8.5, leading=12,
                          textColor=TEXT_MUTE)

    story = []
    story.append(Paragraph(_inline(headline or "Intelligence Update"), h1))
    story.append(Spacer(1, 4))

    # Meta row: scope / type / confidence
    meta_data = [[
        Paragraph(f"<b>Scope</b><br/>{scope or 'Global'}", meta),
        Paragraph(f"<b>Type</b><br/>{(event_type or 'general').replace('_',' ').title()}", meta),
        Paragraph(f"<b>Confidence</b><br/>{confidence if confidence is not None else '—'}%", meta),
    ]]
    mt = Table(meta_data, colWidths=[58*mm, 58*mm, 58*mm])
    mt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#f9fafb")),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(mt)
    story.append(Spacer(1, 8))
    story.append(SeverityBar(174*mm, tier, sev))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE))
    story.append(Spacer(1, 8))

    # Body — markdown content
    story.extend(_md_to_paragraphs(summary_md, body, h2))

    doc.build(
        story,
        onFirstPage=lambda c, d: _header_footer(c, d, headline, role_label),
        onLaterPages=lambda c, d: _header_footer(c, d, headline, role_label),
    )
    return buf.getvalue()


# ── PUBLIC API ──────────────────────────────────────────────────────────────

def generate_brief_pdf(brief_id: str = None, event_id: str = None) -> bytes:
    """
    Generate a branded PDF. Prefers a brief row; falls back to the raw event.
    Raises ValueError if neither brief_id nor event_id resolves to data.
    """
    with get_session() as s:
        # 1. Try brief first
        if brief_id:
            b = s.execute(_sql_text("""
                SELECT b.id, b.event_id, b.role_view, b.content_md,
                       b.confidence, b.generated_at,
                       e.headline, e.severity, e.geographic_scope, e.event_type
                FROM obs_briefs b
                LEFT JOIN obs_events e ON e.id = b.event_id
                WHERE b.id = :bid
            """), {"bid": brief_id}).fetchone()
            if b:
                return _build_pdf(
                    headline=b.headline or "Intelligence Brief",
                    summary_md=b.content_md or "",
                    severity=b.severity,
                    scope=b.geographic_scope,
                    role_view=b.role_view,
                    confidence=b.confidence,
                    event_type=b.event_type,
                    generated_at=b.generated_at,
                )

        # 2. Fall back to event
        if event_id:
            e = s.execute(_sql_text("""
                SELECT id, headline, summary, severity, confidence,
                       geographic_scope, event_type
                FROM obs_events WHERE id = :eid
            """), {"eid": event_id}).fetchone()
            if e:
                return _build_pdf(
                    headline=e.headline or "Intelligence Update",
                    summary_md=e.summary or "_No summary available._",
                    severity=e.severity,
                    scope=e.geographic_scope,
                    role_view=None,
                    confidence=e.confidence,
                    event_type=e.event_type,
                    generated_at=None,
                )

    raise ValueError("No brief or event found for the given id(s)")
