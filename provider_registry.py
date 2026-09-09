"""
provider_registry.py  —  Novadomus Health Service, Phase 2: Provider Registry

Registers practitioners under the Novadomus Health Authority, mints NVM-####
numbers, tracks facility affiliations and licence terms, and prints the Provider
Identification badge in colour and line-art B&W.

PRIVACY MODEL (consistent with the Citizen Registry and Health Card)
    Badge FACE : name, provider ID, role, specialty, primary facility, validity
    QR ONLY    : licence class, prescribing authority, controlled authority,
                 full affiliation list

PRESCRIBING GATE
    Phase 5 (Prescriptions) may only issue against a provider whose record
    grants prescribing authority, and controlled prescriptions only where
    controlled authority is granted. `can_prescribe()` and `can_prescribe_
    controlled()` are the single source of truth for that rule.

Depends only on:  nova_health.py  (same folder)  +  reportlab.
Run:  py provider_registry.py
"""

import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nova_health as nh

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "novadomus_health.db")
BADGE_DIR = os.path.join(APP_DIR, "badges")

LICENCE_YEARS = 5  # provider licence term

ROLES = ["Physician", "Nurse", "Technician", "Pharmacist", "Administrator"]
LICENCE_CLASSES = ["General", "Specialist", "Consultant", "Provisional", "Auxiliary"]

# Roles that may hold prescribing authority at all. Administrators and
# technicians can never prescribe, whatever the checkbox says.
PRESCRIBER_ROLES = {"Physician", "Nurse", "Pharmacist"}
# Roles that may hold *controlled* prescribing authority.
CONTROLLED_ROLES = {"Physician"}

PROTECTED_FIELDS = ("licence_class", "prescribing", "controlled")


# --------------------------------------------------------------------------
# Data layer (pure — no GUI, unit-testable)
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


def normalise_authority(role, prescribing, controlled):
    """
    Enforce the role gate. Returns (prescribing, controlled) as 0/1.
    Controlled authority implies prescribing authority.
    """
    p = 1 if prescribing else 0
    c = 1 if controlled else 0
    if role not in PRESCRIBER_ROLES:
        p = 0
    if role not in CONTROLLED_ROLES:
        c = 0
    if c:
        p = 1
    return p, c


def add_provider(conn, d):
    pid = nh.next_id(conn, "provider")
    issued = _today()
    expires = _plus_years(issued, LICENCE_YEARS)
    vc = nh.verify_code("provider", pid)
    p, ctrl = normalise_authority(d.get("role"), d.get("prescribing"), d.get("controlled"))
    conn.execute(
        "INSERT INTO providers (id, full_name, role, specialty, prescribing_authority, "
        "controlled_authority, verify_code, status, issued_on, expires_on) "
        "VALUES (?,?,?,?,?,?,?, 'active', ?,?)",
        (pid, d["full_name"], d.get("role"), d.get("specialty"), p, ctrl, vc,
         issued, expires))
    conn.execute(
        "INSERT INTO provider_licenses (provider_id, license_class, issued_on, expires_on) "
        "VALUES (?,?,?,?)",
        (pid, d.get("licence_class"), issued, expires))
    _set_affiliations(conn, pid, d.get("affiliations") or [])
    conn.commit()
    return pid


def update_provider(conn, pid, d):
    p, ctrl = normalise_authority(d.get("role"), d.get("prescribing"), d.get("controlled"))
    conn.execute(
        "UPDATE providers SET full_name=?, role=?, specialty=?, prescribing_authority=?, "
        "controlled_authority=? WHERE id=?",
        (d["full_name"], d.get("role"), d.get("specialty"), p, ctrl, pid))
    conn.execute("UPDATE provider_licenses SET license_class=? WHERE provider_id=?",
                 (d.get("licence_class"), pid))
    _set_affiliations(conn, pid, d.get("affiliations") or [])
    conn.commit()


def _set_affiliations(conn, pid, facility_ids):
    conn.execute("DELETE FROM provider_affiliations WHERE provider_id=?", (pid,))
    for fid in facility_ids:
        if fid:
            conn.execute("INSERT INTO provider_affiliations(provider_id, facility_id) "
                         "VALUES(?,?)", (pid, fid))


def get_affiliations(conn, pid):
    """[(facility_id, legal_name), ...] in registration order."""
    return [(r[0], r[1]) for r in conn.execute(
        "SELECT f.id, f.legal_name FROM provider_affiliations a "
        "JOIN facilities f ON f.id = a.facility_id "
        "WHERE a.provider_id=? ORDER BY a.id", (pid,))]


def get_licence(conn, pid):
    r = conn.execute("SELECT license_class, issued_on, expires_on FROM provider_licenses "
                     "WHERE provider_id=? LIMIT 1", (pid,)).fetchone()
    return {"licence_class": r[0], "issued_on": r[1], "expires_on": r[2]} if r else {}


def delete_provider(conn, pid):
    conn.execute("DELETE FROM provider_affiliations WHERE provider_id=?", (pid,))
    conn.execute("DELETE FROM provider_licenses WHERE provider_id=?", (pid,))
    conn.execute("DELETE FROM providers WHERE id=?", (pid,))
    conn.commit()


def _row_to_dict(conn, row):
    cols = [c[1] for c in conn.execute("PRAGMA table_info(providers)")]
    return dict(zip(cols, row))


def list_providers(conn, search=None):
    if search:
        q = f"%{search.strip()}%"
        rows = conn.execute("SELECT * FROM providers WHERE full_name LIKE ? OR id LIKE ? "
                            "OR role LIKE ? ORDER BY id", (q, q, q)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM providers ORDER BY id").fetchall()
    return [_row_to_dict(conn, r) for r in rows]


def get_provider(conn, pid):
    r = conn.execute("SELECT * FROM providers WHERE id=?", (pid,)).fetchone()
    return _row_to_dict(conn, r) if r else None


def facility_choices(conn):
    return [(r[0], r[1]) for r in conn.execute(
        "SELECT id, legal_name FROM facilities ORDER BY legal_name")]


def counts(conn):
    total = conn.execute("SELECT COUNT(*) FROM providers").fetchone()[0]
    today = _today()
    horizon = (datetime.date.fromisoformat(today) + datetime.timedelta(days=90)).isoformat()
    expiring = conn.execute(
        "SELECT COUNT(*) FROM providers WHERE expires_on IS NOT NULL "
        "AND expires_on <= ? AND expires_on >= ?", (horizon, today)).fetchone()[0]
    prescribers = conn.execute(
        "SELECT COUNT(*) FROM providers WHERE prescribing_authority=1").fetchone()[0]
    return total, expiring, prescribers


# --------------------------------------------------------------------------
# Prescribing gate  —  single source of truth for Phase 5
# --------------------------------------------------------------------------
def is_licence_current(prov, on=None):
    exp = prov.get("expires_on")
    if not exp:
        return False
    return str(on or _today()) <= str(exp)


def can_prescribe(conn, pid, on=None):
    """True only if the provider is active, in-date, and holds prescribing authority."""
    prov = get_provider(conn, pid)
    if not prov:
        return False
    return (prov.get("status") == "active"
            and bool(prov.get("prescribing_authority"))
            and is_licence_current(prov, on))


def can_prescribe_controlled(conn, pid, on=None):
    prov = get_provider(conn, pid)
    if not prov:
        return False
    return (can_prescribe(conn, pid, on)
            and bool(prov.get("controlled_authority")))


# --------------------------------------------------------------------------
# Badge generation  (public face + protected QR)
# --------------------------------------------------------------------------
def protected_payload(conn, prov):
    """QR block: verify line + protected fields. Never printed on the face."""
    lic = get_licence(conn, prov["id"])
    lines = [prov.get("verify_code") or nh.verify_code("provider", prov["id"])]

    def add(k, v):
        if v not in (None, "", 0):
            lines.append(f"{k}={v}")

    add("NAME", prov.get("full_name"))
    add("ROLE", prov.get("role"))
    add("CLASS", lic.get("licence_class"))
    add("PRESCRIBE", "Y" if prov.get("prescribing_authority") else None)
    add("CONTROLLED", "Y" if prov.get("controlled_authority") else None)
    affs = get_affiliations(conn, prov["id"])
    if affs:
        add("AFFIL", "; ".join(f"{fid}" for fid, _ in affs))
    add("EXPIRES", prov.get("expires_on"))
    return "\n".join(lines)


def provider_spec(conn, prov, photo=None):
    affs = get_affiliations(conn, prov["id"])
    primary = affs[0][1] if affs else "\u2014"
    if len(primary) > 30:
        primary = primary[:29] + "\u2026"
    role = prov.get("role") or "\u2014"
    spec = {
        "authority": "NOVADOMUS HEALTH SERVICE",
        "kind": "PROVIDER IDENTIFICATION",
        "title": prov["full_name"],                       # public
        "subtitle": f"{role}  \u00b7  {prov.get('specialty') or 'General'}",  # public
        "id_code": prov["id"],                            # public
        "fields": [                                       # public only
            ("Facility", primary),
            ("Issued", prov.get("issued_on") or "\u2014"),
            ("Expires", prov.get("expires_on") or "\u2014"),
        ],
        "qr_payload": protected_payload(conn, prov),      # protected
        "barcode": prov["id"],
        "photo": photo,                                   # panel drawn even if None
    }
    return spec


def _leaks(needle, face):
    import re
    s = str(needle).strip()
    if len(s) < 2:
        return False
    return re.search(r"(?<!\w)" + re.escape(s.lower()) + r"(?!\w)", face) is not None


def assert_face_is_clean(spec, prov, licence=None):
    """Raise if a protected value would be printed on the badge face."""
    face = " ".join(
        [str(spec.get("title", "")), str(spec.get("subtitle", "")),
         str(spec.get("kind", "")), str(spec.get("id_code", ""))]
        + [f"{a} {b}" for a, b in spec.get("fields", [])]
    ).lower()

    if licence and licence.get("licence_class"):
        if _leaks(licence["licence_class"], face):
            raise AssertionError(
                f"Privacy violation: licence class "
                f"({licence['licence_class']!r}) would be printed on the badge face.")
    for key, label in (("prescribing_authority", "prescribing authority"),
                       ("controlled_authority", "controlled authority")):
        if prov.get(key) and _leaks("prescribing" if "pres" in key else "controlled", face):
            raise AssertionError(
                f"Privacy violation: {label} would be disclosed on the badge face.")
    return True


def generate_badge(conn, prov, photo=None, out_dir=BADGE_DIR):
    os.makedirs(out_dir, exist_ok=True)
    spec = provider_spec(conn, prov, photo)
    assert_face_is_clean(spec, prov, get_licence(conn, prov["id"]))
    color = os.path.join(out_dir, f"{prov['id']}_provider_badge_color.pdf")
    bw = os.path.join(out_dir, f"{prov['id']}_provider_badge_bw.pdf")
    nh.render_credential_page(spec, nh.HEALTH_PALETTE, color)
    nh.render_credential_page(spec, nh.bw_palette(), bw)
    return color, bw


def _open_path(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)          # noqa: Windows only
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
    from tkinter import ttk, messagebox, filedialog

    P = nh.HEALTH_PALETTE
    TEAL, TEALD, GOLD, PAPER, INK = P["teal"], P["teal_deep"], P["gold"], P["paper"], P["ink"]

    conn = connect()

    root = tk.Tk()
    root.title("Novadomus Health \u2014 Provider Registry")
    root.geometry("1040x680")
    root.configure(bg=PAPER)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("TLabel", background=PAPER, foreground=INK)
    style.configure("TCheckbutton", background=PAPER, foreground=INK)
    style.configure("TButton", padding=6)
    style.configure("Accent.TButton", foreground="#ffffff")
    style.map("Accent.TButton", background=[("!disabled", TEAL), ("active", TEALD)])
    style.configure("Treeview", rowheight=24)
    style.configure("Treeview.Heading", font=("Helvetica", 9, "bold"))

    # ---- header ----
    header = tk.Frame(root, bg=TEALD, height=58)
    header.pack(side="top", fill="x")
    header.pack_propagate(False)
    emb = tk.Canvas(header, width=46, height=46, bg=TEALD, highlightthickness=0)
    emb.place(x=12, y=6)
    _tk_aegis_star(emb, 23, 23, 20, P)
    tk.Label(header, text="Novadomus Health Service", bg=TEALD, fg=GOLD,
             font=("Helvetica", 15, "bold")).place(x=68, y=8)
    tk.Label(header, text="Provider Registry \u2014 Practitioner Identification", bg=TEALD,
             fg=P["t_soft"], font=("Helvetica", 9)).place(x=70, y=32)
    stat = tk.Label(header, text="", bg=TEALD, fg=P["t_light"], font=("Helvetica", 9))
    stat.place(relx=1.0, x=-14, y=20, anchor="ne")

    body = tk.Frame(root, bg=PAPER)
    body.pack(fill="both", expand=True, padx=12, pady=10)

    # ---- form (left) ----
    form = tk.LabelFrame(body, text=" Provider ", bg=PAPER, fg=TEALD,
                         font=("Helvetica", 10, "bold"), padx=12, pady=8)
    form.pack(side="left", fill="y")
    form.columnconfigure(1, weight=1)

    f = {}
    selected = {"id": None, "photo": None}
    r = 0

    def row(label, widget, note=None):
        nonlocal r
        ttk.Label(form, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
        widget.grid(row=r, column=1, sticky="ew", pady=3)
        r += 1
        if note:
            ttk.Label(form, text=note, foreground="#6a7f80",
                      font=("Helvetica", 7)).grid(row=r, column=1, sticky="w")
            r += 1

    f["full_name"] = ttk.Entry(form, width=34)
    row("Full name", f["full_name"])
    f["role"] = ttk.Combobox(form, values=ROLES, state="readonly", width=32)
    f["role"].current(0)
    row("Role", f["role"])
    f["specialty"] = ttk.Entry(form, width=34)
    row("Specialty", f["specialty"])
    f["licence_class"] = ttk.Combobox(form, values=LICENCE_CLASSES, state="readonly", width=32)
    f["licence_class"].current(0)
    row("Licence class", f["licence_class"], "Protected \u2014 QR only")

    # affiliations
    ttk.Label(form, text="Affiliations").grid(row=r, column=0, sticky="nw", pady=3)
    aff_box = tk.Listbox(form, selectmode="multiple", height=5, width=32,
                         exportselection=False)
    aff_box.grid(row=r, column=1, sticky="ew", pady=3)
    r += 1
    ttk.Label(form, text="Select one or more; the first is the badge facility.",
              foreground="#6a7f80", font=("Helvetica", 7)).grid(row=r, column=1, sticky="w")
    r += 1

    # authority block
    auth = tk.LabelFrame(form, text=" Authority \u2014 QR only ", bg=PAPER, fg=TEALD,
                         font=("Helvetica", 8, "bold"), padx=8, pady=6)
    auth.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(10, 4))
    r += 1
    presc = tk.IntVar(value=0)
    ctrl = tk.IntVar(value=0)
    cb_p = ttk.Checkbutton(auth, text="May prescribe", variable=presc)
    cb_p.grid(row=0, column=0, sticky="w")
    cb_c = ttk.Checkbutton(auth, text="May prescribe controlled substances", variable=ctrl)
    cb_c.grid(row=1, column=0, sticky="w")
    gate_lbl = ttk.Label(auth, text="", foreground="#8a5a00", font=("Helvetica", 7))
    gate_lbl.grid(row=2, column=0, sticky="w", pady=(4, 0))

    def apply_role_gate(*_a):
        """Grey out authority the selected role can never hold."""
        role = f["role"].get()
        if role in PRESCRIBER_ROLES:
            cb_p.state(["!disabled"])
        else:
            presc.set(0)
            cb_p.state(["disabled"])
        if role in CONTROLLED_ROLES:
            cb_c.state(["!disabled"])
        else:
            ctrl.set(0)
            cb_c.state(["disabled"])
        notes = []
        if role not in PRESCRIBER_ROLES:
            notes.append(f"{role}s cannot prescribe.")
        elif role not in CONTROLLED_ROLES:
            notes.append(f"{role}s cannot prescribe controlled substances.")
        gate_lbl.config(text=" ".join(notes))

    f["role"].bind("<<ComboboxSelected>>", apply_role_gate)

    def on_ctrl(*_a):
        if ctrl.get():
            presc.set(1)
    ctrl.trace_add("write", on_ctrl)

    # photo
    photo_lbl = ttk.Label(form, text="No photo selected", foreground="#6a7f80",
                          font=("Helvetica", 8))

    def pick_photo():
        p = filedialog.askopenfilename(
            title="Choose a badge photo",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif"), ("All files", "*.*")])
        if p:
            selected["photo"] = p
            photo_lbl.config(text=os.path.basename(p))

    def clear_photo():
        selected["photo"] = None
        photo_lbl.config(text="No photo selected")

    prow = tk.Frame(form, bg=PAPER)
    prow.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(6, 2))
    r += 1
    ttk.Button(prow, text="Choose photo\u2026", command=pick_photo).pack(side="left")
    ttk.Button(prow, text="Clear", command=clear_photo).pack(side="left", padx=6)
    photo_lbl.grid(row=r, column=0, columnspan=2, sticky="w")
    r += 1

    def read_form():
        name = f["full_name"].get().strip()
        if not name:
            messagebox.showwarning("Missing", "Full name is required.")
            return None
        sel = [aff_ids[i] for i in aff_box.curselection()] if aff_ids else []
        return {
            "full_name": name,
            "role": f["role"].get(),
            "specialty": f["specialty"].get().strip(),
            "licence_class": f["licence_class"].get(),
            "prescribing": presc.get(),
            "controlled": ctrl.get(),
            "affiliations": sel,
        }

    def clear_form():
        selected["id"] = None
        f["full_name"].delete(0, "end")
        f["specialty"].delete(0, "end")
        f["role"].current(0)
        f["licence_class"].current(0)
        presc.set(0)
        ctrl.set(0)
        aff_box.selection_clear(0, "end")
        clear_photo()
        apply_role_gate()
        sel_lbl.config(text="New provider")

    def load_into_form(prov):
        clear_form()
        selected["id"] = prov["id"]
        f["full_name"].insert(0, prov.get("full_name") or "")
        f["role"].set(prov.get("role") or ROLES[0])
        f["specialty"].insert(0, prov.get("specialty") or "")
        lic = get_licence(conn, prov["id"])
        f["licence_class"].set(lic.get("licence_class") or LICENCE_CLASSES[0])
        apply_role_gate()
        presc.set(1 if prov.get("prescribing_authority") else 0)
        ctrl.set(1 if prov.get("controlled_authority") else 0)
        have = {fid for fid, _ in get_affiliations(conn, prov["id"])}
        for i, fid in enumerate(aff_ids):
            if fid in have:
                aff_box.selection_set(i)
        sel_lbl.config(text=f"Editing {prov['id']}")

    # ---- buttons ----
    btns = tk.Frame(form, bg=PAPER)
    btns.grid(row=r, column=0, columnspan=2, pady=(10, 4), sticky="ew")
    r += 1

    def do_save():
        d = read_form()
        if not d:
            return
        p, c = normalise_authority(d["role"], d["prescribing"], d["controlled"])
        if (d["prescribing"] and not p) or (d["controlled"] and not c):
            messagebox.showinfo(
                "Authority adjusted",
                f"A {d['role']} cannot hold that authority, so it was not granted.")
        if selected["id"]:
            update_provider(conn, selected["id"], d)
            pid = selected["id"]
        else:
            pid = add_provider(conn, d)
        refresh()
        clear_form()
        messagebox.showinfo("Saved", f"Provider saved as {pid}.")

    def do_badge():
        if not selected["id"]:
            messagebox.showinfo("Select", "Select a provider from the list first.")
            return
        prov = get_provider(conn, selected["id"])
        try:
            color, bw = generate_badge(conn, prov, selected["photo"])
        except AssertionError as e:
            messagebox.showerror("Privacy check failed", f"{e}\n\nThe badge was not printed.")
            return
        _open_path(color)
        messagebox.showinfo(
            "Provider badge",
            "Saved to the 'badges' folder:\n\n"
            f"{os.path.basename(color)}\n{os.path.basename(bw)}\n\n"
            "Licence class and prescribing authority are in the QR only.")

    def do_delete():
        if not selected["id"]:
            return
        if messagebox.askyesno("Delete", f"Delete {selected['id']} permanently?"):
            delete_provider(conn, selected["id"])
            refresh()
            clear_form()

    ttk.Button(btns, text="Save", style="Accent.TButton", command=do_save).pack(side="left")
    ttk.Button(btns, text="New", command=clear_form).pack(side="left", padx=6)
    ttk.Button(btns, text="Print badge", command=do_badge).pack(side="left")
    ttk.Button(btns, text="Delete", command=do_delete).pack(side="left", padx=6)

    sel_lbl = ttk.Label(form, text="New provider", foreground=TEALD,
                        font=("Helvetica", 9, "italic"))
    sel_lbl.grid(row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))

    # ---- list (right) ----
    right = tk.Frame(body, bg=PAPER)
    right.pack(side="left", fill="both", expand=True, padx=(14, 0))

    searchbar = tk.Frame(right, bg=PAPER)
    searchbar.pack(fill="x", pady=(0, 6))
    ttk.Label(searchbar, text="Search").pack(side="left", padx=(0, 6))
    sv = tk.StringVar()
    ttk.Entry(searchbar, textvariable=sv, width=28).pack(side="left")
    ttk.Button(searchbar, text="Find", command=lambda: refresh(sv.get())).pack(side="left", padx=6)
    ttk.Button(searchbar, text="All", command=lambda: (sv.set(""), refresh())).pack(side="left")

    cols = ("id", "name", "role", "specialty", "rx", "expires")
    tree = ttk.Treeview(right, columns=cols, show="headings", selectmode="browse")
    for c, w, txt in [("id", 85, "Provider ID"), ("name", 165, "Name"), ("role", 95, "Role"),
                      ("specialty", 125, "Specialty"), ("rx", 60, "Rx"),
                      ("expires", 90, "Expires")]:
        tree.heading(c, text=txt)
        tree.column(c, width=w, anchor="w")
    tree.pack(side="left", fill="both", expand=True)
    sb = ttk.Scrollbar(right, orient="vertical", command=tree.yview)
    sb.pack(side="left", fill="y")
    tree.configure(yscrollcommand=sb.set)

    def on_select(_e):
        item = tree.focus()
        if item:
            prov = get_provider(conn, item)
            if prov:
                load_into_form(prov)

    tree.bind("<<TreeviewSelect>>", on_select)

    aff_ids = []

    def reload_facilities():
        nonlocal aff_ids
        choices = facility_choices(conn)
        aff_ids = [fid for fid, _ in choices]
        aff_box.delete(0, "end")
        for fid, name in choices:
            aff_box.insert("end", f"{fid} \u2014 {name}")

    def refresh(search=None):
        reload_facilities()
        tree.delete(*tree.get_children())
        for prov in list_providers(conn, search):
            rx = "\u2014"
            if prov.get("prescribing_authority"):
                rx = "Rx+C" if prov.get("controlled_authority") else "Rx"
            tree.insert("", "end", iid=prov["id"], values=(
                prov["id"], prov["full_name"], prov.get("role") or "",
                prov.get("specialty") or "", rx, prov.get("expires_on") or ""))
        total, expiring, prescribers = counts(conn)
        stat.config(text=f"{total} providers    Expiring \u2264 90d: {expiring}    "
                         f"Prescribers: {prescribers}")

    apply_role_gate()
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
