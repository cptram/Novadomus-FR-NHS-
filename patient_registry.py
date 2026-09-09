"""
patient_registry.py  —  Novadomus Health Service, Phase 3: Patient Registry

Registers patients and issues the National Health Card. Mints NVP-#### IDs
(the MRN), 10-year validity, links to a home facility and optionally a citizen
NVC-#### record.

Privacy rule (inherited from the Citizen Registry):
    * CARD FACE  (public):    name, health ID, home facility, issued / expires
    * QR PAYLOAD (protected):  DOB, sex, blood type, allergies, chronic flag,
                               coverage tier, emergency contact
The protected fields are NEVER printed on the face — they are only readable by
scanning the QR.

Depends on nova_health.py (+ reportlab). Run:  py patient_registry.py
"""

import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nova_health as nh

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "novadomus_health.db")
CARD_DIR = os.path.join(APP_DIR, "health_cards")

CARD_YEARS = 10  # National Health Card validity

COVERAGE = ["Public", "Standard", "Premium"]
BLOOD = ["", "O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"]
SEX = ["", "F", "M", "X"]


# --------------------------------------------------------------------------
# Data layer (pure)
# --------------------------------------------------------------------------
def _today():
    return datetime.date.today().isoformat()


def _plus_years(iso, years):
    d = datetime.date.fromisoformat(iso)
    try:
        return d.replace(year=d.year + years).isoformat()
    except ValueError:
        return d.replace(year=d.year + years, day=28).isoformat()


def connect():
    return nh.init_db(DB_PATH)


def facility_choices(conn):
    """[(nvf_id, 'NVF-0001 \u2014 Legal Name'), ...] for the home-facility picker."""
    rows = conn.execute(
        "SELECT id, legal_name FROM facilities ORDER BY id").fetchall()
    return [(r[0], f"{r[0]} \u2014 {r[1]}") for r in rows]


def facility_name(conn, fid):
    if not fid:
        return None
    r = conn.execute("SELECT legal_name FROM facilities WHERE id=?", (fid,)).fetchone()
    return r[0] if r else None


def add_patient(conn, d):
    pid = nh.next_id(conn, "patient")
    issued = _today()
    expires = _plus_years(issued, CARD_YEARS)
    vc = nh.verify_code("patient", pid)
    conn.execute(
        "INSERT INTO patients (id, full_name, dob, sex, home_facility, citizen_id, "
        "coverage_tier, verify_code, blood_type, allergies, chronic_flag, status, "
        "issued_on, expires_on) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'active', ?, ?)",
        (pid, d["full_name"], d.get("dob"), d.get("sex"), d.get("home_facility"),
         d.get("citizen_id"), d.get("coverage_tier"), vc, d.get("blood_type"),
         d.get("allergies"), 1 if d.get("chronic_flag") else 0, issued, expires))
    _set_contact(conn, pid, d.get("contact"))
    conn.commit()
    return pid


def update_patient(conn, pid, d):
    conn.execute(
        "UPDATE patients SET full_name=?, dob=?, sex=?, home_facility=?, citizen_id=?, "
        "coverage_tier=?, blood_type=?, allergies=?, chronic_flag=? WHERE id=?",
        (d["full_name"], d.get("dob"), d.get("sex"), d.get("home_facility"),
         d.get("citizen_id"), d.get("coverage_tier"), d.get("blood_type"),
         d.get("allergies"), 1 if d.get("chronic_flag") else 0, pid))
    _set_contact(conn, pid, d.get("contact"))
    conn.commit()


def _set_contact(conn, pid, contact):
    conn.execute("DELETE FROM patient_contacts WHERE patient_id=?", (pid,))
    if contact and (contact.get("name") or contact.get("phone")):
        conn.execute(
            "INSERT INTO patient_contacts (patient_id, name, relation, phone) "
            "VALUES (?,?,?,?)",
            (pid, contact.get("name", ""), contact.get("relation", ""),
             contact.get("phone", "")))


def delete_patient(conn, pid):
    conn.execute("DELETE FROM patient_contacts WHERE patient_id=?", (pid,))
    conn.execute("DELETE FROM patient_flags WHERE patient_id=?", (pid,))
    conn.execute("DELETE FROM patients WHERE id=?", (pid,))
    conn.commit()


def _row_to_dict(conn, row):
    cols = [c[1] for c in conn.execute("PRAGMA table_info(patients)")]
    return dict(zip(cols, row))


def list_patients(conn):
    rows = conn.execute("SELECT * FROM patients ORDER BY id").fetchall()
    return [_row_to_dict(conn, r) for r in rows]


def get_patient(conn, pid):
    r = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    return _row_to_dict(conn, r) if r else None


def get_contact(conn, pid):
    r = conn.execute(
        "SELECT name, relation, phone FROM patient_contacts WHERE patient_id=?",
        (pid,)).fetchone()
    return {"name": r[0], "relation": r[1], "phone": r[2]} if r else None


def counts(conn):
    total = conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    today = _today()
    horizon = (datetime.date.fromisoformat(today) + datetime.timedelta(days=90)).isoformat()
    expiring = conn.execute(
        "SELECT COUNT(*) FROM patients WHERE expires_on IS NOT NULL "
        "AND expires_on <= ? AND expires_on >= ?", (horizon, today)).fetchone()[0]
    return total, expiring


# --------------------------------------------------------------------------
# Card generation  (public face + protected QR)
# --------------------------------------------------------------------------
def protected_payload(pat, contact):
    """The QR block: verify line + protected fields. Never printed on the face."""
    lines = [pat.get("verify_code") or nh.verify_code("patient", pat["id"])]

    def add(k, v):
        if v not in (None, "", 0):
            lines.append(f"{k}={v}")

    add("NAME", pat.get("full_name"))
    add("DOB", pat.get("dob"))
    add("SEX", pat.get("sex"))
    add("BLOOD", pat.get("blood_type"))
    add("ALLERGIES", pat.get("allergies"))
    add("CHRONIC", "Y" if pat.get("chronic_flag") else None)
    add("COVERAGE", pat.get("coverage_tier"))
    if contact and (contact.get("name") or contact.get("phone")):
        ice = f"{contact.get('name','')} ({contact.get('relation','')}) {contact.get('phone','')}"
        add("ICE", " ".join(ice.split()))
    return "\n".join(lines)


def patient_spec(pat, fac_label, contact):
    label = fac_label or "\u2014"
    if len(label) > 34:
        label = label[:33] + "\u2026"
    return {
        "authority": "NOVADOMUS HEALTH SERVICE",
        "kind": "NATIONAL HEALTH CARD",
        "title": pat["full_name"],                     # public
        "subtitle": label,                             # public (home facility)
        "id_code": pat["id"],                          # public
        "fields": [                                    # public only
            ("Issued", pat.get("issued_on") or "\u2014"),
            ("Expires", pat.get("expires_on") or "\u2014"),
            ("Citizen", pat.get("citizen_id") or "\u2014"),
        ],
        "qr_payload": protected_payload(pat, contact),  # protected
        "barcode": pat["id"],
    }


PROTECTED_FIELDS = ("blood_type", "allergies", "coverage_tier")


def _leaks(needle, face):
    """
    True if `needle` really appears on the face as a distinct token.

    Substring matching alone gives false positives (the digit of a boolean flag,
    or a short code, can occur inside an ID or a date), so only meaningful
    values are checked and they must match on word boundaries.
    """
    import re
    s = str(needle).strip()
    if len(s) < 2:            # booleans / single chars are never printed verbatim
        return False
    return re.search(r"(?<!\w)" + re.escape(s.lower()) + r"(?!\w)", face) is not None


def assert_face_is_clean(spec, pat, contact=None):
    """
    Enforcement guard for the privacy model.

    Raises if any protected value would be printed on the card FACE. The face is
    every visible string in the spec except the QR payload. This exists so the
    rule can't silently regress the next time the card layout changes.
    """
    face = " ".join(
        [str(spec.get("title", "")), str(spec.get("subtitle", "")),
         str(spec.get("kind", "")), str(spec.get("id_code", ""))]
        + [f"{a} {b}" for a, b in spec.get("fields", [])]
    ).lower()

    for key in PROTECTED_FIELDS:
        val = pat.get(key)
        if val in (None, "", 0):
            continue
        if _leaks(val, face):
            raise AssertionError(
                f"Privacy violation: protected field '{key}' ({val!r}) "
                f"would be printed on the card face.")

    if contact:
        for part in (contact.get("name"), contact.get("phone")):
            if part and _leaks(part, face):
                raise AssertionError(
                    f"Privacy violation: emergency contact ({part!r}) "
                    f"would be printed on the card face.")
    return True


def generate_card(pat, contact, fac_label, out_dir=CARD_DIR):
    os.makedirs(out_dir, exist_ok=True)
    spec = patient_spec(pat, fac_label, contact)
    assert_face_is_clean(spec, pat, contact)   # privacy model enforced here
    color = os.path.join(out_dir, f"{pat['id']}_healthcard_color.pdf")
    bw = os.path.join(out_dir, f"{pat['id']}_healthcard_bw.pdf")
    nh.render_credential_page(spec, nh.HEALTH_PALETTE, color)
    nh.render_credential_page(spec, nh.bw_palette(), bw)
    return color, bw


def _open_path(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)          # noqa
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except Exception:
        pass


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------
def main():
    import tkinter as tk
    from tkinter import ttk, messagebox

    P = nh.HEALTH_PALETTE
    TEAL, TEALD, GOLD, CARE, PAPER, INK = (P["teal"], P["teal_deep"], P["gold"],
                                           P["care"], P["paper"], P["ink"])

    conn = connect()

    root = tk.Tk()
    root.title("Novadomus Health \u2014 Patient Registry")
    root.geometry("1000x660")
    root.configure(bg=PAPER)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("TLabel", background=PAPER, foreground=INK)
    style.configure("Prot.TLabel", background=PAPER, foreground="#2E7B80",
                    font=("Helvetica", 9, "italic"))
    style.configure("TButton", padding=6)
    style.configure("Accent.TButton", foreground="#ffffff")
    style.map("Accent.TButton", background=[("!disabled", TEAL), ("active", TEALD)])
    style.configure("Treeview", rowheight=24)
    style.configure("Treeview.Heading", font=("Helvetica", 9, "bold"))

    header = tk.Frame(root, bg=TEALD, height=58)
    header.pack(side="top", fill="x")
    header.pack_propagate(False)
    emb = tk.Canvas(header, width=46, height=46, bg=TEALD, highlightthickness=0)
    emb.place(x=12, y=6)
    _tk_aegis_star(emb, 23, 23, 20, P)
    tk.Label(header, text="Novadomus Health Service", bg=TEALD, fg=GOLD,
             font=("Helvetica", 15, "bold")).place(x=68, y=8)
    tk.Label(header, text="Patient Registry \u2014 National Health Card", bg=TEALD,
             fg="#BFD6D2", font=("Helvetica", 9)).place(x=70, y=32)
    stat = tk.Label(header, text="", bg=TEALD, fg="#F4F1E6", font=("Helvetica", 9))
    stat.place(relx=1.0, x=-14, y=20, anchor="ne")

    body = tk.Frame(root, bg=PAPER)
    body.pack(fill="both", expand=True, padx=12, pady=10)

    form = tk.LabelFrame(body, text=" Patient ", bg=PAPER, fg=TEALD,
                         font=("Helvetica", 10, "bold"), padx=12, pady=8)
    form.pack(side="left", fill="y")
    form.columnconfigure(1, weight=1)

    fields = {}
    selected = {"id": None}
    fac_map = {}   # combobox label -> nvf id

    r = 0

    def add_row(label, widget, style_label="TLabel"):
        nonlocal r
        ttk.Label(form, text=label, style=style_label).grid(
            row=r, column=0, sticky="w", pady=3, padx=(0, 8))
        widget.grid(row=r, column=1, sticky="ew", pady=3)
        r += 1

    fields["full_name"] = ttk.Entry(form, width=32)
    add_row("Full name", fields["full_name"])
    fields["dob"] = ttk.Entry(form, width=32)
    add_row("Date of birth", fields["dob"])
    fields["sex"] = ttk.Combobox(form, values=SEX, state="readonly", width=30)
    fields["sex"].current(0)
    add_row("Sex", fields["sex"])

    fields["home_facility"] = ttk.Combobox(form, state="readonly", width=30)
    add_row("Home facility", fields["home_facility"])
    fields["citizen_id"] = ttk.Entry(form, width=32)
    add_row("Citizen ID", fields["citizen_id"])

    # protected section divider
    ttk.Separator(form, orient="horizontal").grid(
        row=r, column=0, columnspan=2, sticky="ew", pady=(8, 2)); r += 1
    ttk.Label(form, text="Protected \u2014 stored in QR only",
              style="Prot.TLabel").grid(row=r, column=0, columnspan=2, sticky="w"); r += 1

    fields["coverage_tier"] = ttk.Combobox(form, values=COVERAGE, state="readonly", width=30)
    fields["coverage_tier"].current(0)
    add_row("Coverage tier", fields["coverage_tier"])
    fields["blood_type"] = ttk.Combobox(form, values=BLOOD, state="readonly", width=30)
    fields["blood_type"].current(0)
    add_row("Blood type", fields["blood_type"])
    fields["allergies"] = ttk.Entry(form, width=32)
    add_row("Allergies", fields["allergies"])

    chronic_var = tk.IntVar(value=0)
    ttk.Checkbutton(form, text="Chronic condition", variable=chronic_var).grid(
        row=r, column=1, sticky="w", pady=3); r += 1

    fields["ice_name"] = ttk.Entry(form, width=32)
    add_row("ICE name", fields["ice_name"])
    fields["ice_relation"] = ttk.Entry(form, width=32)
    add_row("ICE relation", fields["ice_relation"])
    fields["ice_phone"] = ttk.Entry(form, width=32)
    add_row("ICE phone", fields["ice_phone"])

    def refresh_facilities():
        choices = facility_choices(conn)
        fac_map.clear()
        labels = [""]
        for fid, lbl in choices:
            fac_map[lbl] = fid
            labels.append(lbl)
        fields["home_facility"]["values"] = labels

    def read_form():
        name = fields["full_name"].get().strip()
        if not name:
            messagebox.showwarning("Missing", "Full name is required.")
            return None
        home_lbl = fields["home_facility"].get()
        return {
            "full_name": name,
            "dob": fields["dob"].get().strip(),
            "sex": fields["sex"].get(),
            "home_facility": fac_map.get(home_lbl),
            "citizen_id": fields["citizen_id"].get().strip(),
            "coverage_tier": fields["coverage_tier"].get(),
            "blood_type": fields["blood_type"].get(),
            "allergies": fields["allergies"].get().strip(),
            "chronic_flag": chronic_var.get(),
            "contact": {"name": fields["ice_name"].get().strip(),
                        "relation": fields["ice_relation"].get().strip(),
                        "phone": fields["ice_phone"].get().strip()},
        }

    def clear_form():
        selected["id"] = None
        for k, w in fields.items():
            if isinstance(w, ttk.Combobox):
                w.set("")
            else:
                w.delete(0, "end")
        fields["sex"].current(0)
        fields["coverage_tier"].current(0)
        fields["blood_type"].current(0)
        chronic_var.set(0)
        sel_lbl.config(text="New patient")

    def load_into_form(pat):
        clear_form()
        selected["id"] = pat["id"]
        fields["full_name"].insert(0, pat.get("full_name") or "")
        fields["dob"].insert(0, pat.get("dob") or "")
        fields["sex"].set(pat.get("sex") or "")
        if pat.get("home_facility"):
            for lbl, fid in fac_map.items():
                if fid == pat["home_facility"]:
                    fields["home_facility"].set(lbl)
                    break
        fields["citizen_id"].insert(0, pat.get("citizen_id") or "")
        fields["coverage_tier"].set(pat.get("coverage_tier") or COVERAGE[0])
        fields["blood_type"].set(pat.get("blood_type") or "")
        fields["allergies"].insert(0, pat.get("allergies") or "")
        chronic_var.set(1 if pat.get("chronic_flag") else 0)
        contact = get_contact(conn, pat["id"])
        if contact:
            fields["ice_name"].insert(0, contact.get("name") or "")
            fields["ice_relation"].insert(0, contact.get("relation") or "")
            fields["ice_phone"].insert(0, contact.get("phone") or "")
        sel_lbl.config(text=f"Editing {pat['id']}")

    btns = tk.Frame(form, bg=PAPER)
    btns.grid(row=r, column=0, columnspan=2, pady=(10, 4), sticky="ew"); r += 1

    def do_save():
        d = read_form()
        if not d:
            return
        if selected["id"]:
            update_patient(conn, selected["id"], d)
            pid = selected["id"]
        else:
            pid = add_patient(conn, d)
        refresh()
        clear_form()
        messagebox.showinfo("Saved", f"Patient saved as {pid}.")

    def do_card():
        if not selected["id"]:
            messagebox.showinfo("Select", "Select a patient from the list first.")
            return
        pat = get_patient(conn, selected["id"])
        contact = get_contact(conn, pat["id"])
        fac_lbl = facility_name(conn, pat.get("home_facility"))
        try:
            color, bw = generate_card(pat, contact, fac_lbl)
        except AssertionError as e:
            messagebox.showerror("Privacy check failed",
                                 f"{e}\n\nThe card was not printed.")
            return
        _open_path(color)
        messagebox.showinfo(
            "Health card",
            f"Saved to the 'health_cards' folder:\n\n"
            f"{os.path.basename(color)}\n{os.path.basename(bw)}\n\n"
            f"Protected data is in the QR only \u2014 not on the card face.")

    def do_delete():
        if not selected["id"]:
            return
        if messagebox.askyesno("Delete", f"Delete {selected['id']} permanently?"):
            delete_patient(conn, selected["id"])
            refresh()
            clear_form()

    ttk.Button(btns, text="Save", style="Accent.TButton", command=do_save).pack(side="left")
    ttk.Button(btns, text="New", command=clear_form).pack(side="left", padx=6)
    ttk.Button(btns, text="Generate card", command=do_card).pack(side="left")
    ttk.Button(btns, text="Delete", command=do_delete).pack(side="left", padx=6)

    sel_lbl = ttk.Label(form, text="New patient", foreground=TEALD,
                        font=("Helvetica", 9, "italic"))
    sel_lbl.grid(row=r, column=0, columnspan=2, sticky="w", pady=(4, 0)); r += 1

    # list (right)
    right = tk.Frame(body, bg=PAPER)
    right.pack(side="left", fill="both", expand=True, padx=(14, 0))
    cols = ("id", "name", "facility", "expires")
    tree = ttk.Treeview(right, columns=cols, show="headings", selectmode="browse")
    for c, w, txt in [("id", 80, "Health ID"), ("name", 220, "Name"),
                      ("facility", 170, "Home facility"), ("expires", 100, "Expires")]:
        tree.heading(c, text=txt)
        tree.column(c, width=w, anchor="w")
    tree.pack(side="left", fill="both", expand=True)
    sb = ttk.Scrollbar(right, orient="vertical", command=tree.yview)
    sb.pack(side="left", fill="y")
    tree.configure(yscrollcommand=sb.set)

    def on_select(_evt):
        item = tree.focus()
        if item:
            pat = get_patient(conn, item)
            if pat:
                load_into_form(pat)

    tree.bind("<<TreeviewSelect>>", on_select)

    def refresh():
        refresh_facilities()
        tree.delete(*tree.get_children())
        for pat in list_patients(conn):
            fn = facility_name(conn, pat.get("home_facility")) or ""
            tree.insert("", "end", iid=pat["id"], values=(
                pat["id"], pat["full_name"], fn, pat.get("expires_on", "")))
        total, expiring = counts(conn)
        stat.config(text=f"{total} patients    Expiring \u2264 90d: {expiring}")

    refresh()
    root.mainloop()


def _tk_aegis_star(cv, cx, cy, R, p):
    """Draw the Aegis Star on a Tk canvas so the app window itself is branded."""
    import math
    pts = []
    for k in range(8):
        ang = math.radians(90 - k * 45)
        rad = R if k % 2 == 0 else 0.40 * R
        pts += [cx + rad * math.cos(ang), cy - rad * math.sin(ang)]
    cv.create_polygon(pts, fill=p["teal"], outline=p["gold"], width=1.5)
    cv.create_line(cx, cy - 0.60 * R, cx, cy + 0.60 * R,
                   fill=p["gold_lite"], width=max(1, int(0.09 * R)), capstyle="round")


if __name__ == "__main__":
    main()
