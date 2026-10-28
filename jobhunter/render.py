"""Render a tailored resume (YAML) to a clean, ATS-readable PDF and check its page count.

Resume YAML (see templates/resume.example.yaml):
  name: Jane Doe
  contact: [Washington, DC, jane@example.com, (202) 555-0100, linkedin.com/in/janedoe]
  summary: 2-3 plain sentences
  experience:
    - company: Example Bank
      title: Vice President, Credit
      location: Washington, DC
      dates: 2019 - Present
      bullets: [...]
  education:
    - school: ...
      degree: ...
      dates: ...
  skills: {Credit: "DSCR sizing, ...", Tools: "Excel, Argus"}   # or a flat list
  extra_sections: [{heading: Certifications, items: [...]}]
"""
import io
from pathlib import Path
from xml.sax.saxutils import escape

import yaml
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

INK = HexColor("#1a1a1a")
MUTED = HexColor("#555555")
FONT, BOLD = "Helvetica", "Helvetica-Bold"


def _p(text):
    return escape(str(text or "")).replace("\n", "<br/>")


def load_resume(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def resume_text(data):
    """All visible text, for linting and fact checks."""
    out = [data.get("name", ""), " | ".join(map(str, data.get("contact", []) or [])), data.get("summary", "")]
    for e in data.get("experience", []) or []:
        out += [e.get("title", ""), e.get("company", ""), e.get("location", ""), str(e.get("dates", ""))]
        out += [str(b) for b in e.get("bullets", []) or []]
    for e in data.get("education", []) or []:
        out += [str(e.get(k, "")) for k in ("school", "degree", "dates", "details")]
    sk = data.get("skills") or {}
    out += [f"{k}: {v}" for k, v in sk.items()] if isinstance(sk, dict) else [", ".join(map(str, sk))]
    for s in data.get("extra_sections", []) or []:
        out += [s.get("heading", "")] + [str(i) for i in s.get("items", []) or []]
    return "\n".join(x for x in out if x)


def all_bullets(data):
    return [str(b) for e in data.get("experience", []) or [] for b in e.get("bullets", []) or []]


def _styles(size):
    lead = size * 1.25
    return {
        "name": ParagraphStyle("name", fontName=BOLD, fontSize=size + 7, leading=size + 10, alignment=TA_CENTER, textColor=INK),
        "contact": ParagraphStyle("contact", fontName=FONT, fontSize=size - 0.5, leading=lead, alignment=TA_CENTER, textColor=MUTED),
        "h": ParagraphStyle("h", fontName=BOLD, fontSize=size + 0.5, leading=lead, textColor=INK, spaceBefore=size * 0.8),
        "body": ParagraphStyle("body", fontName=FONT, fontSize=size, leading=lead, textColor=INK),
        "role": ParagraphStyle("role", fontName=BOLD, fontSize=size, leading=lead, textColor=INK),
        "right": ParagraphStyle("right", fontName=FONT, fontSize=size, leading=lead, textColor=MUTED, alignment=2),
        "bullet": ParagraphStyle("bullet", fontName=FONT, fontSize=size, leading=lead, textColor=INK),
    }


def _two_col(left, right, s, width):
    t = Table([[Paragraph(left, s["role"]), Paragraph(right, s["right"])]], colWidths=[width * 0.72, width * 0.28])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _story(data, size, width):
    s = _styles(size)
    st = [Paragraph(_p(data.get("name")), s["name"])]
    contact = data.get("contact") or []
    if contact:
        st.append(Paragraph("  |  ".join(_p(c) for c in contact), s["contact"]))

    def heading(text):
        st.append(Paragraph(_p(text).upper(), s["h"]))
        st.append(HRFlowable(width="100%", thickness=0.6, color=MUTED, spaceBefore=1, spaceAfter=3))

    if data.get("summary"):
        heading(data.get("summary_heading", "Summary"))
        st.append(Paragraph(_p(data["summary"]), s["body"]))
    if data.get("experience"):
        heading("Experience")
        for e in data["experience"]:
            block = [_two_col(f"{_p(e.get('title'))}, {_p(e.get('company'))}",
                              _p(e.get("dates")), s, width)]
            if e.get("location") or e.get("subtitle"):
                sub = " | ".join(_p(x) for x in [e.get("subtitle"), e.get("location")] if x)
                block.append(Paragraph(f"<i>{sub}</i>", s["body"]))
            bullets = [ListItem(Paragraph(_p(b), s["bullet"]), leftIndent=10, value="circle")
                       for b in e.get("bullets", []) or []]
            if bullets:
                block.append(ListFlowable(bullets, bulletType="bullet", start="•", leftIndent=10,
                                          bulletFontSize=size - 1, bulletOffsetY=0))
            block.append(Spacer(1, size * 0.35))
            st.append(KeepTogether(block[:3]))
            st.extend(block[3:])
    if data.get("education"):
        heading("Education")
        for e in data["education"]:
            st.append(_two_col(f"{_p(e.get('degree'))}, {_p(e.get('school'))}", _p(e.get("dates")), s, width))
            if e.get("details"):
                st.append(Paragraph(_p(e["details"]), s["body"]))
    sk = data.get("skills")
    if sk:
        heading(data.get("skills_heading", "Skills"))
        if isinstance(sk, dict):
            for k, v in sk.items():
                st.append(Paragraph(f"<b>{_p(k)}:</b> {_p(v)}", s["body"]))
        else:
            st.append(Paragraph(_p(", ".join(map(str, sk))), s["body"]))
    for sec in data.get("extra_sections", []) or []:
        heading(sec.get("heading", ""))
        for item in sec.get("items", []) or []:
            st.append(Paragraph(_p(item), s["body"]))
    return st


def _build(data, size, out):
    margin = 0.6 * inch
    doc = SimpleDocTemplate(out, pagesize=LETTER, leftMargin=margin, rightMargin=margin,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch,
                            title=f"{data.get('name', '')} - Resume", author=data.get("name", ""))
    width = LETTER[0] - 2 * margin
    doc.build(_story(data, size, width))
    return doc.page


def render(resume_yaml, out_pdf, target_pages=None, sizes=(10.0, 9.5, 9.0, 8.75)):
    """Write the PDF. Shrinks the font a little (never below 8.75pt) to hit target_pages.
    Returns dict(pages, font_size, fits)."""
    data = load_resume(resume_yaml) if not isinstance(resume_yaml, dict) else resume_yaml
    chosen, pages = sizes[0], None
    for size in sizes:
        pages = _build(data, size, io.BytesIO())
        chosen = size
        if not target_pages or pages <= target_pages:
            break
    final_pages = _build(data, chosen, str(out_pdf))
    return {"pages": final_pages, "font_size": chosen, "fits": (not target_pages) or final_pages <= target_pages}
