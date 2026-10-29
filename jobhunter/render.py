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

from .fileio import secure

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
            # Bullet glyph from Helvetica: ZapfDingbats bullets show as boxes in some viewers and
            # come out as junk characters when an applicant tracking system extracts the text.
            bullets = [ListItem(Paragraph(_p(b), s["bullet"]), leftIndent=10, bulletFontName=FONT)
                       for b in e.get("bullets", []) or []]
            if bullets:
                block.append(ListFlowable(bullets, bulletType="bullet", start="\u2022", leftIndent=10,
                                          bulletFontName=FONT, bulletFontSize=size - 1, bulletOffsetY=0))
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
    width = LETTER[0] - 2 * margin - 12  # the frame keeps 6pt of padding on each side
    doc.build(_story(data, size, width))
    return doc.page


# ----------------------------- machine-readability check ----------------------

def _squash(s):
    import re
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def _encodable(ch):
    try:
        ch.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def pdf_text(path):
    from pypdf import PdfReader
    return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)


def readability_issues(pdf_path, expected):
    """Read the PDF's text back the way an applicant tracking system would, and check every
    expected piece (name, titles, employers, dates, the start of each bullet) comes out, in order.
    `expected` is a list of strings in document order. Returns a list of problems (empty = fine)."""
    try:
        text = pdf_text(pdf_path)
    except Exception as e:
        return [f"couldn't read text back out of the PDF ({e})"]
    issues = []
    if len(text.strip()) < 50:
        return ["the PDF has almost no extractable text (an ATS would see a blank resume)"]
    # The built-in fonts only cover Western European characters; anything else prints as a box.
    unshowable = sorted({c for piece in expected for c in str(piece) if not _encodable(c)})
    if unshowable or "\u25a0" in text:
        shown = "".join(unshowable[:10]) or "\u25a0"
        issues.append(f"characters the PDF font can't show ({shown!r}) print as boxes; replace them with plain letters")
    for lig in ("\ufb01", "\ufb02", "\ufffd"):
        if lig in text:
            issues.append(f"text extracts with {repr(lig)} characters (ligatures or bad glyphs) that ATS parsers garble")
            break
    flat = _squash(text)
    pos = 0
    for piece in expected:
        key = _squash(" ".join(str(piece).split()[:6]))  # the first words: line wrapping can split the rest
        if len(key) < 4:
            continue
        i = flat.find(key, pos)
        if i == -1:
            where = flat.find(key)
            issues.append(f"'{str(piece)[:50]}' " + ("comes out of order" if where != -1 else "is missing from the extracted text"))
            continue
        pos = i + len(key)
    return issues


def resume_pieces(data):
    out = [data.get("name", "")]
    for e in data.get("experience", []) or []:
        out += [e.get("title", ""), e.get("company", "")] + [str(b) for b in e.get("bullets", []) or []]
    for e in data.get("education", []) or []:
        out += [e.get("degree", ""), e.get("school", "")]
    return [x for x in out if x]


def letter_pieces(data):
    return [x for x in [data.get("name", "")] + [str(p) for p in data.get("paragraphs", []) or []] if x]


def render(resume_yaml, out_pdf, target_pages=None, sizes=(10.0, 9.5, 9.0, 8.75)):
    """Write the PDF. Shrinks the font a little (never below 8.75pt) to hit target_pages.
    Returns dict(pages, font_size, fits, readability_issues)."""
    data = load_resume(resume_yaml) if not isinstance(resume_yaml, dict) else resume_yaml
    chosen, pages = sizes[0], None
    for size in sizes:
        pages = _build(data, size, io.BytesIO())
        chosen = size
        if not target_pages or pages <= target_pages:
            break
    final_pages = _build(data, chosen, str(out_pdf))
    secure(Path(out_pdf))
    return {"pages": final_pages, "font_size": chosen, "fits": (not target_pages) or final_pages <= target_pages,
            "readability_issues": readability_issues(out_pdf, resume_pieces(data))}


# ----------------------------- cover letters ---------------------------------
# Cover letter YAML (see templates/cover_letter.example.yaml):
#   name, contact: [...], date, recipient: [lines], greeting, paragraphs: [...], closing, signature

def is_letter(data) -> bool:
    return isinstance(data, dict) and "paragraphs" in data and "experience" not in data


def letter_text(data):
    """All visible text of a cover letter, for linting and fact checks."""
    out = [data.get("name", ""), " | ".join(map(str, data.get("contact", []) or [])), str(data.get("date", ""))]
    out += [str(x) for x in data.get("recipient", []) or []]
    out += [data.get("greeting", "")] + [str(p) for p in data.get("paragraphs", []) or []]
    out += [data.get("closing", ""), data.get("signature", "") or data.get("name", "")]
    return "\n".join(str(x) for x in out if x)


def _letter_story(data, size):
    s = _styles(size)
    body = ParagraphStyle("lbody", parent=s["body"], spaceAfter=size * 0.9)
    st = [Paragraph(_p(data.get("name")), s["name"])]
    if data.get("contact"):
        st.append(Paragraph("  |  ".join(_p(c) for c in data["contact"]), s["contact"]))
    st.append(Spacer(1, size * 2))
    if data.get("date"):
        st.append(Paragraph(_p(data["date"]), body))
    if data.get("recipient"):
        st.append(Paragraph("<br/>".join(_p(x) for x in data["recipient"]), body))
    if data.get("greeting"):
        st.append(Paragraph(_p(data["greeting"]), body))
    for para in data.get("paragraphs", []) or []:
        st.append(Paragraph(_p(para), body))
    st.append(Paragraph(_p(data.get("closing", "Sincerely,")), s["body"]))
    st.append(Spacer(1, size * 1.5))
    st.append(Paragraph(_p(data.get("signature") or data.get("name")), s["body"]))
    return st


def render_letter(data, out_pdf, sizes=(10.5, 10.0, 9.5)):
    """One-page cover letter PDF. Returns dict(pages, font_size, fits)."""
    margin = 0.9 * inch

    def build(size, out):
        doc = SimpleDocTemplate(out, pagesize=LETTER, leftMargin=margin, rightMargin=margin,
                                topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                                title=f"{data.get('name', '')} - Cover letter", author=data.get("name", ""))
        doc.build(_letter_story(data, size))
        return doc.page

    chosen = sizes[0]
    for size in sizes:
        chosen = size
        if build(size, io.BytesIO()) <= 1:
            break
    pages = build(chosen, str(out_pdf))
    secure(Path(out_pdf))
    return {"pages": pages, "font_size": chosen, "fits": pages <= 1,
            "readability_issues": readability_issues(out_pdf, letter_pieces(data))}
