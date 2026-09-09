"""
novadomus_facility_sign.py  —  Novadomus Health Service, Phase 1 signage

Generates four facility sign variants, each in colour and line-art B&W, from one
palette-swapped layout (so the two versions never drift):

    board   300 x 200 mm  landscape wall board
    plaque  160 x 240 mm  portrait door plaque
    oval    280 x 190 mm  hanging oval
    fascia  700 x 150 mm  wide reception / lobby fascia

Depends on nova_health.py (emblem, palette, wrap) + reportlab.
Called by facility_registry.py, or run standalone for a demo sign.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nova_health as nh
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

VARIANTS = ("board", "plaque", "oval", "fascia")
SIZES = {"board": (300, 200), "plaque": (160, 240), "oval": (280, 190), "fascia": (700, 150)}


def _c(p, k):
    return nh.hex_to_color(p[k])


def _frame(c, W, H, p, inset=8):
    """Gold double frame; for the oval variant the caller skips this."""
    c.setStrokeColor(_c(p, "gold"))
    c.setLineWidth(2.4)
    c.rect(inset * mm, inset * mm, W - 2 * inset * mm, H - 2 * inset * mm, fill=0, stroke=1)
    c.setLineWidth(0.8)
    c.rect((inset + 3) * mm, (inset + 3) * mm,
           W - 2 * (inset + 3) * mm, H - 2 * (inset + 3) * mm, fill=0, stroke=1)


def _centered_name(c, spec, p, cx, top_y, max_w, base_size, min_size=22):
    """Draw the facility name centred, shrinking / wrapping to fit; returns bottom y."""
    size = base_size
    lines = nh._wrap(c, spec["title"], "Helvetica-Bold", size, max_w)
    while len(lines) > 2 and size > min_size:
        size -= 2
        lines = nh._wrap(c, spec["title"], "Helvetica-Bold", size, max_w)
    lines = lines[:2]
    lead = size * 1.15
    c.setFillColor(_c(p, "t_light"))
    y = top_y
    for ln in lines:
        c.setFont("Helvetica-Bold", size)
        c.drawCentredString(cx, y, ln)
        y -= lead
    return y + lead  # baseline of the last line drawn


def draw_board(c, spec, p):
    W, H = 300 * mm, 200 * mm
    c.setFillColor(_c(p, "teal_deep"))
    c.rect(0, 0, W, H, fill=1, stroke=0)
    _frame(c, W, H, p)
    nh.draw_aegis_star(c, W / 2, H - 42 * mm, 20 * mm, palette=p)
    c.setFillColor(_c(p, "gold"))
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(W / 2, H - 78 * mm, spec["authority"])
    y = _centered_name(c, spec, p, W / 2, H - 108 * mm, W - 60 * mm, 46)
    c.setFillColor(_c(p, "t_soft"))
    c.setFont("Helvetica", 20)
    c.drawCentredString(W / 2, y - 12 * mm, spec["subtitle"])
    c.setFillColor(_c(p, "gold"))
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(W / 2, 20 * mm, spec["footer"])


def draw_plaque(c, spec, p):
    W, H = 160 * mm, 240 * mm
    c.setFillColor(_c(p, "teal_deep"))
    c.rect(0, 0, W, H, fill=1, stroke=0)
    _frame(c, W, H, p, inset=7)
    nh.draw_aegis_star(c, W / 2, H - 40 * mm, 16 * mm, palette=p)
    c.setFillColor(_c(p, "gold"))
    c.setFont("Helvetica-Bold", 12.5)
    c.drawCentredString(W / 2, H - 70 * mm, spec["authority"])
    y = _centered_name(c, spec, p, W / 2, H - 96 * mm, W - 28 * mm, 30, min_size=18)
    c.setFillColor(_c(p, "t_soft"))
    c.setFont("Helvetica", 14)
    c.drawCentredString(W / 2, y - 10 * mm, spec["subtitle"])
    c.setFillColor(_c(p, "gold"))
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(W / 2, 18 * mm, spec["footer"])


def draw_oval(c, spec, p):
    W, H = 280 * mm, 190 * mm
    # page background = paper so the oval reads as a cut-out plaque shape
    c.setFillColor(_c(p, "paper"))
    c.rect(0, 0, W, H, fill=1, stroke=0)
    # oval body
    c.setFillColor(_c(p, "teal_deep"))
    c.setStrokeColor(_c(p, "gold"))
    c.setLineWidth(3)
    c.ellipse(8 * mm, 8 * mm, W - 8 * mm, H - 8 * mm, fill=1, stroke=1)
    c.setLineWidth(1)
    c.ellipse(13 * mm, 13 * mm, W - 13 * mm, H - 13 * mm, fill=0, stroke=1)
    nh.draw_aegis_star(c, W / 2, H - 46 * mm, 16 * mm, palette=p)
    c.setFillColor(_c(p, "gold"))
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(W / 2, H - 74 * mm, spec["authority"])
    y = _centered_name(c, spec, p, W / 2, H - 98 * mm, W - 80 * mm, 34, min_size=20)
    c.setFillColor(_c(p, "t_soft"))
    c.setFont("Helvetica", 15)
    c.drawCentredString(W / 2, y - 10 * mm, spec["subtitle"])
    c.setFillColor(_c(p, "gold"))
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(W / 2, 30 * mm, spec["footer"])


def draw_fascia(c, spec, p):
    W, H = 700 * mm, 150 * mm
    c.setFillColor(_c(p, "teal_deep"))
    c.rect(0, 0, W, H, fill=1, stroke=0)
    _frame(c, W, H, p, inset=8)
    nh.draw_aegis_star(c, 80 * mm, H / 2, 40 * mm, palette=p)
    lx = 150 * mm
    c.setFillColor(_c(p, "gold"))
    c.setFont("Helvetica-Bold", 20)
    c.drawString(lx, H - 52 * mm, spec["authority"])
    # name (single line, shrink to fit remaining width)
    from reportlab.pdfbase.pdfmetrics import stringWidth
    max_w = W - lx - 40 * mm
    size = 54
    while size > 24 and stringWidth(spec["title"], "Helvetica-Bold", size) > max_w:
        size -= 2
    c.setFillColor(_c(p, "t_light"))
    c.setFont("Helvetica-Bold", size)
    c.drawString(lx, H - 92 * mm, spec["title"])
    c.setFillColor(_c(p, "t_soft"))
    c.setFont("Helvetica", 18)
    c.drawString(lx, H - 116 * mm, spec["subtitle"])
    c.setFillColor(_c(p, "gold"))
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(W - 40 * mm, 26 * mm, spec["footer"])


_DRAW = {"board": draw_board, "plaque": draw_plaque, "oval": draw_oval, "fascia": draw_fascia}


def sign_spec(fac, type_label=None):
    label = (type_label or fac.get("facility_type", "")).title()
    return {
        "authority": "NOVADOMUS HEALTH SERVICE",
        "title": fac["legal_name"],
        "subtitle": f"{label}  \u00b7  {fac.get('state', '')}".strip(" \u00b7"),
        "footer": f"REGISTERED FACILITY  \u00b7  {fac['id']}",
    }


def render_sign(variant, spec, palette, path):
    W, H = SIZES[variant]
    c = canvas.Canvas(path, pagesize=(W * mm, H * mm))
    _DRAW[variant](c, spec, palette)
    c.showPage()
    c.save()
    return path


def generate_signage(fac, out_dir, type_label=None):
    os.makedirs(out_dir, exist_ok=True)
    spec = sign_spec(fac, type_label)
    made = []
    for v in VARIANTS:
        made.append(render_sign(v, spec, nh.HEALTH_PALETTE,
                                os.path.join(out_dir, f"{fac['id']}_sign_{v}_color.pdf")))
        made.append(render_sign(v, spec, nh.bw_palette(),
                                os.path.join(out_dir, f"{fac['id']}_sign_{v}_bw.pdf")))
    return made


if __name__ == "__main__":
    demo = {"id": "NVF-0001", "legal_name": "Arisia Central Hospital",
            "facility_type": "hospital", "state": "Ariesia"}
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signage_demo")
    files = generate_signage(demo, out)
    print(f"Wrote {len(files)} sign PDFs to {out}")
