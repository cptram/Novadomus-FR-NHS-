"""
facility_registry.py  —  Novadomus Health Service, Phase 1: Facility Registry

Registers clinics, hospitals, urgent care, labs, and pharmacies under the
Novadomus Health Authority. Mints NVF-#### IDs, writes to the shared health
database, and prints registration credentials (colour + line-art B&W) true-size
on a Letter page with crop marks.

Depends only on:  nova_health.py  (same folder)  +  reportlab.
Run:  py facility_registry.py
"""

import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nova_health as nh

try:
    import novadomus_facility_sign as sign
except Exception:
    sign = None

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "novadomus_health.db")
CRED_DIR = os.path.join(APP_DIR, "credentials")
SIGN_DIR = os.path.join(APP_DIR, "signage")

REG_YEARS = 5  # facility registration term (adjustable)

# UI label  <->  database value
TYPE_DB = {"Clinic": "clinic", "Hospital": "hospital", "Urgent Care": "urgent_care",
           "Laboratory": "lab", "Pharmacy": "pharmacy"}
TYPE_LABEL = {v: k for k, v in TYPE_DB.items()}
FAC_TYPES = list(TYPE_DB.keys())
STATES = ["Ariesia", "Materra"]


# --------------------------------------------------------------------------
# Data layer (pure — no GUI, unit-testable)
# --------------------------------------------------------------------------
def _today():
    return datetime.date.today().isoformat()


def _plus_years(iso, years):
    d = datetime.date.fromisoformat(iso)
    try:
        return d.replace(year=d.year + years).isoformat()
    except ValueError:            # Feb 29 -> Feb 28
        return d.replace(year=d.year + years, day=28).isoformat()


def connect():
    return nh.init_db(DB_PATH)


def add_facility(conn, d):
    fid = nh.next_id(conn, "facility")
    reg = _today()
    exp = _plus_years(reg, REG_YEARS)
    vc = nh.verify_code("facility", fid)
    conn.execute(
        "INSERT INTO facilities (id, legal_name, facility_type, state, address, "
        "hours, bed_count, administrator, verify_code, status, registered_on, expires_on) "
        "VALUES (?,?,?,?,?,?,?,?,?,'active',?,?)",
        (fid, d["legal_name"], d["facility_type"], d["state"], d.get("address"),
         d.get("hours"), d.get("bed_count"), d.get("administrator"), vc, reg, exp))
    _replace_departments(conn, fid, d.get("departments", []))
    conn.commit()
    return fid


def update_facility(conn, fid, d):
    conn.execute(
        "UPDATE facilities SET legal_name=?, facility_type=?, state=?, address=?, "
        "hours=?, bed_count=?, administrator=? WHERE id=?",
        (d["legal_name"], d["facility_type"], d["state"], d.get("address"),
         d.get("hours"), d.get("bed_count"), d.get("administrator"), fid))
    _replace_departments(conn, fid, d.get("departments", []))
    conn.commit()


def _replace_departments(conn, fid, deps):
    conn.execute("DELETE FROM facility_departments WHERE facility_id=?", (fid,))
    for dep in deps:
        if dep and dep.strip():
            conn.execute("INSERT INTO facility_departments(facility_id, name) VALUES(?,?)",
                         (fid, dep.strip()))


def delete_facility(conn, fid):
    conn.execute("DELETE FROM facility_departments WHERE facility_id=?", (fid,))
    conn.execute("DELETE FROM facilities WHERE id=?", (fid,))
    conn.commit()


def _row_to_dict(conn, row):
    cols = [c[1] for c in conn.execute("PRAGMA table_info(facilities)")]
    return dict(zip(cols, row))


def list_facilities(conn):
    rows = conn.execute("SELECT * FROM facilities ORDER BY id").fetchall()
    return [_row_to_dict(conn, r) for r in rows]


def get_facility(conn, fid):
    r = conn.execute("SELECT * FROM facilities WHERE id=?", (fid,)).fetchone()
    return _row_to_dict(conn, r) if r else None


def get_departments(conn, fid):
    return [r[0] for r in conn.execute(
        "SELECT name FROM facility_departments WHERE facility_id=? ORDER BY id", (fid,))]


def counts(conn):
    out = {lbl: 0 for lbl in FAC_TYPES}
    for t, n in conn.execute("SELECT facility_type, COUNT(*) FROM facilities GROUP BY facility_type"):
        out[TYPE_LABEL.get(t, t)] = n
    total = conn.execute("SELECT COUNT(*) FROM facilities").fetchone()[0]
    soon = _today()
    horizon = _plus_years(soon, 0)
    horizon = (datetime.date.fromisoformat(soon) + datetime.timedelta(days=90)).isoformat()
    expiring = conn.execute(
        "SELECT COUNT(*) FROM facilities WHERE expires_on IS NOT NULL "
        "AND expires_on <= ? AND expires_on >= ?", (horizon, soon)).fetchone()[0]
    return out, total, expiring


# --------------------------------------------------------------------------
# Credential generation
# --------------------------------------------------------------------------
def facility_spec(fac):
    label = TYPE_LABEL.get(fac["facility_type"], fac["facility_type"]).title()
    return {
        "authority": "NOVADOMUS HEALTH SERVICE",
        "kind": "REGISTERED FACILITY",
        "title": fac["legal_name"],
        "subtitle": f"{label}  \u00b7  {fac.get('state', '')}",
        "id_code": fac["id"],
        "fields": [("Administrator", fac.get("administrator") or "\u2014"),
                   ("Registered", fac.get("registered_on") or "\u2014"),
                   ("Expires", fac.get("expires_on") or "\u2014")],
        "qr_payload": fac.get("verify_code") or nh.verify_code("facility", fac["id"]),
        "barcode": fac["id"],
    }


def generate_credentials(fac, out_dir=CRED_DIR):
    os.makedirs(out_dir, exist_ok=True)
    spec = facility_spec(fac)
    color = os.path.join(out_dir, f"{fac['id']}_facility_color.pdf")
    bw = os.path.join(out_dir, f"{fac['id']}_facility_bw.pdf")
    nh.render_credential_page(spec, nh.HEALTH_PALETTE, color)
    nh.render_credential_page(spec, nh.bw_palette(), bw)
    return color, bw


def _open_path(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)          # noqa: only exists on Windows
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
    TEAL, TEALD, GOLD, PAPER, INK = P["teal"], P["teal_deep"], P["gold"], P["paper"], P["ink"]

    conn = connect()

    root = tk.Tk()
    root.title("Novadomus Health \u2014 Facility Registry")
    root.geometry("980x620")
    root.configure(bg=PAPER)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("TLabel", background=PAPER, foreground=INK)
    style.configure("TButton", padding=6)
    style.configure("Accent.TButton", foreground="#ffffff")
    style.map("Accent.TButton", background=[("!disabled", TEAL), ("active", TEALD)])
    style.configure("Treeview", rowheight=24)
    style.configure("Treeview.Heading", font=("Helvetica", 9, "bold"))

    # header bar
    header = tk.Frame(root, bg=TEALD, height=58)
    header.pack(side="top", fill="x")
    tk.Canvas(header, width=44, height=44, bg=TEALD, highlightthickness=0).pack(
        side="left", padx=(14, 8), pady=7)  # placeholder for emblem area
    tk.Label(header, text="Novadomus Health Service", bg=TEALD, fg=GOLD,
             font=("Helvetica", 15, "bold")).place(x=64, y=8)
    tk.Label(header, text="Facility Registry", bg=TEALD, fg="#BFD6D2",
             font=("Helvetica", 9)).place(x=66, y=32)
    stat = tk.Label(header, text="", bg=TEALD, fg="#F4F1E6", font=("Helvetica", 9))
    stat.place(relx=1.0, x=-14, y=20, anchor="ne")

    body = tk.Frame(root, bg=PAPER)
    body.pack(fill="both", expand=True, padx=12, pady=10)

    # ---- form (left) ----
    form = tk.LabelFrame(body, text=" Facility ", bg=PAPER, fg=TEALD,
                         font=("Helvetica", 10, "bold"), padx=12, pady=10)
    form.pack(side="left", fill="y")

    fields = {}
    selected = {"id": None}

    def add_row(r, label, widget):
        ttk.Label(form, text=label).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 8))
        widget.grid(row=r, column=1, sticky="ew", pady=4)

    form.columnconfigure(1, weight=1)

    fields["legal_name"] = ttk.Entry(form, width=34)
    add_row(0, "Legal name", fields["legal_name"])

    fields["facility_type"] = ttk.Combobox(form, values=FAC_TYPES, state="readonly", width=32)
    fields["facility_type"].current(0)
    add_row(1, "Type", fields["facility_type"])

    fields["state"] = ttk.Combobox(form, values=STATES, state="readonly", width=32)
    fields["state"].current(0)
    add_row(2, "State", fields["state"])

    fields["address"] = ttk.Entry(form, width=34)
    add_row(3, "Address", fields["address"])

    fields["hours"] = ttk.Entry(form, width=34)
    add_row(4, "Hours", fields["hours"])

    fields["bed_count"] = ttk.Entry(form, width=34)
    add_row(5, "Bed count", fields["bed_count"])

    fields["administrator"] = ttk.Entry(form, width=34)
    add_row(6, "Administrator", fields["administrator"])

    fields["departments"] = ttk.Entry(form, width=34)
    add_row(7, "Departments", fields["departments"])
    ttk.Label(form, text="(comma-separated)", foreground="#6a7f80").grid(
        row=8, column=1, sticky="w")

    def read_form():
        name = fields["legal_name"].get().strip()
        if not name:
            messagebox.showwarning("Missing", "Legal name is required.")
            return None
        bc = fields["bed_count"].get().strip()
        try:
            bc_val = int(bc) if bc else None
        except ValueError:
            messagebox.showwarning("Invalid", "Bed count must be a whole number.")
            return None
        return {
            "legal_name": name,
            "facility_type": TYPE_DB[fields["facility_type"].get()],
            "state": fields["state"].get(),
            "address": fields["address"].get().strip(),
            "hours": fields["hours"].get().strip(),
            "bed_count": bc_val,
            "administrator": fields["administrator"].get().strip(),
            "departments": [x.strip() for x in fields["departments"].get().split(",") if x.strip()],
        }

    def clear_form():
        selected["id"] = None
        for k, w in fields.items():
            if isinstance(w, ttk.Combobox):
                w.current(0)
            else:
                w.delete(0, "end")
        sel_lbl.config(text="New facility")

    def load_into_form(fac):
        clear_form()
        selected["id"] = fac["id"]
        fields["legal_name"].insert(0, fac.get("legal_name") or "")
        fields["facility_type"].set(TYPE_LABEL.get(fac.get("facility_type"), FAC_TYPES[0]))
        fields["state"].set(fac.get("state") or STATES[0])
        fields["address"].insert(0, fac.get("address") or "")
        fields["hours"].insert(0, fac.get("hours") or "")
        fields["bed_count"].insert(0, "" if fac.get("bed_count") in (None, "") else str(fac["bed_count"]))
        fields["administrator"].insert(0, fac.get("administrator") or "")
        fields["departments"].insert(0, ", ".join(get_departments(conn, fac["id"])))
        sel_lbl.config(text=f"Editing {fac['id']}")

    # ---- action buttons ----
    btns = tk.Frame(form, bg=PAPER)
    btns.grid(row=9, column=0, columnspan=2, pady=(12, 4), sticky="ew")

    def do_register():
        d = read_form()
        if not d:
            return
        if selected["id"]:
            update_facility(conn, selected["id"], d)
            fid = selected["id"]
        else:
            fid = add_facility(conn, d)
        refresh()
        clear_form()
        messagebox.showinfo("Saved", f"Facility saved as {fid}.")

    def do_credential():
        if not selected["id"]:
            messagebox.showinfo("Select", "Select a facility from the list first.")
            return
        fac = get_facility(conn, selected["id"])
        color, bw = generate_credentials(fac)
        _open_path(color)
        messagebox.showinfo("Credential",
                            f"Saved to the 'credentials' folder:\n\n"
                            f"{os.path.basename(color)}\n{os.path.basename(bw)}")

    def do_signage():
        if not selected["id"]:
            messagebox.showinfo("Select", "Select a facility from the list first.")
            return
        if sign is None:
            messagebox.showwarning(
                "Missing file",
                "novadomus_facility_sign.py isn't in this folder, so signage "
                "can't be generated. Add it next to this app and try again.")
            return
        fac = get_facility(conn, selected["id"])
        files = sign.generate_signage(
            fac, SIGN_DIR, type_label=TYPE_LABEL.get(fac["facility_type"]))
        _open_path(SIGN_DIR)
        messagebox.showinfo(
            "Signage", f"Wrote {len(files)} sign PDFs to the 'signage' folder\n"
                       f"(board, plaque, oval, fascia \u00d7 colour + B&W).")

    def do_delete():
        if not selected["id"]:
            return
        if messagebox.askyesno("Delete", f"Delete {selected['id']} permanently?"):
            delete_facility(conn, selected["id"])
            refresh()
            clear_form()

    ttk.Button(btns, text="Save", style="Accent.TButton", command=do_register).pack(side="left")
    ttk.Button(btns, text="New", command=clear_form).pack(side="left", padx=6)
    ttk.Button(btns, text="Generate credential", command=do_credential).pack(side="left")
    ttk.Button(btns, text="Generate signage", command=do_signage).pack(side="left", padx=6)
    ttk.Button(btns, text="Delete", command=do_delete).pack(side="left")

    sel_lbl = ttk.Label(form, text="New facility", foreground=TEALD, font=("Helvetica", 9, "italic"))
    sel_lbl.grid(row=10, column=0, columnspan=2, sticky="w", pady=(6, 0))

    # ---- list (right) ----
    right = tk.Frame(body, bg=PAPER)
    right.pack(side="left", fill="both", expand=True, padx=(14, 0))

    cols = ("id", "name", "type", "state", "expires")
    tree = ttk.Treeview(right, columns=cols, show="headings", selectmode="browse")
    for c, w, txt in [("id", 80, "ID"), ("name", 220, "Legal name"),
                      ("type", 100, "Type"), ("state", 90, "State"), ("expires", 100, "Expires")]:
        tree.heading(c, text=txt)
        tree.column(c, width=w, anchor="w")
    tree.pack(side="left", fill="both", expand=True)
    sb = ttk.Scrollbar(right, orient="vertical", command=tree.yview)
    sb.pack(side="left", fill="y")
    tree.configure(yscrollcommand=sb.set)

    def on_select(_evt):
        item = tree.focus()
        if item:
            fac = get_facility(conn, item)
            if fac:
                load_into_form(fac)

    tree.bind("<<TreeviewSelect>>", on_select)

    def refresh():
        tree.delete(*tree.get_children())
        for fac in list_facilities(conn):
            tree.insert("", "end", iid=fac["id"], values=(
                fac["id"], fac["legal_name"],
                TYPE_LABEL.get(fac["facility_type"], fac["facility_type"]),
                fac.get("state", ""), fac.get("expires_on", "")))
        by_type, total, expiring = counts(conn)
        parts = "   ".join(f"{k}: {v}" for k, v in by_type.items() if v)
        stat.config(text=f"{total} facilities    {parts}    Expiring \u2264 90d: {expiring}")

    refresh()
    root.mainloop()


if __name__ == "__main__":
    main()
