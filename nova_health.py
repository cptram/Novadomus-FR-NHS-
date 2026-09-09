"""
nova_health.py  —  Novadomus Health Service shared module (Phase 0)

Provides, for every downstream health app (facility / provider / patient /
encounter / prescription / lab / immunization / billing):

    * HEALTH_PALETTE      deep-teal + gold identity, with a health accent and
                          text-on-dark roles kept distinct (t_light / t_soft)
    * draw_aegis_star()   the health sub-emblem, drawn as a vector (no font
                          glyphs) so it renders anywhere, at any size
    * init_db()           creates the full health schema (all phases stubbed)
    * next_id()           mints NVP-#### / NVM-#### / NVF-#### / ... IDs
    * verify_code()       builds NVD:DOMAIN:TOKEN:CHECK verify strings
    * check_char()        deterministic check character used across the suite

Design notes
------------
* If nova_brand.py is present alongside this file its PALETTE is used as the
  base so the health palette never drifts from the master identity; otherwise
  a matching default is used.  Same graceful pattern for nova_pdf later.
* Credential *layout* helpers (patient card, provider badge, facility card)
  arrive in Phase 1, built against the existing nova_pdf engine.
"""

import math
import sqlite3

# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------
# Base identity.  Roles are split so text-on-dark never borrows a
# text-on-light colour (the invisible-text bug guard).
_DEFAULT_PALETTE = {
    # backgrounds / structure
    "teal_deep": "#0E3B3E",   # darkest teal  (card fields, headers)
    "teal":      "#12595E",   # primary teal
    "teal_soft": "#2E7B80",   # lighter teal for fills
    "paper":     "#FBFAF4",   # warm white page
    "hairline":  "#D8C7A0",   # soft gold rule lines
    # accents
    "gold":      "#C9A227",   # primary gold
    "gold_lite": "#E4C766",   # highlight gold
    "care":      "#3FA79B",   # HEALTH accent (jade) — the health-domain tint
    # text-on-light
    "ink":       "#0B2A2C",   # body text on paper
    "ink_soft":  "#4A6163",   # muted text on paper
    # text-on-dark  (NEVER reuse the ink roles here)
    "t_light":   "#F4F1E6",   # primary text on teal
    "t_soft":    "#BFD6D2",   # muted text on teal
}

try:
    from nova_brand import PALETTE as _BRAND        # type: ignore
    HEALTH_PALETTE = {**_DEFAULT_PALETTE, **dict(_BRAND)}
    # ensure the health-only roles always exist even if brand lacks them
    HEALTH_PALETTE.setdefault("care", _DEFAULT_PALETTE["care"])
    HEALTH_PALETTE.setdefault("t_light", _DEFAULT_PALETTE["t_light"])
    HEALTH_PALETTE.setdefault("t_soft", _DEFAULT_PALETTE["t_soft"])
except Exception:
    HEALTH_PALETTE = dict(_DEFAULT_PALETTE)


def hex_to_color(h):
    """'#RRGGBB' -> reportlab Color (imported lazily so DB-only use needs no PDF stack)."""
    from reportlab.lib.colors import Color
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return Color(r, g, b)


# --------------------------------------------------------------------------
# Aegis Star  —  the health sub-emblem
# --------------------------------------------------------------------------
# A Novadomus four-point star with a single-serpent Asclepius staff drawn in
# gold over it.  Everything is a vector path; no ✦ glyph, no fonts.
def draw_aegis_star(c, cx, cy, R, palette=None,
                    star_fill=None, star_edge=None, staff=None):
    """
    Draw the Aegis Star centred at (cx, cy) with outer radius R onto a
    reportlab canvas `c`.  Colours fall back to the health palette.
    """
    p = palette or HEALTH_PALETTE
    star_fill = star_fill or p["teal"]
    star_edge = star_edge or p["gold"]
    staff = staff or p["gold_lite"]

    c.saveState()

    # --- four-point star (8 vertices, alternating outer / inner radius) ---
    inner = 0.40 * R
    path = c.beginPath()
    for k in range(8):
        ang = math.radians(90 - k * 45)
        rad = R if k % 2 == 0 else inner
        x = cx + rad * math.cos(ang)
        y = cy + rad * math.sin(ang)
        if k == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.close()
    c.setFillColor(hex_to_color(star_fill))
    c.setStrokeColor(hex_to_color(star_edge))
    c.setLineWidth(max(0.6, 0.03 * R))
    c.drawPath(path, fill=1, stroke=1)

    # --- Asclepius staff: rod + single serpent, in gold ---
    rod_top = cy + 0.62 * R
    rod_bot = cy - 0.62 * R
    c.setStrokeColor(hex_to_color(staff))
    c.setLineCap(1)  # round caps
    c.setLineWidth(max(1.0, 0.055 * R))
    c.line(cx, rod_bot, cx, rod_top)

    # Below card scale the serpent turns to mush, so drop it and keep the
    # rod only — the star + staff silhouette still reads at favicon size.
    if R < 22:
        c.restoreState()
        return

    # serpent: a smooth coil crossing the rod, bottom -> top, as cubic beziers
    amp = 0.20 * R
    coils = 3
    span = rod_top - 0.14 * R - (rod_bot + 0.10 * R)
    seg = span / coils
    y0 = rod_bot + 0.10 * R
    ser = c.beginPath()
    ser.moveTo(cx, y0)
    side = 1
    for i in range(coils):
        y_next = y0 + seg
        y_mid = y0 + seg * 0.5
        # one half-coil: swing out to `side`, back to centre
        ser.curveTo(cx + side * amp, y0 + seg * 0.15,
                    cx + side * amp, y_mid + seg * 0.15,
                    cx, y_next)
        side *= -1
        y0 = y_next
    c.setStrokeColor(hex_to_color(staff))
    c.setLineWidth(max(0.9, 0.045 * R))
    c.drawPath(ser, fill=0, stroke=1)

    # serpent head
    hx = cx + amp * 0.55
    hy = rod_top - 0.10 * R
    c.setFillColor(hex_to_color(staff))
    c.circle(hx, hy, max(0.9, 0.055 * R), fill=1, stroke=0)

    c.restoreState()


# --------------------------------------------------------------------------
# IDs & verify codes
# --------------------------------------------------------------------------
# Domain -> (id prefix, verify namespace)
DOMAINS = {
    "patient":     ("NVP",  "PATIENT"),
    "provider":    ("NVM",  "PROVIDER"),
    "facility":    ("NVF",  "FACILITY"),
    "visit":       ("NVV",  "VISIT"),
    "prescription":("NVRx", "RX"),
    "lab":         ("NVL",  "LAB"),
    "immunization":("NVI",  "IMMUN"),
}

_CHECK_ALPHABET = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no I/O (ambiguity)


def check_char(payload):
    """Deterministic single check character over an arbitrary string."""
    total = sum((i + 1) * ord(ch) for i, ch in enumerate(str(payload)))
    return _CHECK_ALPHABET[total % len(_CHECK_ALPHABET)]


def next_id(conn, domain):
    """Mint the next sequential ID for a domain, e.g. next_id(conn,'patient') -> 'NVP-0007'."""
    if domain not in DOMAINS:
        raise ValueError(f"unknown domain: {domain}")
    prefix = DOMAINS[domain][0]
    cur = conn.cursor()
    cur.execute("INSERT INTO id_counters(prefix, last_seq) VALUES(?, 0) "
                "ON CONFLICT(prefix) DO NOTHING", (prefix,))
    cur.execute("UPDATE id_counters SET last_seq = last_seq + 1 WHERE prefix = ?", (prefix,))
    cur.execute("SELECT last_seq FROM id_counters WHERE prefix = ?", (prefix,))
    seq = cur.fetchone()[0]
    conn.commit()
    return f"{prefix}-{seq:04d}"


def verify_code(domain, token):
    """Build an NVD:DOMAIN:TOKEN:CHECK verify string for a credential."""
    ns = DOMAINS[domain][1] if domain in DOMAINS else str(domain).upper()
    token = str(token)
    body = f"NVD:{ns}:{token}"
    return f"{body}:{check_char(body)}"


# --------------------------------------------------------------------------
# Credential rendering  (shared: facility / provider / patient credentials)
# --------------------------------------------------------------------------
CARD_W_MM = 86.0
CARD_H_MM = 54.0


def bw_palette(palette=None):
    """
    Line-art B&W palette: white card, black text/outlines, printer-friendly.
    Every role flips together so text-on-background contrast is preserved
    (guards the half-flip 'invisible text' bug).
    """
    return {
        "teal_deep": "#FFFFFF", "teal": "#FFFFFF", "teal_soft": "#EEEEEE",
        "paper": "#FFFFFF", "hairline": "#000000",
        "gold": "#000000", "gold_lite": "#000000", "care": "#000000",
        "ink": "#000000", "ink_soft": "#333333",
        "t_light": "#000000", "t_soft": "#555555",
    }


def draw_qr(c, value, x, y, size):
    """Draw a QR of `value` at (x,y) sized `size` x `size` points (black on transparent)."""
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics import renderPDF
    qr = QrCodeWidget(value)
    b = qr.getBounds()
    w, h = b[2] - b[0], b[3] - b[1]
    d = Drawing(size, size,
                transform=[size / w, 0, 0, size / h, -b[0] * size / w, -b[1] * size / h])
    d.add(qr)
    renderPDF.draw(d, c, x, y)


def draw_code128(c, value, x, y, width, height, color="#000000"):
    """Draw a Code128 barcode of `value` scaled to `width` x `height` points at (x,y)."""
    from reportlab.graphics.barcode import code128
    bc = code128.Code128(str(value), barHeight=height, barWidth=0.9, humanReadable=False)
    natural = bc.width
    if natural <= 0:
        return
    c.saveState()
    c.translate(x, y)
    c.scale(width / natural, 1.0)
    bc.drawOn(c, 0, 0)
    c.restoreState()


def _wrap(c, text, font, size, max_w):
    c.setFont(font, size)
    from reportlab.pdfbase.pdfmetrics import stringWidth
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if stringWidth(trial, font, size) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def draw_credential_card(c, ox, oy, spec, palette=None):
    """
    Draw one credential card with its lower-left corner at (ox, oy).
    `spec` keys: authority, kind, title, subtitle, id_code,
                 fields=[(label,value),...], qr_payload, barcode
    """
    from reportlab.lib.units import mm
    p = palette or HEALTH_PALETTE
    W, H = CARD_W_MM * mm, CARD_H_MM * mm
    pad = 5 * mm

    def col(k):
        return hex_to_color(p[k])

    c.saveState()
    # card body + gold frame
    c.setFillColor(col("teal_deep"))
    c.roundRect(ox, oy, W, H, 3 * mm, fill=1, stroke=0)
    c.setStrokeColor(col("gold"))
    c.setLineWidth(1.2)
    c.roundRect(ox + 1.4 * mm, oy + 1.4 * mm, W - 2.8 * mm, H - 2.8 * mm, 2.4 * mm,
                fill=0, stroke=1)

    # emblem top-left
    draw_aegis_star(c, ox + pad + 6 * mm, oy + H - pad - 6 * mm, 6 * mm, palette=p)

    # authority / kind header (to the right of the emblem)
    hx = ox + pad + 15 * mm
    c.setFillColor(col("gold"))
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(hx, oy + H - pad - 3.2 * mm, spec.get("authority", ""))
    c.setFillColor(col("t_soft"))
    c.setFont("Helvetica", 6.2)
    c.drawString(hx, oy + H - pad - 6.6 * mm, spec.get("kind", ""))

    # facility / holder name (wrapped) — starts below the emblem's lower point,
    # shrinks to 2 lines for long names, subtitle & ID flow off the last line.
    max_w = W - 2 * pad - 2 * mm
    lines = _wrap(c, spec.get("title", ""), "Helvetica-Bold", 12, max_w)
    if len(lines) >= 2:
        tsize, lead = 10.5, 4.6 * mm
        lines = _wrap(c, spec.get("title", ""), "Helvetica-Bold", tsize, max_w)[:2]
    else:
        tsize, lead = 12, 5.2 * mm
    ty = oy + H - pad - 16 * mm
    c.setFillColor(col("t_light"))
    for line in lines:
        c.setFont("Helvetica-Bold", tsize)
        c.drawString(ox + pad, ty, line)
        ty -= lead
    if spec.get("subtitle"):
        c.setFillColor(col("t_soft"))
        c.setFont("Helvetica", 7.5)
        c.drawString(ox + pad, ty + lead - 4.2 * mm, spec["subtitle"])

    # ID code — prominent, gold
    c.setFillColor(col("gold_lite"))
    c.setFont("Helvetica-Bold", 13)
    c.drawString(ox + pad, oy + 19 * mm, spec.get("id_code", ""))

    # fields, small, bottom-left
    fy = oy + 15 * mm
    for label, value in (spec.get("fields") or [])[:3]:
        c.setFillColor(col("t_soft"))
        c.setFont("Helvetica", 5.4)
        c.drawString(ox + pad, fy, str(label).upper())
        c.setFillColor(col("t_light"))
        c.setFont("Helvetica", 7)
        c.drawString(ox + pad + 22 * mm, fy, str(value))
        fy -= 3.6 * mm

    # QR on a white panel, bottom-right
    qr_sz = 20 * mm
    qx = ox + W - pad - qr_sz
    qy = oy + pad
    c.setFillColor(hex_to_color("#FFFFFF"))
    c.roundRect(qx - 1.4 * mm, qy - 1.4 * mm, qr_sz + 2.8 * mm, qr_sz + 2.8 * mm,
                1.2 * mm, fill=1, stroke=0)
    if spec.get("qr_payload"):
        draw_qr(c, spec["qr_payload"], qx, qy, qr_sz)

    # Code128 strip along the very bottom-left, clear of the field rows
    if spec.get("barcode"):
        draw_code128(c, spec["barcode"], ox + pad, oy + 2.4 * mm, 34 * mm, 3.6 * mm)

    c.restoreState()


def render_credential_page(spec, palette, path):
    """Render a single credential centred true-size on a Letter page with crop marks."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import mm
    p = palette or HEALTH_PALETTE
    PW, PH = letter
    W, H = CARD_W_MM * mm, CARD_H_MM * mm
    ox, oy = (PW - W) / 2, (PH - H) / 2

    c = canvas.Canvas(path, pagesize=letter)
    # crop marks
    c.setStrokeColor(hex_to_color("#666666"))
    c.setLineWidth(0.4)
    m = 4 * mm
    for cx, cy in [(ox, oy), (ox + W, oy), (ox, oy + H), (ox + W, oy + H)]:
        sx = -1 if cx == ox else 1
        sy = -1 if cy == oy else 1
        c.line(cx + sx * 1.5 * mm, cy, cx + sx * m, cy)
        c.line(cx, cy + sy * 1.5 * mm, cx, cy + sy * m)
    draw_credential_card(c, ox, oy, spec, palette=p)
    c.showPage()
    c.save()
    return path


# --------------------------------------------------------------------------
# Schema  —  full scaffold, all phases stubbed
# --------------------------------------------------------------------------
SCHEMA_VERSION = 1

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY, value TEXT
);

CREATE TABLE IF NOT EXISTS id_counters (
    prefix TEXT PRIMARY KEY, last_seq INTEGER NOT NULL DEFAULT 0
);

-- Phase 1: facilities -----------------------------------------------------
CREATE TABLE IF NOT EXISTS facilities (
    id TEXT PRIMARY KEY,               -- NVF-####
    legal_name TEXT NOT NULL,
    facility_type TEXT NOT NULL,       -- clinic|hospital|urgent_care|lab|pharmacy
    state TEXT,                        -- Ariesia|Materra
    address TEXT,
    hours TEXT,
    bed_count INTEGER,
    administrator TEXT,
    verify_code TEXT,
    status TEXT DEFAULT 'active',
    registered_on TEXT,
    expires_on TEXT
);
CREATE TABLE IF NOT EXISTS facility_departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    facility_id TEXT REFERENCES facilities(id),
    name TEXT
);

-- Phase 2: providers ------------------------------------------------------
CREATE TABLE IF NOT EXISTS providers (
    id TEXT PRIMARY KEY,               -- NVM-####
    full_name TEXT NOT NULL,
    role TEXT,                         -- physician|nurse|technician|pharmacist|admin
    specialty TEXT,
    prescribing_authority INTEGER DEFAULT 0,   -- 0/1
    controlled_authority INTEGER DEFAULT 0,    -- 0/1
    verify_code TEXT,
    status TEXT DEFAULT 'active',
    issued_on TEXT,
    expires_on TEXT
);
CREATE TABLE IF NOT EXISTS provider_affiliations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT REFERENCES providers(id),
    facility_id TEXT REFERENCES facilities(id)
);
CREATE TABLE IF NOT EXISTS provider_licenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT REFERENCES providers(id),
    license_class TEXT,
    issued_on TEXT,
    expires_on TEXT
);

-- Phase 3: patients -------------------------------------------------------
CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY,               -- NVP-####  (this is the MRN)
    full_name TEXT NOT NULL,
    dob TEXT,
    sex TEXT,
    home_facility TEXT REFERENCES facilities(id),
    citizen_id TEXT,                   -- link to NVC-#### where applicable
    coverage_tier TEXT,
    verify_code TEXT,
    -- protected fields (QR payload only, never on card face):
    blood_type TEXT,
    allergies TEXT,
    chronic_flag INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    issued_on TEXT,
    expires_on TEXT
);
CREATE TABLE IF NOT EXISTS patient_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT REFERENCES patients(id),
    name TEXT, relation TEXT, phone TEXT
);
CREATE TABLE IF NOT EXISTS patient_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT REFERENCES patients(id),
    flag TEXT, note TEXT
);

-- Phase 4: encounters -----------------------------------------------------
CREATE TABLE IF NOT EXISTS encounters (
    id TEXT PRIMARY KEY,               -- NVV-####
    patient_id TEXT REFERENCES patients(id),
    provider_id TEXT REFERENCES providers(id),
    facility_id TEXT REFERENCES facilities(id),
    date TEXT, reason TEXT, disposition TEXT, notes TEXT,
    verify_code TEXT
);
CREATE TABLE IF NOT EXISTS vitals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_id TEXT REFERENCES encounters(id),
    kind TEXT, value TEXT
);
CREATE TABLE IF NOT EXISTS diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_id TEXT REFERENCES encounters(id),
    code TEXT, description TEXT
);

-- Phase 5: prescriptions --------------------------------------------------
CREATE TABLE IF NOT EXISTS prescriptions (
    id TEXT PRIMARY KEY,               -- NVRx-####
    patient_id TEXT REFERENCES patients(id),
    provider_id TEXT REFERENCES providers(id),
    drug TEXT, dose TEXT, quantity TEXT, directions TEXT,
    controlled INTEGER DEFAULT 0,
    docket TEXT,                       -- CIA-style case number for controlled
    verify_code TEXT,
    issued_on TEXT
);
CREATE TABLE IF NOT EXISTS rx_dispenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rx_id TEXT REFERENCES prescriptions(id),
    facility_id TEXT REFERENCES facilities(id),
    dispensed_on TEXT
);
CREATE TABLE IF NOT EXISTS controlled_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rx_id TEXT REFERENCES prescriptions(id),
    docket TEXT, event TEXT, at TEXT
);

-- Phase 6: labs & immunizations ------------------------------------------
CREATE TABLE IF NOT EXISTS lab_orders (
    id TEXT PRIMARY KEY,               -- NVL-####
    patient_id TEXT REFERENCES patients(id),
    provider_id TEXT REFERENCES providers(id),
    facility_id TEXT REFERENCES facilities(id),
    panel TEXT, ordered_on TEXT, status TEXT DEFAULT 'ordered',
    verify_code TEXT
);
CREATE TABLE IF NOT EXISTS lab_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lab_id TEXT REFERENCES lab_orders(id),
    analyte TEXT, value TEXT, unit TEXT, ref_range TEXT, flag TEXT
);
CREATE TABLE IF NOT EXISTS immunizations (
    id TEXT PRIMARY KEY,               -- NVI-####
    patient_id TEXT REFERENCES patients(id),
    provider_id TEXT REFERENCES providers(id),
    vaccine TEXT, lot TEXT, dose_no INTEGER, given_on TEXT,
    verify_code TEXT
);

-- Phase 7: billing --------------------------------------------------------
CREATE TABLE IF NOT EXISTS health_charges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT REFERENCES patients(id),
    encounter_id TEXT REFERENCES encounters(id),
    description TEXT, amount_nova REAL, posted_on TEXT, status TEXT DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS health_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    charge_id INTEGER REFERENCES health_charges(id),
    coverage_tier TEXT, covered_nova REAL, patient_nova REAL, status TEXT
);
"""


def init_db(path="novadomus_health.db"):
    """Create the full health schema at `path` (idempotent). Returns the connection."""
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO meta(key,value) VALUES('schema_version',?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (str(SCHEMA_VERSION),))
    conn.commit()
    return conn


# --------------------------------------------------------------------------
# Manifest hook (wire into novadomus_core.py in Phase 8)
# --------------------------------------------------------------------------
MANIFEST_ENTRY = {
    "domain": "health",
    "db": "novadomus_health.db",
    "prefixes": [v[0] for v in DOMAINS.values()],
    "verify_namespaces": [v[1] for v in DOMAINS.values()],
}


if __name__ == "__main__":
    # Smoke test: build the DB, mint one ID per domain, print verify codes.
    c = init_db(":memory:")
    print("schema_version:",
          c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
    print("tables:",
          [r[0] for r in c.execute(
              "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")])
    print()
    for dom in DOMAINS:
        i = next_id(c, dom)
        print(f"{dom:13s} -> {i:10s}  {verify_code(dom, i)}")

    # Keep the console open when the file is double-clicked (it's a library,
    # so this self-test is the only time it runs on its own).
    try:
        input("\nSelf-test OK. Press Enter to close this window...")
    except EOFError:
        pass
