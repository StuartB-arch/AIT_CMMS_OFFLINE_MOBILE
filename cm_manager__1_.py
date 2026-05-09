"""
CM Manager - Corrective Maintenance Tracking Application
Desktop application for recording and analyzing CMs with Pareto charts.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
import os
import sys
from datetime import datetime, date, time
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.gridspec as gridspec
import pandas as pd
import numpy as np

plt.rcParams['figure.max_open_warning'] = 0   # figures managed via self._figs

# ─── Database ──────────────────────────────────────────────────────────────────

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cm_manager.db")

def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS cms (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            date             TEXT,
            time             TEXT,
            andon            TEXT,
            event_id         TEXT,
            bfm_number       TEXT,
            station          TEXT,
            user             TEXT,
            criticality      TEXT,
            comments         TEXT,
            ack_date         TEXT,
            ack_time         TEXT,
            resolved_date    TEXT,
            resolve_time     TEXT,
            resolution_time  TEXT,
            root_cause       TEXT,
            notes            TEXT,
            created_at       TEXT DEFAULT (datetime('now'))
        )""")
        # Migrate existing databases
        cols = [r[1] for r in conn.execute("PRAGMA table_info(cms)").fetchall()]
        if "root_cause" not in cols:
            conn.execute("ALTER TABLE cms ADD COLUMN root_cause TEXT DEFAULT ''")
        if "bfm_number" not in cols:
            conn.execute("ALTER TABLE cms ADD COLUMN bfm_number TEXT DEFAULT ''")
        conn.commit()
    backfill_resolution_times()

def backfill_resolution_times():
    """Two jobs on startup:
    1. Convert any legacy 24-hour time values to 12-hour format.
    2. Recalculate resolution_time for records where it is blank/null
       but both report date and resolved date are present."""
    with get_conn() as conn:
        rows_all = conn.execute(
            "SELECT id, time, ack_time, resolve_time FROM cms"
        ).fetchall()

        # ── Pass 1: migrate 24h → 12h for all time columns ──────────────────
        migrated = 0
        for r in rows_all:
            updates = {}
            for col in ("time", "ack_time", "resolve_time"):
                raw = (r[col] or "").strip()
                if not raw:
                    continue
                # Already 12h if contains AM/PM
                if "AM" in raw.upper() or "PM" in raw.upper():
                    continue
                converted = _fmt_time_12h(raw)
                if converted and converted != raw:
                    updates[col] = converted
            if updates:
                set_clause = ", ".join(f"{k}=?" for k in updates)
                conn.execute(
                    f"UPDATE cms SET {set_clause} WHERE id=?",
                    (*updates.values(), r["id"]))
                migrated += 1

        if migrated:
            conn.commit()
            print(f"[migrate] Converted {migrated} records to 12-hour time format.")

        # ── Pass 2: backfill missing resolution_time ─────────────────────────
        rows = conn.execute("""
            SELECT id, date, time, resolved_date, resolve_time
            FROM cms
            WHERE (resolution_time IS NULL OR TRIM(resolution_time) = '')
              AND date          IS NOT NULL AND TRIM(date)          != ''
              AND resolved_date IS NOT NULL AND TRIM(resolved_date) != ''
        """).fetchall()
        updated = 0
        for r in rows:
            res_t = calc_resolution(
                r["date"],          r["time"]         or "12:00 AM",
                r["resolved_date"], r["resolve_time"] or "12:00 AM")
            if res_t:
                conn.execute("UPDATE cms SET resolution_time=? WHERE id=?",
                             (res_t, r["id"]))
                updated += 1
        conn.commit()
    if updated:
        print(f"[backfill] Updated resolution_time for {updated} records.")

# ─── Colours / Style ───────────────────────────────────────────────────────────

BG        = "#1e2130"
BG2       = "#252a3d"
BG3       = "#2e3450"
ACCENT    = "#4f8ef7"
ACCENT2   = "#f7a24f"
SUCCESS   = "#4fc87a"
DANGER    = "#f74f4f"
TEXT      = "#e8ecf4"
TEXT_DIM  = "#7e8ab0"
ENTRY_BG  = "#313856"
SEP       = "#3a4060"

FONT_TITLE  = ("Segoe UI", 16, "bold")
FONT_HEADER = ("Segoe UI", 11, "bold")
FONT_BODY   = ("Segoe UI", 10)
FONT_SMALL  = ("Segoe UI", 9)

ANDON_COLORS = {"Low": "#4fc87a", "Medium": "#f7a24f", "High": "#f74f4f"}
CRIT_COLORS  = {"P1": "#f74f4f", "P2": "#f7934f", "P3": "#f7d04f", "P4": "#4fc87a"}

MONTHS = ["January","February","March","April","May","June",
          "July","August","September","October","November","December"]

# ─── Helpers ───────────────────────────────────────────────────────────────────

def now_date(): return datetime.now().strftime("%Y-%m-%d")
def now_time(): return datetime.now().strftime("%I:%M %p")   # e.g. "02:30 PM"

def _parse_date(raw):
    """Return 'YYYY-MM-DD' string or '' on failure."""
    if raw is None:
        return ""
    s = str(raw).strip()
    if s.lower() in ("", "nan", "none", "nat"):
        return ""
    try:
        return pd.to_datetime(s, errors="coerce", dayfirst=False).strftime("%Y-%m-%d")
    except Exception:
        return ""

def _parse_time(raw):
    """Internal helper — always returns 24-hour 'HH:MM' string or ''.
    Accepts: '2:30 PM', '14:30', '02:30:00', '2:30:00 PM', Excel fractions (0.5)."""
    if raw is None:
        return ""
    s = str(raw).strip()
    if s.lower() in ("", "nan", "none", "nat"):
        return ""

    # Excel day-fraction (0.0–1.0)
    try:
        f = float(s)
        if 0.0 <= f < 1.0:
            total_min = int(round(f * 1440))
            return f"{total_min // 60:02d}:{total_min % 60:02d}"
    except ValueError:
        pass

    # Strip seconds suffix so '2:30:00 PM' → '2:30 PM' before AM/PM check
    import re as _re
    s_clean = _re.sub(r':\d{2}(\s)', r'\1', s)   # HH:MM:SS AM → HH:MM AM
    s_clean = _re.sub(r':\d{2}$', '', s_clean)   # HH:MM:SS   → HH:MM

    # 12-hour with AM/PM  — '2:30 PM', '12:00 AM', '11:59 PM'
    m12 = _re.match(r'^(\d{1,2}):(\d{2})\s*(AM|PM)$', s_clean.strip(), _re.IGNORECASE)
    if m12:
        h, mn, period = int(m12.group(1)), int(m12.group(2)), m12.group(3).upper()
        if period == "AM":
            h = 0 if h == 12 else h
        else:
            h = 12 if h == 12 else h + 12
        return f"{h:02d}:{mn:02d}"

    # Plain HH:MM or H:MM  (24-hour)
    m24 = _re.match(r'^(\d{1,2}):(\d{2})$', s_clean.strip())
    if m24:
        return f"{int(m24.group(1)):02d}:{int(m24.group(2)):02d}"

    # Last resort — pandas
    try:
        t = pd.to_datetime(s, errors="coerce")
        if pd.notna(t):
            return t.strftime("%H:%M")
    except Exception:
        pass
    return ""

def _fmt_time_12h(raw):
    """Display helper — converts any stored time value to '12:30 PM' format.
    Returns '' if the value cannot be parsed."""
    t24 = _parse_time(raw)
    if not t24:
        return ""
    try:
        h, m = map(int, t24.split(":"))
        period = "AM" if h < 12 else "PM"
        h12    = h % 12 or 12
        return f"{h12}:{m:02d} {period}"
    except Exception:
        return raw  # fall back to raw string rather than blank

def calc_resolution(report_date, report_time, resolved_date, resolved_time):
    """Calculate TTR (Time To Resolve): reported datetime → resolved datetime.
    Returns 'HH:MM' string, or '' when data is missing or invalid."""
    try:
        d1 = _parse_date(report_date)
        d2 = _parse_date(resolved_date)
        if not d1 or not d2:
            return ""
        t1 = _parse_time(report_time) or "00:00"
        t2 = _parse_time(resolved_time) or "00:00"
        start = datetime.strptime(f"{d1} {t1}", "%Y-%m-%d %H:%M")
        end   = datetime.strptime(f"{d2} {t2}", "%Y-%m-%d %H:%M")
        if end < start:
            return ""
        h, rem = divmod(int((end - start).total_seconds()), 3600)
        m = rem // 60
        return f"{h:02d}:{m:02d}"
    except Exception:
        return ""

def styled_entry(parent, width=22, **kw):
    e = tk.Entry(parent, width=width, bg=ENTRY_BG, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 font=FONT_BODY, highlightthickness=1,
                 highlightbackground=SEP, highlightcolor=ACCENT, **kw)
    return e

def styled_combo(parent, values, width=20):
    cb = ttk.Combobox(parent, values=values, width=width,
                      font=FONT_BODY, state="readonly")
    return cb

def label(parent, text, font=FONT_BODY, fg=TEXT_DIM, **kw):
    return tk.Label(parent, text=text, bg=BG2, fg=fg, font=font, **kw)

def section_frame(parent, title=""):
    outer = tk.Frame(parent, bg=BG3, bd=0, highlightthickness=1,
                     highlightbackground=SEP)
    if title:
        tk.Label(outer, text=title, bg=BG3, fg=ACCENT, font=FONT_HEADER,
                 padx=10, pady=6).pack(anchor="w")
        ttk.Separator(outer, orient="horizontal").pack(fill="x", padx=8)
    inner = tk.Frame(outer, bg=BG3)
    inner.pack(fill="both", expand=True, padx=10, pady=8)
    return outer, inner

# ─── Entry Form ────────────────────────────────────────────────────────────────

class EntryForm(tk.Frame):
    def __init__(self, master, on_save_cb):
        super().__init__(master, bg=BG2)
        self.on_save_cb = on_save_cb
        self._build()

    def _build(self):
        # ── Header
        hdr = tk.Frame(self, bg=BG2)
        hdr.pack(fill="x", padx=20, pady=(16,8))
        tk.Label(hdr, text="➕  New CM Entry", bg=BG2, fg=TEXT,
                 font=FONT_TITLE).pack(side="left")
        tk.Button(hdr, text="  ✕ Clear Form  ", bg=BG3, fg=TEXT_DIM,
                  font=FONT_SMALL, relief="flat", cursor="hand2",
                  command=self._clear).pack(side="right", padx=4)

        # ── Scroll canvas
        canvas = tk.Canvas(self, bg=BG2, highlightthickness=0)
        scroll = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = tk.Frame(canvas, bg=BG2)
        win_id = canvas.create_window((0,0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(
            win_id, width=e.width))
        canvas.bind_all("<MouseWheel>",
            lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))

        pad = {"padx": 20, "pady": 6}

        # ── Incident info
        sec_o, sec = section_frame(body, "📋  Incident Information")
        sec_o.pack(fill="x", **pad)

        r = tk.Frame(sec, bg=BG3); r.pack(fill="x", pady=3)
        self._field(r, "Date *", 0); self._field(r, "Time *", 1)
        self._field(r, "Andon Level *", 2); self._field(r, "Criticality *", 3)

        r2 = tk.Frame(sec, bg=BG3); r2.pack(fill="x", pady=3)
        self._field(r2, "Event ID", 0); self._field(r2, "Station / Equipment *", 1)
        self._field(r2, "User / Reporter *", 2); self._field(r2, "BFM Number", 3)

        r3 = tk.Frame(sec, bg=BG3); r3.pack(fill="x", pady=3)
        label(r3, "Comments *", fg=TEXT_DIM).grid(row=0, column=0, sticky="nw", padx=(0,6))
        self.vars["Comments *"] = tk.Text(r3, height=3, width=80,
            bg=ENTRY_BG, fg=TEXT, insertbackground=TEXT, relief="flat",
            font=FONT_BODY, wrap="word",
            highlightthickness=1, highlightbackground=SEP,
            highlightcolor=ACCENT)
        self.vars["Comments *"].grid(row=1, column=0, sticky="ew")

        # ── Resolution info
        sec2_o, sec2 = section_frame(body, "✅  Resolution Information")
        sec2_o.pack(fill="x", **pad)

        r4 = tk.Frame(sec2, bg=BG3); r4.pack(fill="x", pady=3)
        self._field(r4, "Acknowledge Date", 0); self._field(r4, "Acknowledge Time", 1)
        self._field(r4, "Resolved Date", 2);    self._field(r4, "Resolve Time", 3)

        # ── Root cause
        r4b = tk.Frame(sec2, bg=BG3); r4b.pack(fill="x", pady=3)
        rc_frm = tk.Frame(r4b, bg=BG3)
        rc_frm.grid(row=0, column=0, sticky="nw")
        label(rc_frm, "Root Cause", fg=TEXT_DIM).pack(anchor="w")
        RC_OPTIONS = ["", "Electrical", "Mechanical", "Hydraulic", "Pneumatic"]
        self.vars["Root Cause"] = styled_combo(rc_frm, RC_OPTIONS, width=18)
        self.vars["Root Cause"].pack()

        r5 = tk.Frame(sec2, bg=BG3); r5.pack(fill="x", pady=3)
        label(r5, "Notes", fg=TEXT_DIM).grid(row=0, column=0, sticky="nw", padx=(0,6))
        self.vars["Notes"] = tk.Text(r5, height=2, width=80,
            bg=ENTRY_BG, fg=TEXT, insertbackground=TEXT, relief="flat",
            font=FONT_BODY, wrap="word",
            highlightthickness=1, highlightbackground=SEP,
            highlightcolor=ACCENT)
        self.vars["Notes"].grid(row=1, column=0, sticky="ew")

        # ── Auto-fill now buttons
        af = tk.Frame(sec2, bg=BG3); af.pack(fill="x", pady=4)
        for txt, cb in [
            ("⏱ Set Acknowledge = Now", self._ack_now),
            ("⏱ Set Resolve = Now",     self._resolve_now),
        ]:
            tk.Button(af, text=txt, bg=ACCENT, fg="white", relief="flat",
                      font=FONT_SMALL, cursor="hand2", command=cb,
                      padx=8, pady=4).pack(side="left", padx=4)

        # ── Save button
        btn_row = tk.Frame(body, bg=BG2)
        btn_row.pack(fill="x", pady=(8,20), padx=20)
        tk.Button(btn_row, text="  💾  SAVE CM RECORD  ", bg=SUCCESS, fg="white",
                  font=("Segoe UI", 12, "bold"), relief="flat", cursor="hand2",
                  padx=16, pady=10, command=self._save).pack(side="right")

    def _field(self, parent, name, col):
        if not hasattr(self, "vars"):
            self.vars = {}
        frm = tk.Frame(parent, bg=BG3)
        frm.grid(row=0, column=col, padx=(0,12), sticky="nw")
        label(frm, name, fg=TEXT_DIM).pack(anchor="w")
        if name == "Andon Level *":
            w = styled_combo(frm, ["Low","Medium","High"], width=14)
            w.pack()
        elif name == "Criticality *":
            w = styled_combo(frm, ["P1","P2","P3","P4"], width=8)
            w.pack()
        else:
            w = styled_entry(frm, width=18)
            if "Date" in name: w.insert(0, now_date())
            if name in ("Time *", "Acknowledge Time", "Resolve Time"):
                w.insert(0, now_time())
            w.pack()
        self.vars[name] = w

    def _v(self, key):
        w = self.vars[key]
        if isinstance(w, tk.Text):
            return w.get("1.0","end-1c").strip()
        return w.get().strip()

    def _ack_now(self):
        self.vars["Acknowledge Date"].delete(0,"end")
        self.vars["Acknowledge Date"].insert(0, now_date())
        self.vars["Acknowledge Time"].delete(0,"end")
        self.vars["Acknowledge Time"].insert(0, now_time())

    def _resolve_now(self):
        self.vars["Resolved Date"].delete(0,"end")
        self.vars["Resolved Date"].insert(0, now_date())
        self.vars["Resolve Time"].delete(0,"end")
        self.vars["Resolve Time"].insert(0, now_time())

    def _clear(self):
        for k, w in self.vars.items():
            if isinstance(w, tk.Text):
                w.delete("1.0","end")
            elif isinstance(w, ttk.Combobox):
                w.set("")
            else:
                w.delete(0,"end")
                if "Date" in k: w.insert(0, now_date())
                if k in ("Time *",): w.insert(0, now_time())

    def _save(self):
        req = ["Date *","Time *","Andon Level *","Criticality *",
               "Station / Equipment *","User / Reporter *","Comments *"]
        for r in req:
            if not self._v(r):
                messagebox.showwarning("Missing Field",
                    f"Please fill in: {r.rstrip(' *')}")
                return
        # TTR = time from initial report to resolution (not ack→resolved)
        res_t = calc_resolution(
            self._v("Date *"),    self._v("Time *"),
            self._v("Resolved Date"), self._v("Resolve Time"))
        with get_conn() as conn:
            conn.execute("""
            INSERT INTO cms
            (date,time,andon,event_id,bfm_number,station,user,criticality,comments,
             ack_date,ack_time,resolved_date,resolve_time,resolution_time,root_cause,notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (self._v("Date *"), self._v("Time *"), self._v("Andon Level *"),
             self._v("Event ID"), self._v("BFM Number"),
             self._v("Station / Equipment *"),
             self._v("User / Reporter *"), self._v("Criticality *"),
             self._v("Comments *"), self._v("Acknowledge Date"),
             self._v("Acknowledge Time"), self._v("Resolved Date"),
             self._v("Resolve Time"), res_t,
             self._v("Root Cause"), self._v("Notes")))
            conn.commit()
        messagebox.showinfo("Saved", "✅ CM record saved successfully!")
        self._clear()
        self.on_save_cb()

# ─── Records Table ─────────────────────────────────────────────────────────────

COLS = ("Date","Time","Andon","Event ID","BFM #","Station","User",
        "Priority","Root Cause","Comments","Ack Date","Ack Time",
        "Resolved Date","Resolve Time","Res. Time","Notes")

COL_W = [85,75,65,95,90,90,120,55,90,280,85,75,90,85,65,160]

class RecordsView(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=BG2)
        self._edit_id = None
        self._build()
        self.load()

    def _build(self):
        # ── Toolbar
        bar = tk.Frame(self, bg=BG2)
        bar.pack(fill="x", padx=16, pady=(12,6))
        tk.Label(bar, text="📋  CM Records", bg=BG2, fg=TEXT,
                 font=FONT_TITLE).pack(side="left")

        # Search
        sf = tk.Frame(bar, bg=BG2); sf.pack(side="left", padx=20)
        tk.Label(sf, text="🔍", bg=BG2, fg=TEXT_DIM, font=FONT_BODY).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.load())
        se = tk.Entry(sf, textvariable=self.search_var, bg=ENTRY_BG, fg=TEXT,
                      insertbackground=TEXT, relief="flat", font=FONT_BODY,
                      width=24, highlightthickness=1,
                      highlightbackground=SEP, highlightcolor=ACCENT)
        se.pack(side="left", padx=4)

        # Month filter
        tk.Label(bar, text="Month:", bg=BG2, fg=TEXT_DIM, font=FONT_BODY).pack(side="left")
        self.month_var = tk.StringVar(value="All")
        mc = ttk.Combobox(bar, textvariable=self.month_var,
                          values=["All"]+MONTHS, width=11,
                          font=FONT_BODY, state="readonly")
        mc.pack(side="left", padx=4)
        mc.bind("<<ComboboxSelected>>", lambda _: self.load())

        # Year filter
        tk.Label(bar, text="Year:", bg=BG2, fg=TEXT_DIM, font=FONT_BODY).pack(side="left")
        years = [str(y) for y in range(2024, datetime.now().year+2)]
        self.year_var = tk.StringVar(value=str(datetime.now().year))
        yc = ttk.Combobox(bar, textvariable=self.year_var,
                          values=["All"]+years, width=7,
                          font=FONT_BODY, state="readonly")
        yc.pack(side="left", padx=4)
        yc.bind("<<ComboboxSelected>>", lambda _: self.load())

        for txt, cmd, col in [
            ("✏ Edit",   self._edit,   ACCENT),
            ("🗑 Delete", self._delete, DANGER),
            ("📤 Export", self._export, ACCENT2),
        ]:
            tk.Button(bar, text=txt, bg=col, fg="white", relief="flat",
                      font=FONT_SMALL, cursor="hand2",
                      command=cmd, padx=8, pady=4).pack(side="right", padx=3)

        # ── Priority + Station filter row
        pbar = tk.Frame(self, bg=BG2)
        pbar.pack(fill="x", padx=16, pady=(0, 4))

        # Priority toggles
        tk.Label(pbar, text="Priority:", bg=BG2, fg=TEXT_DIM,
                 font=FONT_BODY).pack(side="left", padx=(0, 6))

        self.prio_var = tk.StringVar(value="All")
        self._prio_btns = {}
        PRIO_BTN_DEFS = [
            ("All", TEXT_DIM, BG3),
            ("P1",  CRIT_COLORS["P1"], "#3d1212"),
            ("P2",  CRIT_COLORS["P2"], "#3d2210"),
            ("P3",  CRIT_COLORS["P3"], "#3d3010"),
            ("P4",  CRIT_COLORS["P4"], "#1a3328"),
        ]
        for label_txt, active_fg, active_bg in PRIO_BTN_DEFS:
            btn = tk.Button(
                pbar, text=label_txt,
                bg=ACCENT if label_txt == "All" else BG3,
                fg="white" if label_txt == "All" else TEXT_DIM,
                relief="flat", font=("Segoe UI", 9, "bold"),
                cursor="hand2", padx=12, pady=3,
                command=lambda v=label_txt,
                               afg=active_fg,
                               abg=active_bg: self._set_prio(v, afg, abg))
            btn.pack(side="left", padx=3)
            self._prio_btns[label_txt] = (btn, active_fg, active_bg)

        # Divider
        ttk.Separator(pbar, orient="vertical").pack(side="left", fill="y",
                                                    padx=14, pady=2)

        # Station filter
        tk.Label(pbar, text="Station:", bg=BG2, fg=TEXT_DIM,
                 font=FONT_BODY).pack(side="left", padx=(0, 6))

        self.station_var = tk.StringVar(value="All")
        self.station_cb = ttk.Combobox(pbar, textvariable=self.station_var,
                                       values=["All"], width=22,
                                       font=FONT_BODY, state="readonly")
        self.station_cb.pack(side="left", padx=(0, 4))
        self.station_cb.bind("<<ComboboxSelected>>", lambda _: self.load())

        # Clear station button — only visible when a station is active
        self._clear_stn_btn = tk.Button(
            pbar, text="✕", bg=BG3, fg=TEXT_DIM,
            relief="flat", font=("Segoe UI", 8, "bold"),
            cursor="hand2", padx=6, pady=3,
            command=self._clear_station)
        self._clear_stn_btn.pack(side="left")
        self._clear_stn_btn.pack_forget()   # hidden until a station is chosen

        # ── Treeview
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("CM.Treeview",
            background=BG3, foreground=TEXT, fieldbackground=BG3,
            rowheight=24, font=FONT_SMALL)
        style.configure("CM.Treeview.Heading",
            background=BG, foreground=ACCENT, font=FONT_HEADER)
        style.map("CM.Treeview",
            background=[("selected", ACCENT)],
            foreground=[("selected","white")])

        tf = tk.Frame(self, bg=BG2)
        tf.pack(fill="both", expand=True, padx=16, pady=(4, 2))

        self.tree = ttk.Treeview(tf, columns=COLS, show="headings",
                                 style="CM.Treeview")
        for c, w in zip(COLS, COL_W):
            self.tree.heading(c, text=c, command=lambda _c=c: self._sort(_c))
            self.tree.column(c, width=w, minwidth=40)

        vsb = ttk.Scrollbar(tf, orient="vertical",   command=self.tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right",  fill="y")
        hsb.pack(side="bottom", fill="x")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _: self._edit())
        self._sort_col, self._sort_rev = None, False

        # ── Footer status bar (always visible below the table)
        footer = tk.Frame(self, bg=BG3, highlightthickness=1,
                          highlightbackground=SEP)
        footer.pack(fill="x", padx=16, pady=(0, 10))

        self.count_lbl = tk.Label(
            footer, text="", bg=BG3, fg=TEXT, font=("Segoe UI", 9, "bold"),
            anchor="w", padx=12, pady=5)
        self.count_lbl.pack(side="left")

        self.hours_lbl = tk.Label(
            footer, text="", bg=BG3, fg=ACCENT2, font=("Segoe UI", 9, "bold"),
            anchor="e", padx=12, pady=5)
        self.hours_lbl.pack(side="right")

    def _set_prio(self, value, active_fg, active_bg):
        self.prio_var.set(value)
        for lbl, (btn, afg, abg) in self._prio_btns.items():
            if lbl == value:
                btn.configure(bg=abg if lbl != "All" else ACCENT,
                               fg=afg if lbl != "All" else "white",
                               relief="solid",
                               highlightbackground=afg if lbl != "All" else ACCENT,
                               highlightthickness=1)
            else:
                btn.configure(bg=BG3, fg=TEXT_DIM,
                               relief="flat", highlightthickness=0)
        self.load()

    def _refresh_stations(self):
        """Rebuild the station dropdown from current DB contents."""
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT UPPER(TRIM(station)) AS s FROM cms "
                "WHERE station IS NOT NULL AND TRIM(station) != '' "
                "ORDER BY s"
            ).fetchall()
        stations = ["All"] + [r["s"] for r in rows]
        self.station_cb.configure(values=stations)
        # If the currently selected station no longer exists, reset to All
        if self.station_var.get() not in stations:
            self.station_var.set("All")

    def _clear_station(self):
        self.station_var.set("All")
        self._clear_stn_btn.pack_forget()
        self.load()

    def load(self):
        q = "SELECT * FROM cms WHERE 1=1"
        params = []
        s = self.search_var.get().strip()
        if s:
            q += """ AND (station LIKE ? OR user LIKE ? OR event_id LIKE ?
                         OR bfm_number LIKE ? OR comments LIKE ? OR notes LIKE ?)"""
            params += [f"%{s}%"]*6
        m = self.month_var.get()
        if m != "All":
            mi = str(MONTHS.index(m)+1).zfill(2)
            q += " AND strftime('%m', date) = ?"
            params.append(mi)
        y = self.year_var.get()
        if y != "All":
            q += " AND strftime('%Y', date) = ?"
            params.append(y)
        p = self.prio_var.get()
        if p != "All":
            q += " AND UPPER(criticality) = ?"
            params.append(p)
        st = self.station_var.get()
        if st != "All":
            q += " AND UPPER(TRIM(station)) = ?"
            params.append(st)
            self._clear_stn_btn.pack(side="left")
        else:
            self._clear_stn_btn.pack_forget()
        q += " ORDER BY date DESC, time DESC"

        for row in self.tree.get_children():
            self.tree.delete(row)

        with get_conn() as conn:
            rows = conn.execute(q, params).fetchall()

        for r in rows:
            vals = (r["date"] or "", _fmt_time_12h(r["time"]),
                    r["andon"] or "",
                    r["event_id"] or "", r["bfm_number"] or "",
                    r["station"] or "", r["user"] or "",
                    r["criticality"] or "", r["root_cause"] or "",
                    r["comments"] or "",
                    r["ack_date"] or "", _fmt_time_12h(r["ack_time"]),
                    r["resolved_date"] or "", _fmt_time_12h(r["resolve_time"]),
                    r["resolution_time"] or "", r["notes"] or "")
            tag = (r["andon"] or "").lower()
            self.tree.insert("", "end", iid=str(r["id"]),
                             values=vals, tags=(tag,))

        self.tree.tag_configure("low",    background="#1e3328")
        self.tree.tag_configure("medium", background="#3d3012")
        self.tree.tag_configure("high",   background="#3d1212")
        self.tree.tag_configure("mediun", background="#3d3012")

        # ── Footer summary ────────────────────────────────────────────────────
        parts = []
        if self.prio_var.get() != "All":
            parts.append(f"Priority: {self.prio_var.get()}")
        if self.station_var.get() != "All":
            parts.append(f"Station: {self.station_var.get()}")
        filter_suffix = ("  ·  " + "  ·  ".join(parts)) if parts else ""
        self.count_lbl.config(
            text=f"📋  {len(rows)} record{'s' if len(rows) != 1 else ''}{filter_suffix}")

        # Sum resolution_time (stored as HH:MM) for all visible resolved rows
        total_mins = 0
        resolved_count = 0
        for r in rows:
            rt = (r["resolution_time"] or "").strip()
            if rt and ":" in rt:
                try:
                    h, m = rt.split(":")[:2]
                    total_mins += int(h) * 60 + int(m)
                    resolved_count += 1
                except ValueError:
                    pass

        if resolved_count:
            total_h, total_m = divmod(total_mins, 60)
            self.hours_lbl.config(
                text=f"⏱  {total_h}h {total_m:02d}m total resolution time  "
                     f"({resolved_count} resolved  ·  "
                     f"avg {total_mins // resolved_count // 60}h "
                     f"{(total_mins // resolved_count) % 60:02d}m per CM)")
        else:
            self.hours_lbl.config(text="⏱  No resolved CMs in view")

        self._refresh_stations()

    def _sort(self, col):
        idx = list(COLS).index(col)
        data = [(self.tree.set(c, col), c) for c in self.tree.get_children("")]
        rev = (self._sort_col == col) and not self._sort_rev
        data.sort(reverse=rev)
        for i, (_, iid) in enumerate(data):
            self.tree.move(iid, "", i)
        self._sort_col, self._sort_rev = col, rev

    def _selected_id(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Select Row", "Please select a record first.")
            return None
        return int(sel[0])

    def _delete(self):
        rid = self._selected_id()
        if rid is None: return
        if not messagebox.askyesno("Confirm Delete",
                "Are you sure you want to delete this record?"):
            return
        with get_conn() as conn:
            conn.execute("DELETE FROM cms WHERE id=?", (rid,))
            conn.commit()
        self.load()

    def _edit(self):
        rid = self._selected_id()
        if rid is None: return
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM cms WHERE id=?", (rid,)).fetchone()
        if not row: return
        EditDialog(self, row, self.load)

    def _export(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel","*.xlsx"),("CSV","*.csv")],
            title="Export Records")
        if not path: return
        with get_conn() as conn:
            df = pd.read_sql("SELECT * FROM cms ORDER BY date,time", conn)
        df.columns = [c.replace("_"," ").title() for c in df.columns]
        if path.endswith(".csv"):
            df.to_csv(path, index=False)
        else:
            df.to_excel(path, index=False)
        messagebox.showinfo("Exported", f"Saved to:\n{path}")

# ─── Edit Dialog ───────────────────────────────────────────────────────────────

class EditDialog(tk.Toplevel):
    FIELDS = [
        ("date",          "Date"),
        ("time",          "Time"),
        ("andon",         "Andon Level"),
        ("event_id",      "Event ID"),
        ("bfm_number",    "BFM Number"),
        ("station",       "Station / Equipment"),
        ("user",          "User / Reporter"),
        ("criticality",   "Criticality"),
        ("comments",      "Comments"),
        ("ack_date",      "Acknowledge Date"),
        ("ack_time",      "Acknowledge Time"),
        ("resolved_date", "Resolved Date"),
        ("resolve_time",  "Resolve Time"),
        ("resolution_time","Resolution Time"),
        ("root_cause",     "Root Cause"),
        ("notes",         "Notes"),
    ]
    def __init__(self, master, row, on_save):
        super().__init__(master)
        self.title("Edit CM Record")
        self.configure(bg=BG2)
        self.geometry("680x560")
        self.on_save = on_save
        self._row = row
        self._widgets = {}
        self._build()

    def _build(self):
        tk.Label(self, text=f"Edit Record #{self._row['id']}",
                 bg=BG2, fg=TEXT, font=FONT_TITLE).pack(padx=16, pady=(12,6), anchor="w")

        canvas = tk.Canvas(self, bg=BG2, highlightthickness=0)
        scroll = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=BG2)
        wid = canvas.create_window((0,0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))

        for col, (key, lbl) in enumerate(self.FIELDS):
            r, c = divmod(col, 2)
            f = tk.Frame(body, bg=BG2)
            f.grid(row=r, column=c, padx=12, pady=4, sticky="nw")
            tk.Label(f, text=lbl, bg=BG2, fg=TEXT_DIM, font=FONT_SMALL).pack(anchor="w")
            val = self._row[key] or ""
            if key == "andon":
                w = styled_combo(f, ["Low","Medium","High"])
                w.set(val)
            elif key == "criticality":
                w = styled_combo(f, ["P1","P2","P3","P4"])
                w.set(val)
            elif key == "root_cause":
                w = styled_combo(f, ["","Electrical","Mechanical","Hydraulic","Pneumatic"])
                w.set(val)
            elif key in ("comments","notes"):
                w = tk.Text(f, height=3, width=30, bg=ENTRY_BG, fg=TEXT,
                            insertbackground=TEXT, relief="flat", font=FONT_BODY,
                            highlightthickness=1, highlightbackground=SEP)
                w.insert("1.0", val)
            else:
                w = styled_entry(f, width=22)
                w.insert(0, val)
            w.pack()
            self._widgets[key] = w

        btn_row = tk.Frame(body, bg=BG2)
        btn_row.grid(row=len(self.FIELDS)//2+1, column=0, columnspan=2,
                     pady=12, padx=12, sticky="e")
        tk.Button(btn_row, text="Cancel", bg=BG3, fg=TEXT_DIM, relief="flat",
                  font=FONT_BODY, cursor="hand2",
                  command=self.destroy, padx=8, pady=6).pack(side="left", padx=4)
        tk.Button(btn_row, text="  💾  Save Changes  ", bg=SUCCESS, fg="white",
                  relief="flat", font=FONT_BODY, cursor="hand2",
                  command=self._save, padx=8, pady=6).pack(side="left")

    def _get(self, key):
        w = self._widgets[key]
        if isinstance(w, tk.Text): return w.get("1.0","end-1c").strip()
        return w.get().strip()

    def _save(self):
        # TTR = time from initial report to resolution
        res_t = calc_resolution(
            self._get("date"), self._get("time"),
            self._get("resolved_date"), self._get("resolve_time"))
        with get_conn() as conn:
            conn.execute("""UPDATE cms SET
                date=?, time=?, andon=?, event_id=?, bfm_number=?, station=?, user=?,
                criticality=?, comments=?, ack_date=?, ack_time=?,
                resolved_date=?, resolve_time=?, resolution_time=?, root_cause=?, notes=?
                WHERE id=?""",
                (self._get("date"), self._get("time"), self._get("andon"),
                 self._get("event_id"), self._get("bfm_number"),
                 self._get("station"), self._get("user"),
                 self._get("criticality"), self._get("comments"),
                 self._get("ack_date"), self._get("ack_time"),
                 self._get("resolved_date"), self._get("resolve_time"),
                 res_t, self._get("root_cause"), self._get("notes"),
                 self._row["id"]))
            conn.commit()
        self.on_save()
        self.destroy()

# ─── Analytics / KPI Dashboard ─────────────────────────────────────────────────

def _parse_datetimes(df):
    """Add reported_dt, ack_dt, resolved_dt, response_hrs, ttr_hrs columns."""
    def _dt(date_col, time_col):
        out = []
        for _, row in df.iterrows():
            try:
                d = str(row[date_col]).strip()
                t = str(row[time_col]).strip()
                if not d or d in ("nan","None",""): out.append(pd.NaT); continue
                # Normalise to 24-hour HH:MM regardless of stored format
                t24 = _parse_time(t) or "00:00"
                out.append(pd.to_datetime(f"{d} {t24}",
                                          format="%Y-%m-%d %H:%M",
                                          errors="coerce"))
            except: out.append(pd.NaT)
        return out

    df = df.copy()
    df["reported_dt"] = _dt("date",          "time")
    df["ack_dt"]      = _dt("ack_date",       "ack_time")
    df["resolved_dt"] = _dt("resolved_date",  "resolve_time")
    df["response_hrs"] = (df["ack_dt"]      - df["reported_dt"]).dt.total_seconds() / 3600
    df["ttr_hrs"]      = (df["resolved_dt"] - df["reported_dt"]).dt.total_seconds() / 3600
    df["response_hrs"] = df["response_hrs"].clip(lower=0)
    df["ttr_hrs"]      = df["ttr_hrs"].clip(lower=0)
    df["criticality"]  = df["criticality"].str.strip().str.upper()
    df["station"]      = df["station"].str.strip().str.upper()
    df["andon"]        = df["andon"].str.strip().str.capitalize().replace({"Mediun":"Medium","HIGH":"High","High":"High"})
    return df

PLOT_BG = "#2e3450"
GRID_C  = "#3a4060"

def _style_ax(ax, title, xlabel="", ylabel=""):
    ax.set_facecolor(PLOT_BG)
    ax.set_title(title, color=TEXT, fontsize=10, pad=10, fontweight="bold")
    ax.tick_params(colors=TEXT_DIM, labelsize=8)
    for sp in ax.spines.values(): sp.set_edgecolor(GRID_C)
    if xlabel: ax.set_xlabel(xlabel, color=TEXT_DIM, fontsize=8)
    if ylabel: ax.set_ylabel(ylabel, color=TEXT_DIM, fontsize=8)
    ax.grid(axis="y", color=GRID_C, linewidth=0.5, alpha=0.6, zorder=0)

def _bar_labels(ax, bars, fmt="{:.1f}", color=TEXT, fontsize=7):
    for b in bars:
        h = b.get_height()
        if h > 0:
            ax.text(b.get_x() + b.get_width()/2, h + h*0.02 + 0.01,
                    fmt.format(h), ha="center", va="bottom",
                    fontsize=fontsize, color=color, fontweight="bold")

def _make_fig(nrows=1, ncols=2, figsize=(13,5)):
    plt.style.use("dark_background")
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize,
                             facecolor=BG2,
                             gridspec_kw={"hspace":0.52,"wspace":0.38})
    fig.patch.set_facecolor(BG2)
    if nrows == 1 and ncols == 1: axes = np.array([[axes]])
    elif nrows == 1 or ncols == 1: axes = np.array(axes).reshape(nrows, ncols)
    return fig, axes

PRIO_COLORS = {"P1":"#f74f4f","P2":"#f7934f","P3":"#f7d04f","P4":"#4fc87a"}

# ── Official KPI targets ────────────────────────────────────────────────────────
SLA_TTR      = {"P1": 2,      "P2": 4,    "P3": 10,   "P4": 24}   # hours
SLA_RESP     = {"P1": 0.25,   "P2": 1.0,  "P3": 3.0,  "P4": 4.0}  # hours (15min, 1h, 3h, 4h)
SLA_TTR_LBL  = {"P1": "<2 h", "P2": "<4 h","P3":"<10 h","P4":"<24 h"}
SLA_RESP_LBL = {"P1": "<15 min","P2":"<1 h","P3":"<3 h","P4":"<4 h"}
PRIO_ORDER  = ["P1","P2","P3","P4"]

class AnalyticsView(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=BG2)
        self._figs = {}
        self._build()

    def _build(self):
        # ── Top bar
        hdr = tk.Frame(self, bg=BG2)
        hdr.pack(fill="x", padx=16, pady=(12,0))
        tk.Label(hdr, text="KPI Analytics Dashboard",
                 bg=BG2, fg=TEXT, font=FONT_TITLE).pack(side="left")

        # Filters
        ff = tk.Frame(hdr, bg=BG2); ff.pack(side="left", padx=20)
        for lbl, attr, opts in [
            ("Month:", "month_var", ["All"]+MONTHS),
            ("Year:",  "year_var",  ["All"]+[str(y) for y in range(2024, datetime.now().year+2)]),
        ]:
            tk.Label(ff, text=lbl, bg=BG2, fg=TEXT_DIM, font=FONT_BODY).pack(side="left", padx=(10,2))
            v = tk.StringVar()
            setattr(self, attr, v)
            cb = ttk.Combobox(ff, textvariable=v, values=opts, width=11,
                              font=FONT_BODY, state="readonly")
            cb.pack(side="left")

        self.month_var.set("All")
        self.year_var.set(str(datetime.now().year))

        # Priority filter
        tk.Label(ff, text="Priority:", bg=BG2, fg=TEXT_DIM,
                 font=FONT_BODY).pack(side="left", padx=(14,2))
        self.analytics_prio_var = tk.StringVar(value="All")
        prio_cb = ttk.Combobox(ff, textvariable=self.analytics_prio_var,
                               values=["All","P1","P2","P3","P4"],
                               width=6, font=FONT_BODY, state="readonly")
        prio_cb.pack(side="left")

        # Station filter
        tk.Label(ff, text="Station:", bg=BG2, fg=TEXT_DIM,
                 font=FONT_BODY).pack(side="left", padx=(14,2))
        self.analytics_station_var = tk.StringVar(value="All")
        self.analytics_station_cb = ttk.Combobox(
            ff, textvariable=self.analytics_station_var,
            values=["All"], width=18, font=FONT_BODY, state="readonly")
        self.analytics_station_cb.pack(side="left")
        self._refresh_analytics_stations()

        tk.Button(hdr, text="  🔄 Refresh  ", bg=ACCENT, fg="white",
                  relief="flat", font=FONT_BODY, cursor="hand2",
                  padx=8, pady=5, command=self.render_all).pack(side="right", padx=4)
        tk.Button(hdr, text="  📥 Export PNG  ", bg=ACCENT2, fg="white",
                  relief="flat", font=FONT_SMALL, cursor="hand2",
                  padx=8, pady=5, command=self._export_all).pack(side="right", padx=4)

        # ── Tabs
        style = ttk.Style()
        style.configure("KPI.TNotebook",        background=BG,  borderwidth=0)
        style.configure("KPI.TNotebook.Tab",    background=BG3, foreground=TEXT_DIM,
                        font=FONT_BODY, padding=[12,6])
        style.map("KPI.TNotebook.Tab",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", "white")])

        self.nb = ttk.Notebook(self, style="KPI.TNotebook")
        self.nb.pack(fill="both", expand=True, padx=12, pady=8)

        self._tab_frames = {}
        for key, label in [
            ("ttr",       "Time to Repair"),
            ("mrt",       "Response Time"),
            ("wo_status", "WO Opened vs Closed"),
            ("age",       "WO Age Profile"),
            ("p1_pareto", "P1 Pareto"),
            ("recurring", "Recurring Disruptions"),
        ]:
            frm = tk.Frame(self.nb, bg=BG2)
            self.nb.add(frm, text=label)
            self._tab_frames[key] = frm
            tk.Label(frm, text="Click  🔄 Refresh  to load charts",
                     bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 13)).pack(expand=True)

    def _refresh_analytics_stations(self):
        """Populate the station dropdown from all stations in the DB."""
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT UPPER(TRIM(station)) AS s FROM cms "
                "WHERE station IS NOT NULL AND TRIM(station) != '' ORDER BY s"
            ).fetchall()
        stations = ["All"] + [r["s"] for r in rows]
        self.analytics_station_cb.configure(values=stations)
        if self.analytics_station_var.get() not in stations:
            self.analytics_station_var.set("All")

    def _get_data(self):
        q = "SELECT * FROM cms WHERE 1=1"
        params = []
        m = self.month_var.get()
        if m != "All":
            mi = str(MONTHS.index(m)+1).zfill(2)
            q += " AND strftime('%m', date) = ?"; params.append(mi)
        y = self.year_var.get()
        if y != "All":
            q += " AND strftime('%Y', date) = ?"; params.append(y)
        p = self.analytics_prio_var.get()
        if p != "All":
            q += " AND UPPER(criticality) = ?"; params.append(p)
        st = self.analytics_station_var.get()
        if st != "All":
            q += " AND UPPER(TRIM(station)) = ?"; params.append(st)
        with get_conn() as conn:
            return pd.read_sql(q, conn, params=params)

    def _clear_tab(self, key):
        for w in self._tab_frames[key].winfo_children():
            w.destroy()
        if key in self._figs:
            plt.close(self._figs[key])
            del self._figs[key]
        # Clean up any companion figures (e.g. mrt_trend, mrt_P1..P4)
        companion = key + "_trend"
        if companion in self._figs:
            plt.close(self._figs[companion])
            del self._figs[companion]
        for prio in ["P1", "P2", "P3", "P4"]:
            fig_key = key + f"_{prio}"
            if fig_key in self._figs:
                plt.close(self._figs[fig_key])
                del self._figs[fig_key]

    def _embed(self, key, fig):
        self._figs[key] = fig
        canvas = FigureCanvasTkAgg(fig, self._tab_frames[key])
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    def _no_data(self, key, msg="No data for selected filters."):
        tk.Label(self._tab_frames[key], text=msg,
                 bg=BG2, fg=TEXT_DIM, font=("Segoe UI",13)).pack(expand=True)

    def render_all(self):
        self._refresh_analytics_stations()
        raw = self._get_data()
        if raw.empty:
            for k in self._tab_frames:
                self._clear_tab(k)
                self._no_data(k)
            return
        df = _parse_datetimes(raw)

        # Build a descriptive period label for chart titles
        parts = [f"{self.month_var.get()} {self.year_var.get()}"]
        p = self.analytics_prio_var.get()
        if p != "All":
            parts.append(p)
        st = self.analytics_station_var.get()
        if st != "All":
            parts.append(st)
        period = "  ·  ".join(parts)

        self._render_ttr(df, period)
        self._render_mrt(df, period)
        self._render_wo_status(df, period)
        self._render_age(df, period)
        self._render_p1_pareto(df, period)
        self._render_recurring(df, period)

    # ── 1. Time to Repair ──────────────────────────────────────────────────────
    def _render_ttr(self, df, period):
        import matplotlib.patches as mpatches
        import matplotlib.lines  as mlines

        self._clear_tab("ttr")
        frm = self._tab_frames["ttr"]

        active_station = self.analytics_station_var.get()

        # ── Header label ──────────────────────────────────────────────────────
        subtitle = f"  —  {active_station}" if active_station != "All" else "  —  All Stations"
        tk.Label(frm,
                 text=f"  TTR Adherence by Priority (Weekly){subtitle}",
                 bg=BG2, fg=ACCENT, font=FONT_HEADER,
                 anchor="w").pack(fill="x", padx=8, pady=(6, 2))

        # ── Reload from DB: full history, station filter only (ignore month/year/prio) ──
        q = "SELECT * FROM cms WHERE 1=1"
        params = []
        if active_station != "All":
            q += " AND UPPER(TRIM(station)) = ?"; params.append(active_station)
        with get_conn() as conn:
            df_full = pd.read_sql(q, conn, params=params)
        df_full = _parse_datetimes(df_full)

        completed = df_full[
            df_full["resolved_dt"].notna() &
            df_full["ttr_hrs"].notna() &
            (df_full["ttr_hrs"] >= 0)
        ].copy()

        if completed.empty:
            tk.Label(frm, text="No resolved CMs with resolution times for the selected filters.",
                     bg=BG2, fg=TEXT_DIM, font=FONT_BODY).pack(expand=True)
            return

        # Assign week from date column directly — avoids NaT from time parsing
        completed["week"] = (pd.to_datetime(completed["date"], errors="coerce")
                             .dt.to_period("W").dt.start_time)
        completed = completed[completed["week"].notna()]

        # Shared x-axis: first week of any CM → current week
        first_week = completed["week"].min()
        last_week  = pd.Timestamp(datetime.now()).to_period("W").start_time
        all_weeks  = pd.period_range(start=first_week, end=last_week, freq="W").to_timestamp()
        n_weeks    = len(all_weeks)
        # Show the Monday start date of each week so users can cross-reference
        # the records table directly (e.g. "Mar 23" = the week containing Mar 23-29)
        week_labels = [w.strftime("%b %d") for w in all_weeks]
        x = np.arange(n_weeks)

        # ── Scrollable container (vertical) ──────────────────────────────────
        outer = tk.Frame(frm, bg=BG2)
        outer.pack(fill="both", expand=True, padx=4, pady=4)

        v_scroll = ttk.Scrollbar(outer, orient="vertical")
        v_scroll.pack(side="right", fill="y")
        scroll_cv = tk.Canvas(outer, bg=BG2, highlightthickness=0,
                              yscrollcommand=v_scroll.set)
        scroll_cv.pack(side="left", fill="both", expand=True)
        v_scroll.config(command=scroll_cv.yview)

        inner = tk.Frame(scroll_cv, bg=BG2)
        inner_id = scroll_cv.create_window((0, 0), window=inner, anchor="nw")

        # Keep inner frame full width of canvas
        def _on_canvas_resize(e):
            scroll_cv.itemconfig(inner_id, width=e.width)
        scroll_cv.bind("<Configure>", _on_canvas_resize)
        inner.bind("<Configure>", lambda e: scroll_cv.configure(
            scrollregion=scroll_cv.bbox("all")))

        # Mouse-wheel scrolling
        def _on_wheel(e):
            scroll_cv.yview_scroll(-1 * (e.delta // 120), "units")
        scroll_cv.bind_all("<MouseWheel>", _on_wheel)

        # ── One full-width chart per priority ─────────────────────────────────
        plt.style.use("dark_background")
        fig_w = max(13, n_weeks * 0.72 + 2)

        for idx, p in enumerate(PRIO_ORDER):
            pcolor     = PRIO_COLORS[p]
            sla_target = SLA_TTR[p]
            sla_lbl    = SLA_TTR_LBL[p]

            sub = completed[completed["criticality"] == p].copy()

            fig, ax = plt.subplots(1, 1, figsize=(fig_w, 3.8), facecolor=BG2)
            fig.patch.set_facecolor(BG2)
            fig.subplots_adjust(left=0.05, right=0.98, top=0.85, bottom=0.22)

            if sub.empty:
                ax.set_facecolor(PLOT_BG)
                ax.text(0.5, 0.5, f"No resolved {p} CMs in data",
                        transform=ax.transAxes, ha="center", va="center",
                        color=TEXT_DIM, fontsize=12)
                _style_ax(ax, f"{p}  —  TTR Adherence  (target {sla_lbl})",
                          ylabel="Avg TTR (Hours)")
            else:
                weekly_avg   = sub.groupby("week")["ttr_hrs"].mean().reindex(all_weeks)
                weekly_count = sub.groupby("week")["ttr_hrs"].count().reindex(all_weeks).fillna(0).astype(int)
                vals         = weekly_avg.values.astype(float)
                counts       = weekly_count.values

                # Bar colours: ≤ SLA → green (good), > SLA → red (bad)
                # Do NOT use priority colour — P1's colour is red, which would
                # make on-target bars look like failures.
                bar_colors = []
                for v in vals:
                    if np.isnan(v):       bar_colors.append(BG3)
                    elif v > sla_target:  bar_colors.append(DANGER)
                    else:                 bar_colors.append(SUCCESS)

                ax.bar(x, np.nan_to_num(vals), width=0.6,
                       color=bar_colors, alpha=0.88, zorder=3,
                       edgecolor=BG3, linewidth=0.5)

                # Label above each bar: TTR value + count
                for xi, (val, cnt) in enumerate(zip(vals, counts)):
                    if np.isnan(val) or cnt == 0:
                        continue
                    bar_h = float(np.nan_to_num(val))
                    ax.text(xi, bar_h + 0.05,
                            f"{val:.1f}h\nn={cnt}", ha="center", va="bottom",
                            fontsize=6.5, color=TEXT, fontweight="bold",
                            zorder=6, linespacing=1.3)

                # SLA target line
                ax.axhline(sla_target, color=DANGER, linewidth=2.0,
                           linestyle="--", alpha=0.9, zorder=7)
                ax.text(n_weeks - 0.5, sla_target,
                        f" Target {sla_lbl}", color=DANGER,
                        fontsize=8, va="bottom", ha="right", fontweight="bold")

                # Trend line (straight linear regression)
                has_data = ~np.isnan(vals)
                x_data   = x[has_data].astype(float)
                y_data   = vals[has_data]
                trend_line = None
                if len(x_data) >= 2:
                    coeffs    = np.polyfit(x_data, y_data, 1)
                    slope     = coeffs[0]
                    t_color   = SUCCESS if slope < 0 else ACCENT2
                    direction = "improving ↓" if slope < 0 else "worsening ↑"
                    xs = np.array([x_data[0], x_data[-1]])
                    ys = np.clip(np.polyval(coeffs, xs), 0, None)
                    ax.plot(xs, ys, color=t_color, linewidth=2.2,
                            linestyle=":", zorder=8)
                    trend_line = mlines.Line2D([], [], color=t_color, linewidth=2.2,
                                               linestyle=":", label=f"Trend ({direction})")

                # Adherence badge
                pct_ok  = (sub["ttr_hrs"] <= sla_target).sum() / len(sub) * 100
                badge_c = SUCCESS if pct_ok >= 80 else ACCENT2 if pct_ok >= 50 else DANGER
                ax.text(0.01, 0.97,
                        f"Within target: {pct_ok:.0f}%  (n={len(sub)} CMs total)",
                        transform=ax.transAxes, ha="left", va="top",
                        fontsize=8.5, color=badge_c, fontweight="bold",
                        bbox=dict(facecolor=BG3, alpha=0.75, pad=3, edgecolor=badge_c))

                # Legend
                bar_patch  = mpatches.Patch(facecolor=SUCCESS, alpha=0.88, label="Avg TTR (on-target)")
                over_patch = mpatches.Patch(facecolor=DANGER, alpha=0.88, label="Avg TTR (over target)")
                sla_line   = mlines.Line2D([], [], color=DANGER, linewidth=2.0,
                                           linestyle="--", label=f"SLA {sla_lbl}")
                handles    = [bar_patch, over_patch, sla_line]
                if trend_line: handles.append(trend_line)
                ax.legend(handles=handles, facecolor=PLOT_BG, labelcolor=TEXT,
                          fontsize=8, loc="upper right", framealpha=0.85,
                          handlelength=1.4, handletextpad=0.5)

                ax.set_xticks(x)
                ax.set_xticklabels(week_labels, fontsize=7, rotation=40, ha="right")
                ax.set_xlim(-0.7, n_weeks - 0.3)
                ax.set_ylim(0)
                ax.grid(axis="y", color=GRID_C, linewidth=0.4, alpha=0.5, zorder=0)
                _style_ax(ax, f"{p}  —  Weekly TTR Adherence  |  Target {sla_lbl}  |  {period}",
                          ylabel="Avg TTR (Hours)")

            self._figs[f"ttr_{p}"] = fig
            cv = FigureCanvasTkAgg(fig, inner)
            cv.draw()
            cv.get_tk_widget().pack(fill="x", expand=False, pady=(0, 6))

    # ── 2. Mean Response Time ─────────────────────────────────────────────────
    def _render_mrt(self, df, period):
        self._clear_tab("mrt")

        # Pull ALL records from DB so the weekly trend always spans Jan → now
        with get_conn() as conn:
            all_raw = pd.read_sql("SELECT * FROM cms", conn)

        if all_raw.empty:
            self._no_data("mrt", "No CMs with calculable response times."); return

        all_df   = _parse_datetimes(all_raw)
        trend_src = all_df[all_df["response_hrs"].notna() & (all_df["response_hrs"] >= 0)].copy()

        if trend_src.empty:
            self._no_data("mrt", "No CMs with calculable response times."); return

        # ── Build week buckets: Mon of each ISO week from Jan 1 → today ──────
        today    = pd.Timestamp.now().normalize()
        jan1     = pd.Timestamp(f"{today.year}-01-01")
        # Snap jan1 back to the Monday of that week
        week_start_jan = jan1 - pd.Timedelta(days=jan1.weekday())
        # All Monday starts up to the current week
        week_starts = pd.date_range(start=week_start_jan, end=today, freq="W-MON")

        # Tag each CM with its week-start Monday
        trend_src["week"] = trend_src["reported_dt"].dt.to_period("W").apply(
            lambda p: p.start_time.normalize() if pd.notna(p) else pd.NaT
        )
        trend_src = trend_src[trend_src["week"].notna()]

        # Label each week as "Wk N\nMon DD" for the x-axis
        def _wk_label(ts):
            wn = ts.isocalendar()[1]
            return f"Wk {wn}\n{ts.strftime('%b %d')}"

        week_labels = [_wk_label(ws) for ws in week_starts]
        n_weeks     = len(week_starts)

        # ── Scrollable container ──────────────────────────────────────────────
        outer = tk.Frame(self._tab_frames["mrt"], bg=BG2)
        outer.pack(fill="both", expand=True)
        canvas_scroll = tk.Canvas(outer, bg=BG2, highlightthickness=0)
        vsb = tk.Scrollbar(outer, orient="vertical", command=canvas_scroll.yview)
        canvas_scroll.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas_scroll.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas_scroll, bg=BG2)
        win_id = canvas_scroll.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(event):
            canvas_scroll.configure(scrollregion=canvas_scroll.bbox("all"))
            canvas_scroll.itemconfig(win_id, width=canvas_scroll.winfo_width())
        inner.bind("<Configure>", _on_configure)
        canvas_scroll.bind("<Configure>",
            lambda e: canvas_scroll.itemconfig(win_id, width=e.width))

        def _on_mousewheel(event):
            canvas_scroll.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas_scroll.bind_all("<MouseWheel>", _on_mousewheel)

        # ── Four stacked full-width figures, one per priority ────────────────
        # Each figure spans the full width so all week labels are readable.
        fig_w = max(16, n_weeks * 0.55)
        plt.style.use("dark_background")
        x_pos = np.arange(n_weeks)

        for idx, prio in enumerate(PRIO_ORDER):
            color   = PRIO_COLORS[prio]
            sla_min = SLA_RESP[prio] * 60          # SLA target in minutes

            pdata = trend_src[trend_src["criticality"] == prio]

            # Average response time (minutes) per week
            weekly_avg = (
                pdata.groupby("week")["response_hrs"]
                .mean()
                .reindex(week_starts)
            ) * 60
            vals = weekly_avg.values   # NaN where no CMs that week

            fig, ax = plt.subplots(1, 1, figsize=(fig_w, 3.8), facecolor=BG2)
            fig.patch.set_facecolor(BG2)

            # Bar colours: priority colour = within SLA, red = over
            bar_colors = [
                GRID_C   if np.isnan(v) else
                color    if v <= sla_min else
                DANGER
                for v in vals
            ]

            ax.bar(x_pos, np.nan_to_num(vals, nan=0.0),
                   color=bar_colors, alpha=0.85, zorder=3, width=0.65)

            # Straight linear trend line through weeks that have data
            valid = ~np.isnan(vals)
            if valid.sum() > 1:
                xv = x_pos[valid].astype(float)
                yv = vals[valid]
                coeffs = np.polyfit(xv, yv, 1)
                xs_trend = np.array([xv[0], xv[-1]])
                ys_trend = np.clip(np.polyval(coeffs, xs_trend), 0, None)
                ax.plot(xs_trend, ys_trend, color=color,
                        linewidth=2, zorder=5, alpha=0.95)
            elif valid.sum() == 1:
                ax.plot(x_pos[valid], vals[valid], color=color,
                        linewidth=0, marker="o", markersize=7, zorder=5)

            # SLA dashed target line
            ax.axhline(sla_min, color=DANGER, linewidth=1.5,
                       linestyle="--", zorder=6, alpha=0.85)
            ax.text(n_weeks - 0.45, sla_min, f"  SLA {SLA_RESP_LBL[prio]}",
                    color=DANGER, fontsize=8, va="center", ha="left")

            # Bar value labels in whole minutes
            top_val = vals[valid].max() if valid.any() else sla_min
            for xi, v in zip(x_pos, vals):
                if np.isnan(v) or v == 0:
                    continue
                ax.text(xi, v + top_val * 0.03, f"{int(round(v))}m",
                        ha="center", va="bottom",
                        fontsize=7, color=TEXT, fontweight="bold")

            # n= count below each bar label
            for xi, ws in zip(x_pos, week_starts):
                n = pdata[pdata["week"] == ws].shape[0]
                if n:
                    ax.text(xi, 0, f"n={n}", ha="center", va="top",
                            fontsize=6, color=TEXT_DIM,
                            transform=ax.get_xaxis_transform())

            ax.set_xticks(x_pos)
            ax.set_xticklabels(week_labels, fontsize=7.5, rotation=45, ha="right")

            y_top = top_val * 1.4 if valid.any() and top_val > 0 else sla_min * 2
            ax.set_ylim(0, max(y_top, sla_min * 1.6))
            ax.yaxis.set_major_formatter(
                matplotlib.ticker.FuncFormatter(lambda v, _: f"{int(v)}m"))
            _style_ax(ax,
                      f"{prio} — Weekly Avg Response Time  |  {today.year}  "
                      f"|  SLA target: {SLA_RESP_LBL[prio]}",
                      ylabel="Minutes")

            fig.subplots_adjust(left=0.05, right=0.97, top=0.88, bottom=0.22)

            fig_key = f"mrt_{prio}"
            self._figs[fig_key] = fig
            cv = FigureCanvasTkAgg(fig, inner)
            cv.draw()
            pady = (10, 2) if idx == 0 else (2, 2)
            cv.get_tk_widget().pack(fill="x", padx=6, pady=pady)

    # ── 3. WO Opened vs Closed ────────────────────────────────────────────────
    def _render_wo_status(self, df, period):
        self._clear_tab("wo_status")
        df2 = df.copy()
        df2["date_dt"] = pd.to_datetime(df2["date"], errors="coerce")

        if df2["date_dt"].isna().all():
            self._no_data("wo_status"); return

        fig, axes = _make_fig(1, 1, figsize=(13, 5))
        ax1 = axes[0][0]

        # Group by week
        df2["week"] = df2["date_dt"].dt.to_period("W").dt.start_time
        opened = df2.groupby("week").size()

        df2["res_dt2"] = pd.to_datetime(df2["resolved_date"], errors="coerce")
        df2["res_week"] = df2["res_dt2"].dt.to_period("W").dt.start_time
        closed = df2[df2["res_dt2"].notna()].groupby("res_week").size()

        all_weeks = sorted(set(opened.index) | set(closed.index))
        opened_a  = [opened.get(w, 0) for w in all_weeks]
        closed_a  = [closed.get(w, 0) for w in all_weeks]
        x = range(len(all_weeks))

        ax1.bar([i-0.2 for i in x], opened_a, 0.4, label="Opened",
                color=ACCENT2, alpha=0.85, zorder=3)
        ax1.bar([i+0.2 for i in x], closed_a, 0.4, label="Closed",
                color=SUCCESS, alpha=0.85, zorder=3)
        xlbls = [str(w)[:10] for w in all_weeks]
        step  = max(1, len(all_weeks)//6)
        ax1.set_xticks([i for i in x if i % step == 0])
        ax1.set_xticklabels([xlbls[i] for i in x if i % step == 0],
                            rotation=30, ha="right", fontsize=7)
        ax1.legend(facecolor=PLOT_BG, labelcolor=TEXT, fontsize=8)
        _style_ax(ax1, f"WOs Opened vs Closed (by Week) — {period}", ylabel="Count")

        fig.suptitle(f"WO Opened vs Closed  |  {period}",
                     color=TEXT, fontsize=12, fontweight="bold", y=1.01)
        fig.subplots_adjust(left=0.08, right=0.97, top=0.93, bottom=0.18)
        self._embed("wo_status", fig)

    # ── 4. WO Age Profile ─────────────────────────────────────────────────────
    def _render_age(self, df, period):
        self._clear_tab("age")
        today = pd.Timestamp(datetime.now())

        open_cms = df[df["resolved_dt"].isna()].copy()
        open_cms["age_hrs"] = (today - open_cms["reported_dt"]).dt.total_seconds() / 3600
        open_cms = open_cms[open_cms["age_hrs"] >= 0]

        fig, axes = _make_fig(1, 2, figsize=(13,5))
        ax1, ax2  = axes[0]

        # Age buckets
        bins   = [0, 4, 8, 24, 72, 168, 720, float("inf")]
        labels = ["<4h","4–8h","8–24h","1–3d","3–7d","7–30d",">30d"]
        if not open_cms.empty:
            open_cms["age_bucket"] = pd.cut(open_cms["age_hrs"], bins=bins, labels=labels)
            bucket_counts = open_cms["age_bucket"].value_counts().reindex(labels).fillna(0)
            bar_colors = [SUCCESS, SUCCESS, ACCENT2, ACCENT2, DANGER, DANGER, DANGER]
            b = ax1.bar(labels, bucket_counts.values, color=bar_colors, alpha=0.85, zorder=3)
            _bar_labels(ax1, b, fmt="{:.0f}")
        else:
            ax1.text(0.5, 0.5, "All CMs resolved\n✅", transform=ax1.transAxes,
                     ha="center", va="center", color=SUCCESS, fontsize=14)
        _style_ax(ax1, f"Open WO Age Profile — {period}", ylabel="Count")

        # Age by priority for open CMs
        if not open_cms.empty:
            age_by_prio = open_cms.groupby("criticality")["age_hrs"].mean().reindex(PRIO_ORDER).fillna(0)
            colors = [PRIO_COLORS[p] for p in PRIO_ORDER]
            b2 = ax2.bar(PRIO_ORDER, age_by_prio.values, color=colors, alpha=0.85, zorder=3)
            _bar_labels(ax2, b2)
            # Count labels on top
            cnt_by_prio = open_cms.groupby("criticality").size().reindex(PRIO_ORDER).fillna(0)
            for i, (p, n) in enumerate(zip(PRIO_ORDER, cnt_by_prio)):
                ax2.text(i, ax2.get_ylim()[1]*0.02, f"n={int(n)}",
                         ha="center", va="bottom", fontsize=7, color=TEXT_DIM)
        else:
            ax2.text(0.5, 0.5, "No open CMs\n✅", transform=ax2.transAxes,
                     ha="center", va="center", color=SUCCESS, fontsize=14)
        _style_ax(ax2, "Avg Age of Open WOs by Priority (Hours)", ylabel="Hours")

        # Summary stats in title
        n_open   = len(open_cms)
        n_closed = df["resolved_dt"].notna().sum()
        pct_closed = n_closed / len(df) * 100 if len(df) else 0
        fig.suptitle(
            f"WO Age Profile  |  {period}  |  "
            f"Open: {n_open}  Closed: {n_closed}  ({pct_closed:.0f}% close rate)",
            color=TEXT, fontsize=11, fontweight="bold", y=1.01)
        fig.subplots_adjust(left=0.08, right=0.93, top=0.93, bottom=0.18, wspace=0.38)
        self._embed("age", fig)

    # ── 5. Pareto by Priority (Weekly YTD) ────────────────────────────────────
    def _render_p1_pareto(self, df, period):
        self._clear_tab("p1_pareto")
        frm = self._tab_frames["p1_pareto"]

        tk.Label(frm,
                 text=f"  CM Frequency by Priority — Weekly YTD  |  {period}",
                 bg=BG2, fg=ACCENT, font=FONT_HEADER,
                 anchor="w").pack(fill="x", padx=8, pady=(6, 2))

        # Build YTD week spine: Mon Jan 1-week → current week
        today          = pd.Timestamp.now().normalize()
        jan1           = pd.Timestamp(f"{today.year}-01-01")
        week_start_jan = jan1 - pd.Timedelta(days=jan1.weekday())
        week_starts    = pd.date_range(start=week_start_jan, end=today, freq="W-MON")
        n_weeks        = len(week_starts)
        week_labels    = [ws.strftime("Wk%U\n%b %d") for ws in week_starts]
        x_pos          = np.arange(n_weeks)

        # Tag every CM with its week-start Monday
        df2 = df.copy()
        df2["date_dt"] = pd.to_datetime(df2["date"], errors="coerce")
        df2["week"]    = df2["date_dt"].dt.to_period("W").apply(
            lambda p: p.start_time.normalize() if pd.notna(p) else pd.NaT
        )

        # ── Scrollable container (vertical) ──────────────────────────────────
        outer = tk.Frame(frm, bg=BG2)
        outer.pack(fill="both", expand=True, padx=4, pady=4)

        v_scroll = ttk.Scrollbar(outer, orient="vertical")
        v_scroll.pack(side="right", fill="y")
        scroll_cv = tk.Canvas(outer, bg=BG2, highlightthickness=0,
                              yscrollcommand=v_scroll.set)
        scroll_cv.pack(side="left", fill="both", expand=True)
        v_scroll.config(command=scroll_cv.yview)

        inner = tk.Frame(scroll_cv, bg=BG2)
        inner_id = scroll_cv.create_window((0, 0), window=inner, anchor="nw")

        scroll_cv.bind("<Configure>",
                       lambda e: scroll_cv.itemconfig(inner_id, width=e.width))
        inner.bind("<Configure>",
                   lambda e: scroll_cv.configure(scrollregion=scroll_cv.bbox("all")))
        scroll_cv.bind_all("<MouseWheel>",
                           lambda e: scroll_cv.yview_scroll(-1 * (e.delta // 120), "units"))

        # ── One full-width chart per priority ─────────────────────────────────
        plt.style.use("dark_background")
        fig_w = max(13, n_weeks * 0.72 + 2)

        for idx, p in enumerate(PRIO_ORDER):
            pcolor = PRIO_COLORS[p]
            sub    = df2[df2["criticality"] == p].copy()

            fig, ax = plt.subplots(1, 1, figsize=(fig_w, 3.8), facecolor=BG2)
            fig.patch.set_facecolor(BG2)
            fig.subplots_adjust(left=0.05, right=0.98, top=0.85, bottom=0.22)

            if sub.empty:
                ax.set_facecolor(PLOT_BG)
                ax.text(0.5, 0.5, f"No {p} CMs in period",
                        transform=ax.transAxes, ha="center", va="center",
                        color=TEXT_DIM, fontsize=12)
                _style_ax(ax, f"{p} — Weekly CMs YTD  (SLA {SLA_TTR_LBL[p]})",
                          ylabel="CM Count")
            else:
                weekly_counts = (
                    sub.groupby("week").size()
                    .reindex(week_starts)
                    .fillna(0)
                    .astype(int)
                )
                vals = weekly_counts.values

                bars = ax.bar(x_pos, vals, color=pcolor, alpha=0.85, zorder=3, width=0.7)
                _bar_labels(ax, bars, fmt="{:.0f}", color=TEXT, fontsize=7)

                ax.set_xticks(x_pos)
                ax.set_xticklabels(week_labels, fontsize=7, rotation=40, ha="right")
                ax.set_xlim(-0.7, n_weeks - 0.3)
                ax.set_ylim(0)
                ax.grid(axis="y", color=GRID_C, linewidth=0.4, alpha=0.5, zorder=0)

                ttr_sub = sub[sub["ttr_hrs"].notna() & (sub["ttr_hrs"] >= 0)]["ttr_hrs"]
                if not ttr_sub.empty:
                    pct_ok  = (ttr_sub <= SLA_TTR[p]).sum() / len(ttr_sub) * 100
                    badge_c = SUCCESS if pct_ok >= 80 else ACCENT2 if pct_ok >= 50 else DANGER
                    ax.text(0.01, 0.97,
                            f"TTR target {SLA_TTR_LBL[p]}  |  Within target: {pct_ok:.0f}%  (n={len(ttr_sub)})",
                            transform=ax.transAxes, ha="left", va="top", fontsize=8.5,
                            color=badge_c,
                            bbox=dict(facecolor=BG3, alpha=0.75, pad=3, edgecolor=badge_c))
                ax.text(0.99, 0.97, f"{len(sub)} CMs total",
                        transform=ax.transAxes, ha="right", va="top",
                        fontsize=8, color=pcolor, fontweight="bold")

                _style_ax(ax, f"{p} — Weekly CMs YTD  |  SLA {SLA_TTR_LBL[p]}  |  {period}",
                          ylabel="CM Count")

            self._figs[f"pareto_{p}"] = fig
            cv = FigureCanvasTkAgg(fig, inner)
            cv.draw()
            cv.get_tk_widget().pack(fill="x", expand=False, pady=(0, 6))


    # ── 6. Recurring Disruptions ──────────────────────────────────────────────
    def _render_recurring(self, df, period):
        self._clear_tab("recurring")
        frm = self._tab_frames["recurring"]

        df2 = df.copy()
        df2["station_norm"] = df2["station"].str.upper().str.strip()
        threshold = 3

        # ── Top: Pareto chart ────────────────────────────────────────────────
        chart_frame = tk.Frame(frm, bg=BG2)
        chart_frame.pack(fill="both", expand=True, side="top")

        plt.style.use("dark_background")
        fig, ax1 = plt.subplots(1, 1, figsize=(13, 4), facecolor=BG2)
        fig.patch.set_facecolor(BG2)

        freq = df2["station_norm"].value_counts().head(15)
        if not freq.empty:
            x          = range(len(freq))
            bar_colors = [DANGER if v >= threshold else ACCENT2 if v == 2 else ACCENT
                          for v in freq.values]
            bars = ax1.bar(x, freq.values, color=bar_colors, alpha=0.85, zorder=3)
            _bar_labels(ax1, bars, fmt="{:.0f}")
            ax1.set_xticks(x)
            ax1.set_xticklabels(freq.index, rotation=30, ha="right", fontsize=8)
            ax1.axhline(threshold, color=DANGER, linewidth=1.2,
                        linestyle=":", alpha=0.6, zorder=5)
            ax1.text(0.99, 0.98,
                     f"Red = >=3 CMs (recurring)",
                     transform=ax1.transAxes, ha="right", va="top",
                     fontsize=7, color=DANGER)

        _style_ax(ax1, f"Recurring Disruptions by Station  |  {period}", ylabel="CM Count")
        fig.tight_layout(pad=1.2)
        self._figs["recurring"] = fig
        cv = FigureCanvasTkAgg(fig, chart_frame)
        cv.draw()
        cv.get_tk_widget().pack(fill="both", expand=True)

        # ── Bottom: Recurring events table ───────────────────────────────────
        list_outer = tk.Frame(frm, bg=BG2)
        list_outer.pack(fill="both", expand=True, side="bottom", padx=12, pady=(0, 8))

        # Column definitions: (header text, pixel width, anchor)
        cols_def = [
            ("#",              28,  "center"),
            ("Station",       155,  "w"),
            ("Total",          48,  "center"),
            ("P1",             38,  "center"),
            ("P2",             38,  "center"),
            ("P3",             38,  "center"),
            ("P4",             38,  "center"),
            ("Avg TTR",        68,  "center"),
            ("Last Seen",      88,  "center"),
            ("Most Recent Issue", 0, "w"),   # 0 = fill remainder
        ]

        # Header bar
        hdr_bar = tk.Frame(list_outer, bg=BG3, pady=3)
        hdr_bar.pack(fill="x")
        for col_name, col_w, anch in cols_def:
            kw = {"width": col_w // 7} if col_w else {}
            tk.Label(hdr_bar, text=col_name, bg=BG3, fg=ACCENT,
                     font=FONT_HEADER, anchor=anch, padx=5,
                     **kw).pack(side="left", fill="x",
                                expand=(col_w == 0))

        # Scroll canvas
        scroll_canvas = tk.Canvas(list_outer, bg=BG2, highlightthickness=0)
        vscroll = ttk.Scrollbar(list_outer, orient="vertical",
                                command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        scroll_canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(scroll_canvas, bg=BG2)
        body_id = scroll_canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda e: scroll_canvas.configure(
                      scrollregion=scroll_canvas.bbox("all")))
        scroll_canvas.bind("<Configure>",
                           lambda e: scroll_canvas.itemconfig(body_id, width=e.width))
        scroll_canvas.bind_all("<MouseWheel>",
            lambda e: scroll_canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        # Build rows
        stations_sorted = df2["station_norm"].value_counts()
        recurring_stations = stations_sorted[stations_sorted >= threshold]

        if recurring_stations.empty:
            tk.Label(body,
                     text=f"No stations with {threshold}+ CMs in the selected period.",
                     bg=BG2, fg=TEXT_DIM, font=FONT_BODY).pack(padx=16, pady=12)
        else:
            df2["reported_dt"] = pd.to_datetime(
                df2["date"] + " " + df2["time"],
                format="%Y-%m-%d %H:%M", errors="coerce")

            for rank, (station, total) in enumerate(recurring_stations.items()):
                sub      = df2[df2["station_norm"] == station].copy()
                p_counts = sub["criticality"].value_counts()
                ttr_vals = sub["ttr_hrs"].dropna() if "ttr_hrs" in sub.columns else pd.Series(dtype=float)
                avg_ttr  = f"{ttr_vals.mean():.1f} h" if not ttr_vals.empty else "—"

                last_dt  = sub["reported_dt"].dropna().max()
                last_str = last_dt.strftime("%Y-%m-%d") if pd.notna(last_dt) else "—"

                sub_s    = sub.sort_values("reported_dt", ascending=False)
                comment  = str(sub_s.iloc[0].get("comments", "") or "").strip() if not sub_s.empty else ""
                if len(comment) > 70:
                    comment = comment[:70] + "..."

                has_p1  = p_counts.get("P1", 0) > 0
                row_bg  = "#3a1515" if has_p1 else ("#252a3d" if rank % 2 == 0 else BG3)
                rank_c  = DANGER if total >= 10 else ACCENT2 if total >= 5 else ACCENT

                row = tk.Frame(body, bg=row_bg, pady=3)
                row.pack(fill="x", padx=2, pady=1)

                row_vals = [
                    (f"#{rank+1}",                  28,  "center", rank_c,              FONT_SMALL),
                    (station,                       155,  "w",      TEXT,                ("Segoe UI", 9, "bold")),
                    (str(total),                     48,  "center", rank_c,              ("Segoe UI", 9, "bold")),
                    (str(p_counts.get("P1", 0)),     38,  "center", PRIO_COLORS["P1"],   FONT_SMALL),
                    (str(p_counts.get("P2", 0)),     38,  "center", PRIO_COLORS["P2"],   FONT_SMALL),
                    (str(p_counts.get("P3", 0)),     38,  "center", PRIO_COLORS["P3"],   FONT_SMALL),
                    (str(p_counts.get("P4", 0)),     38,  "center", PRIO_COLORS["P4"],   FONT_SMALL),
                    (avg_ttr,                        68,  "center", TEXT_DIM,            FONT_SMALL),
                    (last_str,                       88,  "center", TEXT_DIM,            FONT_SMALL),
                    (comment,                         0,  "w",      TEXT_DIM,            ("Segoe UI", 9, "italic")),
                ]
                for val, w, anch, fg, fnt in row_vals:
                    kw = {"width": w // 7} if w else {}
                    tk.Label(row, text=val, bg=row_bg, fg=fg,
                             font=fnt, anchor=anch, padx=4,
                             **kw).pack(side="left", fill="x",
                                        expand=(w == 0))

        # Footer summary
        n_r = len(recurring_stations)
        n_c = int(recurring_stations.sum()) if not recurring_stations.empty else 0
        footer = tk.Frame(list_outer, bg=BG3)
        footer.pack(fill="x", pady=(3, 0))
        tk.Label(footer,
                 text=(f"  {n_r} recurring stations  |  {n_c} total CMs  |  "
                       f"Threshold: >= {threshold} CMs  |  "
                       f"Dark red rows = station has P1 CM(s)"),
                 bg=BG3, fg=TEXT_DIM, font=FONT_SMALL,
                 anchor="w").pack(fill="x", padx=8, pady=3)


    def _export_all(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG","*.png"),("PDF","*.pdf")],
            title="Export — choose base filename")
        if not path: return
        base, ext = os.path.splitext(path)
        saved = []
        for key, fig in self._figs.items():
            out = f"{base}_{key}{ext}"
            fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG2)
            saved.append(os.path.basename(out))
        messagebox.showinfo("Exported", f"Saved {len(saved)} charts:\n" + "\n".join(saved))



# ─── Import helper ─────────────────────────────────────────────────────────────

def _import_df(df, get_conn_fn, log_fn=None, sheet="Sheet"):
    """Import a DataFrame (one Excel sheet) into the cms table.
    Returns the number of rows successfully inserted."""

    def log(msg):
        if log_fn:
            log_fn(msg)
        else:
            print(msg)

    if df is None or df.empty:
        log(f"  Sheet '{sheet}': empty — skipped.")
        return 0

    # ── Build a normalised-name → original-column lookup
    norm_cols = {str(c).strip().upper(): c for c in df.columns}

    # ── Flexible column aliases: DB field → accepted Excel header variants
    ALIASES = {
        "date":            ["DATE", "INCIDENT DATE", "REPORT DATE", "CM DATE"],
        "time":            ["TIME", "INCIDENT TIME", "REPORT TIME", "CM TIME"],
        "andon":           ["ANDON", "ANDON LEVEL", "LEVEL"],
        "event_id":        ["EVENT ID", "EVENTID", "EVENT_ID",
                            "WO", "WO#", "WO NUMBER", "WORK ORDER"],
        "station":         ["STATION", "STATION/EQUIPMENT", "STATION / EQUIPMENT",
                            "EQUIPMENT", "ASSET", "MACHINE", "LINE"],
        "user":            ["USER", "USER/REPORTER", "USER / REPORTER",
                            "REPORTER", "REPORTED BY", "TECHNICIAN", "OPERATOR"],
        "criticality":     ["CRITICALITY", "PRIORITY", "CRIT", "SEVERITY"],
        "comments":        ["COMMENTS", "COMMENT", "DESCRIPTION",
                            "ISSUE", "FAILURE DESCRIPTION", "PROBLEM"],
        "ack_date":        ["ACKNOWLEDGE DATE", "ACK DATE", "ACK_DATE",
                            "ACKNOWLEDGEMENT DATE"],
        "ack_time":        ["ACKNOWLEDGE TIME", "ACK TIME", "ACK_TIME",
                            "ACKNOWLEDGEMENT TIME"],
        "resolved_date":   ["RESOLVED DATE", "RESOLVE DATE", "RESOLUTION DATE",
                            "CLOSED DATE", "COMPLETION DATE"],
        "resolve_time":    ["RESOLVE TIME", "RESOLVED TIME", "CLOSE TIME",
                            "CLOSED TIME", "COMPLETION TIME"],
        "resolution_time": ["RESOLUTION TIME", "RES TIME", "TTR",
                            "TIME TO RESOLVE", "TTR (HH:MM)",
                            "RESOLUTION TIME (HH:MM)"],
        "root_cause":      ["ROOT CAUSE", "ROOTCAUSE", "FAILURE TYPE",
                            "CAUSE", "FAULT TYPE", "FAULT CATEGORY"],
        "notes":           ["NOTES", "NOTE", "REMARKS", "ADDITIONAL NOTES",
                            "COMMENTS 2", "FOLLOW UP"],
    }

    field_col = {}          # DB field → original DataFrame column name
    for field, aliases in ALIASES.items():
        for alias in aliases:
            if alias in norm_cols:
                field_col[field] = norm_cols[alias]
                break

    if "date" not in field_col:
        log(f"  Sheet '{sheet}': no DATE column found — skipped.")
        return 0

    mapped = ", ".join(f"{k}←'{v}'" for k, v in field_col.items())
    log(f"  Sheet '{sheet}': mapped columns — {mapped}")

    def cell(row, field, default=""):
        if field not in field_col:
            return default
        val = row.iloc[df.columns.get_loc(field_col[field])] \
              if field_col[field] in df.columns else default
        if val is None:
            return default
        try:
            if pd.isna(val):
                return default
        except (TypeError, ValueError):
            pass
        return str(val).strip()

    inserted = 0
    skipped  = 0

    with get_conn_fn() as conn:
        for _, row in df.iterrows():
            raw_date  = cell(row, "date")
            date_val  = _parse_date(raw_date)
            if not date_val:
                skipped += 1
                continue

            time_val      = _fmt_time_12h(cell(row, "time"))
            ack_date      = _parse_date(cell(row, "ack_date"))
            ack_time      = _fmt_time_12h(cell(row, "ack_time"))
            resolved_date = _parse_date(cell(row, "resolved_date"))
            resolve_time  = _fmt_time_12h(cell(row, "resolve_time"))

            # Use stored resolution_time if present; otherwise recalculate TTR
            res_t = cell(row, "resolution_time")
            if not res_t or res_t.lower() in ("nan", "none", ""):
                res_t = calc_resolution(
                    date_val, time_val or "00:00",
                    resolved_date, resolve_time or "00:00")

            # Normalise andon capitalisation (fix common "Mediun" typo too)
            andon = cell(row, "andon").strip().capitalize()
            if andon.upper() in ("MEDIUN", "MEDUIN"):
                andon = "Medium"

            # Normalise criticality to uppercase P1-P4
            crit = cell(row, "criticality").strip().upper()

            conn.execute("""
                INSERT INTO cms
                  (date, time, andon, event_id, station, user, criticality,
                   comments, ack_date, ack_time, resolved_date, resolve_time,
                   resolution_time, root_cause, notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (date_val, time_val, andon,
                 cell(row, "event_id"),
                 cell(row, "station"),
                 cell(row, "user"),
                 crit,
                 cell(row, "comments"),
                 ack_date, ack_time,
                 resolved_date, resolve_time,
                 res_t,
                 cell(row, "root_cause"),
                 cell(row, "notes")))
            inserted += 1

        conn.commit()

    log(f"  Sheet '{sheet}': ✅ {inserted} inserted, {skipped} skipped (no date).")
    return inserted


# ─── Import from Excel ─────────────────────────────────────────────────────────

class ImportView(tk.Frame):
    def __init__(self, master, on_import_cb):
        super().__init__(master, bg=BG2)
        self.on_import_cb = on_import_cb
        self._build()

    def _build(self):
        tk.Label(self, text="📥  Import from Excel", bg=BG2, fg=TEXT,
                 font=FONT_TITLE).pack(padx=20, pady=(16,8), anchor="w")

        box = tk.Frame(self, bg=BG3, highlightthickness=1, highlightbackground=SEP)
        box.pack(padx=30, pady=20, fill="x")

        tk.Label(box, text=(
            "Import CM records from an existing Excel file.\n"
            "The file should have columns matching the CM Manager format:\n"
            "DATE · TIME · ANDON · EVENT ID · STATION/EQUIPMENT · USER · "
            "CRITICALITY · COMMENTS · ACKNOWLEDGE DATE · ACKNOWLEDGE TIME · "
            "RESOLVED DATE · RESOLVE TIME · TIME · NOTES"),
            bg=BG3, fg=TEXT_DIM, font=FONT_BODY, justify="left",
            wraplength=580).pack(padx=20, pady=16, anchor="w")

        btn_row = tk.Frame(box, bg=BG3)
        btn_row.pack(padx=20, pady=(0,16), anchor="w")
        tk.Button(btn_row, text="  📂  Choose Excel File…  ",
                  bg=ACCENT, fg="white", relief="flat", font=FONT_BODY,
                  cursor="hand2", padx=10, pady=8,
                  command=self._do_import).pack(side="left", padx=(0,8))
        tk.Button(btn_row, text="  🗑  Clear All Records & Re-import  ",
                  bg=DANGER, fg="white", relief="flat", font=FONT_BODY,
                  cursor="hand2", padx=10, pady=8,
                  command=self._clear_and_reimport).pack(side="left")

        self.log = tk.Text(self, height=12, bg=ENTRY_BG, fg=TEXT,
                           font=FONT_SMALL, relief="flat", state="disabled")
        self.log.pack(fill="both", expand=True, padx=20, pady=(0,16))

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg+"\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _do_import(self):
        path = filedialog.askopenfilename(
            filetypes=[("Excel","*.xlsx *.xls")], title="Import Excel")
        if not path: return
        try:
            xl = pd.ExcelFile(path)
            total = 0
            for sheet in xl.sheet_names:
                df = pd.read_excel(path, sheet_name=sheet)
                inserted = _import_df(df, get_conn,
                                      log_fn=self._log, sheet=sheet)
                total += inserted
            self._log(f"\n🎉 Total imported: {total} records")
            self.on_import_cb()
        except Exception as e:
            self._log(f"❌ Error: {e}")

    def _clear_and_reimport(self):
        path = filedialog.askopenfilename(
            filetypes=[("Excel","*.xlsx *.xls")], title="Choose Excel to Re-import")
        if not path: return
        if not messagebox.askyesno("Confirm Clear",
            "This will DELETE all existing records and re-import from the selected file.\nAre you sure?"):
            return
        with get_conn() as conn:
            conn.execute("DELETE FROM cms")
            conn.commit()
        self._log("🗑 All existing records cleared.")
        try:
            xl = pd.ExcelFile(path)
            total = 0
            for sheet in xl.sheet_names:
                df = pd.read_excel(path, sheet_name=sheet)
                inserted = _import_df(df, get_conn,
                                      log_fn=self._log, sheet=sheet)
                total += inserted
            self._log(f"\n🎉 Total imported: {total} records")
            self.on_import_cb()
        except Exception as e:
            self._log(f"❌ Error: {e}")

# ─── MTBF constants ────────────────────────────────────────────────────────────

MTBF_OPERATING_HRS = {"P1": 1414, "P2": 554}   # total operating hours per priority
MTBF_TARGET        = {"P1": 80,   "P2": 40}     # KPI targets (hours)  P1>80h  P2>40h
MTBF_TARGET_LBL    = {"P1": ">80 h", "P2": ">40 h"}
MTBF_PRIOS         = ["P1", "P2"]

# ─── MTBF View ─────────────────────────────────────────────────────────────────

class MTBFView(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=BG2)
        self._figs = {}
        self._build()

    def _build(self):
        # ── Header bar ────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BG2)
        hdr.pack(fill="x", padx=16, pady=(12, 0))
        tk.Label(hdr, text="⏱  MTBF — Mean Time Between Failures",
                 bg=BG2, fg=TEXT, font=FONT_TITLE).pack(side="left")

        ff = tk.Frame(hdr, bg=BG2); ff.pack(side="left", padx=20)
        for lbl, attr, opts in [
            ("Month:", "month_var", ["All"] + MONTHS),
            ("Year:",  "year_var",  ["All"] + [str(y) for y in range(2024, datetime.now().year + 2)]),
        ]:
            tk.Label(ff, text=lbl, bg=BG2, fg=TEXT_DIM, font=FONT_BODY).pack(side="left", padx=(10, 2))
            v = tk.StringVar()
            setattr(self, attr, v)
            cb = ttk.Combobox(ff, textvariable=v, values=opts, width=11,
                              font=FONT_BODY, state="readonly")
            cb.pack(side="left")

        self.month_var.set("All")
        self.year_var.set(str(datetime.now().year))

        tk.Label(ff, text="Station:", bg=BG2, fg=TEXT_DIM,
                 font=FONT_BODY).pack(side="left", padx=(14, 2))
        self.station_var = tk.StringVar(value="All")
        self.station_cb  = ttk.Combobox(ff, textvariable=self.station_var,
                                        values=["All"], width=18,
                                        font=FONT_BODY, state="readonly")
        self.station_cb.pack(side="left")
        self._refresh_stations()

        tk.Button(hdr, text="  🔄 Refresh  ", bg=ACCENT, fg="white",
                  relief="flat", font=FONT_BODY, cursor="hand2",
                  padx=8, pady=5, command=self.render).pack(side="right", padx=4)
        tk.Button(hdr, text="  📥 Export PNG  ", bg=ACCENT2, fg="white",
                  relief="flat", font=FONT_SMALL, cursor="hand2",
                  padx=8, pady=5, command=self._export_all).pack(side="right", padx=4)

        # ── KPI info strip ────────────────────────────────────────────────────
        info = tk.Frame(self, bg=BG3, highlightthickness=1, highlightbackground=SEP)
        info.pack(fill="x", padx=16, pady=(6, 0))
        tk.Label(info,
                 text=("  MTBF = Total Operating Time ÷ Number of Failures   "
                       "  |  P1 Operating Time: 1,414 h   Target: >80 h   "
                       "  |  P2 Operating Time: 554 h   Target: >40 h   "
                       "  |  Green bars = above target   ·   Red bars = below target"),
                 bg=BG3, fg=TEXT_DIM, font=FONT_SMALL, anchor="w").pack(
                 fill="x", padx=10, pady=5)

        # ── Scroll area ───────────────────────────────────────────────────────
        self._scroll_outer = tk.Frame(self, bg=BG2)
        self._scroll_outer.pack(fill="both", expand=True, padx=4, pady=6)
        tk.Label(self._scroll_outer, text="Click  🔄 Refresh  to load charts",
                 bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 13)).pack(expand=True)

    def _export_all(self):
        if not self._figs:
            messagebox.showwarning("Nothing to Export",
                                   "No charts to export. Click Refresh first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf")],
            title="Export MTBF Charts — choose base filename")
        if not path: return
        base, ext = os.path.splitext(path)
        saved = []
        for key, fig in self._figs.items():
            out = f"{base}_{key}{ext}"
            fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG2)
            saved.append(os.path.basename(out))
        messagebox.showinfo("Exported",
                            f"Saved {len(saved)} charts:\n" + "\n".join(saved))

    def _refresh_stations(self):
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT UPPER(TRIM(station)) AS s FROM cms "
                "WHERE station IS NOT NULL AND TRIM(station) != '' ORDER BY s"
            ).fetchall()
        stations = ["All"] + [r["s"] for r in rows]
        self.station_cb.configure(values=stations)
        if self.station_var.get() not in stations:
            self.station_var.set("All")

    def _get_data(self):
        q = "SELECT * FROM cms WHERE UPPER(criticality) IN ('P1','P2')"
        params = []
        st = self.station_var.get()
        if st != "All":
            q += " AND UPPER(TRIM(station)) = ?"; params.append(st)
        with get_conn() as conn:
            return pd.read_sql(q, conn, params=params)

    def render(self):
        import matplotlib.patches as mpatches
        import matplotlib.lines  as mlines
        from scipy.interpolate import make_interp_spline

        self._refresh_stations()

        # Destroy old scroll area widgets & close old figures
        for w in self._scroll_outer.winfo_children():
            w.destroy()
        for fig in self._figs.values():
            plt.close(fig)
        self._figs.clear()

        # ── Build scroll container ────────────────────────────────────────────
        v_scroll  = ttk.Scrollbar(self._scroll_outer, orient="vertical")
        v_scroll.pack(side="right", fill="y")
        scroll_cv = tk.Canvas(self._scroll_outer, bg=BG2, highlightthickness=0,
                              yscrollcommand=v_scroll.set)
        scroll_cv.pack(side="left", fill="both", expand=True)
        v_scroll.config(command=scroll_cv.yview)
        inner    = tk.Frame(scroll_cv, bg=BG2)
        inner_id = scroll_cv.create_window((0, 0), window=inner, anchor="nw")
        scroll_cv.bind("<Configure>",
                       lambda e: scroll_cv.itemconfig(inner_id, width=e.width))
        inner.bind("<Configure>",
                   lambda e: scroll_cv.configure(scrollregion=scroll_cv.bbox("all")))
        scroll_cv.bind_all("<MouseWheel>",
                           lambda e: scroll_cv.yview_scroll(-1 * (e.delta // 120), "units"))

        # ── Fetch data ────────────────────────────────────────────────────────
        raw = self._get_data()
        if raw.empty:
            tk.Label(inner, text="No P1 or P2 CMs found.",
                     bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 13)).pack(expand=True, pady=40)
            return

        # Assign week from the DATE column directly — avoids NaT from time
        # parsing issues dropping records silently from the groupby
        raw["date_dt"] = pd.to_datetime(raw["date"], errors="coerce")
        raw = raw[raw["date_dt"].notna()].copy()
        raw["week"] = raw["date_dt"].dt.to_period("W").dt.start_time

        if raw.empty:
            tk.Label(inner, text="No records with parseable dates.",
                     bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 13)).pack(expand=True, pady=40)
            return

        # Shared week range: first CM → current week
        first_week = raw["week"].min()
        last_week  = pd.Timestamp(datetime.now()).to_period("W").start_time
        all_weeks  = pd.period_range(
            start=first_week, end=last_week, freq="W").to_timestamp()
        n_weeks    = len(all_weeks)

        # Show the Monday start date of each week so users can cross-reference
        # the records table directly (e.g. "Mar 23" = the week of Mar 23-29)
        week_labels = [w.strftime("%b %d") for w in all_weeks]
        x = np.arange(n_weeks)

        # Monthly operating hours → weekly rate
        # avg weeks/month = 52/12 = 4.333
        WEEKS_PER_MONTH = 52 / 12
        ophrs_per_week = {p: MTBF_OPERATING_HRS[p] / WEEKS_PER_MONTH
                          for p in MTBF_PRIOS}

        station_suffix = (f"  ·  {self.station_var.get()}"
                          if self.station_var.get() != "All" else "")
        plt.style.use("dark_background")
        fig_w = max(13, n_weeks * 0.85 + 2)

        # ── One chart per priority ────────────────────────────────────────────
        for p in MTBF_PRIOS:
            pcolor   = PRIO_COLORS[p]
            monthly_ophrs = MTBF_OPERATING_HRS[p]
            ophrs_pw = ophrs_per_week[p]
            target   = MTBF_TARGET[p]
            tgt_lbl  = MTBF_TARGET_LBL[p]

            sub = raw[raw["criticality"] == p].copy()

            fig, ax = plt.subplots(1, 1, figsize=(fig_w, 4.4), facecolor=BG2)
            fig.patch.set_facecolor(BG2)
            fig.subplots_adjust(left=0.05, right=0.98, top=0.84, bottom=0.26)

            if sub.empty:
                ax.set_facecolor(PLOT_BG)
                ax.text(0.5, 0.5, f"No {p} CMs found",
                        transform=ax.transAxes, ha="center", va="center",
                        color=TEXT_DIM, fontsize=12)
                _style_ax(ax, f"{p}  —  MTBF  (target {tgt_lbl})",
                          ylabel="MTBF (Hours)")
                self._figs[f"mtbf_{p}"] = fig
                cv = FigureCanvasTkAgg(fig, inner)
                cv.draw()
                cv.get_tk_widget().pack(fill="x", expand=False, pady=(0, 6))
                continue

            # Weekly failure counts — every CM in that week is a failure
            weekly_count = (sub.groupby("week").size()
                            .reindex(all_weeks).fillna(0).astype(int))
            counts = weekly_count.values

            # Weekly MTBF = operating_hrs_this_week / failures_this_week
            safe_counts = np.where(counts > 0, counts, 1)
            weekly_mtbf = np.where(counts > 0, ophrs_pw / safe_counts, np.nan)

            # Cumulative MTBF = total_operating_hrs_elapsed / total_failures_so_far
            cum_ophrs    = ophrs_pw * (x + 1)
            cum_failures = np.cumsum(counts).astype(float)
            cum_failures[cum_failures == 0] = np.nan
            safe_cum     = np.where(~np.isnan(cum_failures), cum_failures, 1)
            cum_mtbf     = np.where(~np.isnan(cum_failures),
                                    cum_ophrs / safe_cum, np.nan)

            # Bar colours: ≥ target → green (good), < target → red (bad)
            # Note: do NOT use priority colour here — P1's colour is red which
            # would make above-target bars look like failures.
            bar_colors = []
            for v in weekly_mtbf:
                if np.isnan(v):    bar_colors.append(BG3)
                elif v >= target:  bar_colors.append(SUCCESS)
                else:              bar_colors.append(DANGER)

            ax.bar(x, np.nan_to_num(weekly_mtbf), width=0.6,
                   color=bar_colors, alpha=0.88, zorder=3,
                   edgecolor=BG3, linewidth=0.5)

            # Label above each bar: MTBF value + failure count
            for xi, (val, cnt) in enumerate(zip(weekly_mtbf, counts)):
                if np.isnan(val) or cnt == 0:
                    continue
                bar_h = float(np.nan_to_num(val))
                ax.text(xi, bar_h + 0.5,
                        f"{val:.1f}h\nn={cnt}", ha="center", va="bottom",
                        fontsize=6.5, color=TEXT, fontweight="bold",
                        zorder=6, linespacing=1.3)

            # Cumulative MTBF overlay line
            valid_cum = ~np.isnan(cum_mtbf)
            if valid_cum.sum() >= 2:
                ax.plot(x[valid_cum], cum_mtbf[valid_cum],
                        color=ACCENT2, linewidth=2.2, linestyle="-",
                        marker="o", markersize=3.5, zorder=8, alpha=0.9,
                        label="Cumulative MTBF")

            # Target line (green — higher is better for MTBF)
            ax.axhline(target, color=SUCCESS, linewidth=2.0,
                       linestyle="--", alpha=0.9, zorder=7)
            ax.text(n_weeks - 0.5, target,
                    f" Target {tgt_lbl}", color=SUCCESS,
                    fontsize=8, va="bottom", ha="right", fontweight="bold")

            # Trend line on weekly MTBF
            has_data   = ~np.isnan(weekly_mtbf)
            x_data     = x[has_data].astype(float)
            y_data     = weekly_mtbf[has_data]
            trend_line = None
            if len(x_data) >= 2:
                slope     = np.polyfit(x_data, y_data, 1)[0]
                t_color   = SUCCESS if slope > 0 else DANGER
                direction = "improving ↑" if slope > 0 else "worsening ↓"
                if len(x_data) >= 4:
                    k      = min(3, len(x_data) - 1)
                    spline = make_interp_spline(x_data, y_data, k=k)
                    xs     = np.linspace(x_data[0], x_data[-1], 300)
                    ys     = np.clip(spline(xs), 0, None)
                else:
                    xs, ys = x_data, y_data
                ax.plot(xs, ys, color=t_color, linewidth=1.8,
                        linestyle=":", zorder=9,
                        marker="o" if len(x_data) < 4 else None, markersize=3)
                trend_line = mlines.Line2D([], [], color=t_color, linewidth=1.8,
                                           linestyle=":", label=f"Trend ({direction})")

            # Overall MTBF badge
            total_failures = int(counts.sum())
            total_ophrs_elapsed = ophrs_pw * n_weeks
            overall_mtbf = (total_ophrs_elapsed / total_failures
                            if total_failures > 0 else 0)
            badge_c = SUCCESS if overall_mtbf >= target else DANGER
            ax.text(0.01, 0.97,
                    (f"Overall MTBF: {overall_mtbf:.1f} h  |  "
                     f"Total failures: {total_failures}  |  "
                     f"Monthly op. time: {monthly_ophrs:,} h  "
                     f"({ophrs_pw:.0f} h/wk)  |  Target: {tgt_lbl}"),
                    transform=ax.transAxes, ha="left", va="top",
                    fontsize=8.5, color=badge_c, fontweight="bold",
                    bbox=dict(facecolor=BG3, alpha=0.75, pad=3, edgecolor=badge_c))

            # Legend
            good_patch = mpatches.Patch(facecolor=SUCCESS, alpha=0.88,
                                        label="Weekly MTBF (≥ target)")
            bad_patch  = mpatches.Patch(facecolor=DANGER, alpha=0.88,
                                        label="Weekly MTBF (< target)")
            tgt_line   = mlines.Line2D([], [], color=SUCCESS, linewidth=2.0,
                                       linestyle="--", label=f"KPI Target {tgt_lbl}")
            cum_line   = mlines.Line2D([], [], color=ACCENT2, linewidth=2.2,
                                       linestyle="-", marker="o", markersize=3.5,
                                       label="Cumulative MTBF")
            handles = [good_patch, bad_patch, tgt_line, cum_line]
            if trend_line:
                handles.append(trend_line)
            ax.legend(handles=handles, facecolor=PLOT_BG, labelcolor=TEXT,
                      fontsize=7.5, loc="upper right", framealpha=0.85,
                      handlelength=1.4, handletextpad=0.5)

            ax.set_xticks(x)
            ax.set_xticklabels(week_labels, fontsize=6.5, rotation=40, ha="right")
            ax.set_xlim(-0.7, n_weeks - 0.3)
            ax.set_ylim(0)
            ax.grid(axis="y", color=GRID_C, linewidth=0.4, alpha=0.5, zorder=0)
            _style_ax(ax,
                      (f"{p}  —  Weekly MTBF  |  Target {tgt_lbl}  |  "
                       f"Monthly Operating Time: {monthly_ophrs:,} h{station_suffix}"),
                      ylabel="MTBF (Hours)")

            self._figs[f"mtbf_{p}"] = fig
            cv = FigureCanvasTkAgg(fig, inner)
            cv.draw()
            cv.get_tk_widget().pack(fill="x", expand=False, pady=(0, 6))


# ─── Top Breakdown View ────────────────────────────────────────────────────────

# Root cause colour map — consistent across all 4 charts
RC_COLORS = {
    "Electrical":  "#4f8ef7",
    "Mechanical":  "#f7a24f",
    "Hydraulic":   "#4fc87a",
    "Pneumatic":   "#c84fc8",
    "Other":       "#7e8ab0",
    "Unknown":     "#3a4060",
}

class TopBreakdownView(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=BG2)
        self._figs = {}
        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg=BG2)
        hdr.pack(fill="x", padx=16, pady=(12, 0))
        tk.Label(hdr, text="📊  Top Breakdown — Root Cause Pareto by Priority",
                 bg=BG2, fg=TEXT, font=FONT_TITLE).pack(side="left")

        ff = tk.Frame(hdr, bg=BG2); ff.pack(side="left", padx=20)
        for lbl_txt, attr, opts in [
            ("Month:", "month_var", ["All"] + MONTHS),
            ("Year:",  "year_var",
             ["All"] + [str(y) for y in range(2024, datetime.now().year + 2)]),
        ]:
            tk.Label(ff, text=lbl_txt, bg=BG2, fg=TEXT_DIM,
                     font=FONT_BODY).pack(side="left", padx=(10, 2))
            v = tk.StringVar()
            setattr(self, attr, v)
            cb = ttk.Combobox(ff, textvariable=v, values=opts, width=11,
                              font=FONT_BODY, state="readonly")
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>", lambda _: self.render())

        self.month_var.set("All")
        self.year_var.set(str(datetime.now().year))

        tk.Label(ff, text="Station:", bg=BG2, fg=TEXT_DIM,
                 font=FONT_BODY).pack(side="left", padx=(14, 2))
        self.station_var = tk.StringVar(value="All")
        self.station_cb  = ttk.Combobox(ff, textvariable=self.station_var,
                                        values=["All"], width=18,
                                        font=FONT_BODY, state="readonly")
        self.station_cb.pack(side="left")
        self.station_cb.bind("<<ComboboxSelected>>", lambda _: self.render())
        self._refresh_stations()

        tk.Button(hdr, text="  🔄 Refresh  ", bg=ACCENT, fg="white",
                  relief="flat", font=FONT_BODY, cursor="hand2",
                  padx=8, pady=5, command=self.render).pack(side="right", padx=4)
        tk.Button(hdr, text="  📥 Export PNG  ", bg=ACCENT2, fg="white",
                  relief="flat", font=FONT_SMALL, cursor="hand2",
                  padx=8, pady=5, command=self._export_all).pack(side="right", padx=4)

        # Legend strip
        leg = tk.Frame(self, bg=BG3, highlightthickness=1, highlightbackground=SEP)
        leg.pack(fill="x", padx=16, pady=(6, 0))
        tk.Label(leg, text="  Root Cause Colours:  ", bg=BG3, fg=TEXT_DIM,
                 font=FONT_SMALL).pack(side="left", padx=(4, 0), pady=4)
        for rc, col in RC_COLORS.items():
            dot = tk.Frame(leg, bg=col, width=12, height=12)
            dot.pack(side="left", padx=(6, 2), pady=6)
            tk.Label(leg, text=rc, bg=BG3, fg=TEXT, font=FONT_SMALL).pack(
                side="left", padx=(0, 6))

        self._scroll_outer = tk.Frame(self, bg=BG2)
        self._scroll_outer.pack(fill="both", expand=True, padx=4, pady=6)
        tk.Label(self._scroll_outer, text="Click  🔄 Refresh  to load charts",
                 bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 13)).pack(expand=True)

    def _refresh_stations(self):
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT UPPER(TRIM(station)) AS s FROM cms "
                "WHERE station IS NOT NULL AND TRIM(station) != \'\' ORDER BY s"
            ).fetchall()
        stations = ["All"] + [r["s"] for r in rows]
        self.station_cb.configure(values=stations)
        if self.station_var.get() not in stations:
            self.station_var.set("All")

    def _get_data(self):
        q = "SELECT * FROM cms WHERE 1=1"
        params = []
        m = self.month_var.get()
        if m != "All":
            mi = str(MONTHS.index(m) + 1).zfill(2)
            q += " AND strftime(\'%m\', date) = ?"; params.append(mi)
        y = self.year_var.get()
        if y != "All":
            q += " AND strftime(\'%Y\', date) = ?"; params.append(y)
        st = self.station_var.get()
        if st != "All":
            q += " AND UPPER(TRIM(station)) = ?"; params.append(st)
        with get_conn() as conn:
            return pd.read_sql(q, conn, params=params)

    def _export_all(self):
        if not self._figs:
            messagebox.showwarning("Nothing to Export",
                                   "No charts to export. Click Refresh first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf")],
            title="Export Top Breakdown Charts — choose base filename")
        if not path: return
        base, ext = os.path.splitext(path)
        saved = []
        for key, fig in self._figs.items():
            out = f"{base}_{key}{ext}"
            fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG2)
            saved.append(os.path.basename(out))
        messagebox.showinfo("Exported",
                            f"Saved {len(saved)} charts:\n" + "\n".join(saved))

    def render(self):
        self._refresh_stations()
        for w in self._scroll_outer.winfo_children():
            w.destroy()
        for fig in self._figs.values():
            plt.close(fig)
        self._figs.clear()

        v_scroll  = ttk.Scrollbar(self._scroll_outer, orient="vertical")
        v_scroll.pack(side="right", fill="y")
        scroll_cv = tk.Canvas(self._scroll_outer, bg=BG2, highlightthickness=0,
                              yscrollcommand=v_scroll.set)
        scroll_cv.pack(side="left", fill="both", expand=True)
        v_scroll.config(command=scroll_cv.yview)
        inner    = tk.Frame(scroll_cv, bg=BG2)
        inner_id = scroll_cv.create_window((0, 0), window=inner, anchor="nw")
        scroll_cv.bind("<Configure>",
                       lambda e: scroll_cv.itemconfig(inner_id, width=e.width))
        inner.bind("<Configure>",
                   lambda e: scroll_cv.configure(scrollregion=scroll_cv.bbox("all")))
        scroll_cv.bind_all("<MouseWheel>",
                           lambda e: scroll_cv.yview_scroll(-1*(e.delta//120), "units"))

        raw = self._get_data()
        if raw.empty:
            tk.Label(inner, text="No CM records found for the selected filters.",
                     bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 13)).pack(expand=True, pady=40)
            return

        df = _parse_datetimes(raw)
        df["root_cause"] = (df["root_cause"].fillna("").str.strip().replace("", "Unknown"))
        known = set(RC_COLORS.keys())
        df["root_cause"] = df["root_cause"].apply(lambda v: v if v in known else "Other")

        parts = [f"{self.month_var.get()} {self.year_var.get()}"]
        if self.station_var.get() != "All":
            parts.append(self.station_var.get())
        period = "  ·  ".join(parts)

        plt.style.use("dark_background")

        for p in PRIO_ORDER:
            sub     = df[df["criticality"] == p].copy()
            n_total = len(sub)

            # 3 panels: [Pareto chart | Root cause table | Station table]
            fig, (ax, ax_rc, ax_st) = plt.subplots(
                1, 3, figsize=(16, 4.6), facecolor=BG2,
                gridspec_kw={"width_ratios": [3, 1.1, 1.3], "wspace": 0.32})
            fig.patch.set_facecolor(BG2)
            fig.subplots_adjust(left=0.04, right=0.98, top=0.84, bottom=0.22)
            axr = ax.twinx()

            if sub.empty:
                ax.set_facecolor(PLOT_BG)
                ax.text(0.5, 0.5, f"No {p} CMs in selected period",
                        transform=ax.transAxes, ha="center", va="center",
                        color=TEXT_DIM, fontsize=12)
                ax_rc.set_visible(False)
                ax_st.set_visible(False)
                _style_ax(ax, f"{p}  —  Root Cause Pareto  |  {period}", ylabel="Count")
            else:
                # ── Root cause Pareto bars ────────────────────────────────────
                rc_counts = sub["root_cause"].value_counts()
                rc_labels = rc_counts.index.tolist()
                rc_vals   = rc_counts.values
                cum_pct   = rc_counts.cumsum() / rc_counts.sum() * 100
                xr        = np.arange(len(rc_labels))
                bar_cols  = [RC_COLORS.get(rc, RC_COLORS["Other"]) for rc in rc_labels]

                bars = ax.bar(xr, rc_vals, color=bar_cols, alpha=0.88, zorder=3,
                              width=0.55, edgecolor=BG3, linewidth=0.6)

                for b, v in zip(bars, rc_vals):
                    ax.text(b.get_x() + b.get_width()/2, b.get_height() + 0.15,
                            str(int(v)), ha="center", va="bottom",
                            fontsize=8.5, color=TEXT, fontweight="bold", zorder=5)

                axr.plot(xr, cum_pct.values, color=ACCENT2, marker="o",
                         markersize=5, linewidth=2.2, zorder=4, alpha=0.95)
                axr.axhline(80, color=TEXT_DIM, linestyle="--", linewidth=1,
                            alpha=0.55, zorder=3)
                axr.text(len(xr)-0.5, 81, " 80%", color=TEXT_DIM,
                         fontsize=7, va="bottom", ha="right")
                axr.set_ylim(0, 115)
                axr.set_ylabel("Cumulative %", color=TEXT_DIM, fontsize=8)
                axr.tick_params(colors=TEXT_DIM, labelsize=8)
                for sp in axr.spines.values(): sp.set_edgecolor(GRID_C)

                ax.set_xticks(xr)
                ax.set_xticklabels(rc_labels, fontsize=9, rotation=25, ha="right")
                ax.set_xlim(-0.6, len(xr)-0.4)
                ax.set_ylim(0)
                ax.grid(axis="y", color=GRID_C, linewidth=0.4, alpha=0.5, zorder=0)
                _style_ax(ax, f"{p}  —  Root Cause Pareto  |  {period}", ylabel="Count")

                # ── Middle panel: Root Cause table ────────────────────────────
                n_rc = len(rc_labels)
                ax_rc.set_facecolor(PLOT_BG)
                ax_rc.set_xlim(0, 1)
                ax_rc.set_ylim(-0.5, n_rc + 0.8)
                ax_rc.axis("off")
                ax_rc.set_title("Root Cause", color=ACCENT, fontsize=8,
                                fontweight="bold", pad=6)

                # Column headers
                ax_rc.text(0.60, n_rc+0.5, "n",   fontsize=7.5, color=ACCENT,
                           fontweight="bold", va="center", ha="center")
                ax_rc.text(0.87, n_rc+0.5, "%",   fontsize=7.5, color=ACCENT,
                           fontweight="bold", va="center", ha="center")

                for ri, (rc, cnt) in enumerate(zip(rc_labels, rc_vals)):
                    y_pos  = n_rc - ri - 0.3
                    pct    = cnt / n_total * 100
                    rc_col = RC_COLORS.get(rc, RC_COLORS["Other"])
                    # Colour swatch
                    ax_rc.add_patch(plt.Rectangle(
                        (0.01, y_pos-0.28), 0.07, 0.52,
                        facecolor=rc_col, alpha=0.85,
                        transform=ax_rc.transData))
                    ax_rc.text(0.12, y_pos+0.06, rc, fontsize=7.5,
                               color=TEXT, va="center")
                    ax_rc.text(0.60, y_pos+0.06, str(int(cnt)), fontsize=7.5,
                               color=TEXT, va="center", ha="center",
                               fontweight="bold")
                    ax_rc.text(0.87, y_pos+0.06, f"{pct:.1f}%", fontsize=7.5,
                               color=TEXT_DIM, va="center", ha="center")

                # ── Right panel: Station table ─────────────────────────────────
                st_counts = (sub["station"].str.strip().str.upper()
                             .value_counts().head(12))
                n_st = len(st_counts)

                ax_st.set_facecolor(PLOT_BG)
                ax_st.set_xlim(0, 1)
                ax_st.set_ylim(-0.5, max(n_st, 1) + 0.8)
                ax_st.axis("off")
                ax_st.set_title("Station Breakdown", color=ACCENT, fontsize=8,
                                fontweight="bold", pad=6)

                # Column headers
                ax_st.text(0.62, n_st+0.5, "n",   fontsize=7.5, color=ACCENT,
                           fontweight="bold", va="center", ha="center")
                ax_st.text(0.87, n_st+0.5, "%",   fontsize=7.5, color=ACCENT,
                           fontweight="bold", va="center", ha="center")

                # Colour scale: most failures = priority colour, fewer = dimmer
                for si, (station, cnt) in enumerate(st_counts.items()):
                    y_pos = n_st - si - 0.3
                    pct   = cnt / n_total * 100
                    # Rank-based alpha: top station full, others fade slightly
                    alpha = max(0.4, 1.0 - si * 0.07)
                    ax_st.add_patch(plt.Rectangle(
                        (0.01, y_pos-0.28), 0.07, 0.52,
                        facecolor=PRIO_COLORS[p], alpha=alpha,
                        transform=ax_st.transData))
                    ax_st.text(0.12, y_pos+0.06,
                               station[:18] + ("…" if len(station) > 18 else ""),
                               fontsize=7, color=TEXT, va="center")
                    ax_st.text(0.62, y_pos+0.06, str(int(cnt)), fontsize=7.5,
                               color=TEXT, va="center", ha="center",
                               fontweight="bold")
                    ax_st.text(0.87, y_pos+0.06, f"{pct:.1f}%", fontsize=7.5,
                               color=TEXT_DIM, va="center", ha="center")

            self._figs[f"breakdown_{p}"] = fig
            cv = FigureCanvasTkAgg(fig, inner)
            cv.draw()
            cv.get_tk_widget().pack(fill="x", expand=False, pady=(0, 6))

# ─── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardView(tk.Frame):
    def __init__(self, master, on_edit_cb=None):
        super().__init__(master, bg=BG2)
        self.on_edit_cb = on_edit_cb
        self._build()
        self.refresh()

    def _build(self):
        tk.Label(self, text="🏠  Dashboard", bg=BG2, fg=TEXT,
                 font=FONT_TITLE).pack(padx=20, pady=(16,4), anchor="w")

        self.stats_frame = tk.Frame(self, bg=BG2)
        self.stats_frame.pack(fill="x", padx=20, pady=8)

        self.recent_frame = tk.Frame(self, bg=BG2)
        self.recent_frame.pack(fill="both", expand=True, padx=20, pady=8)

        hdr = tk.Frame(self.recent_frame, bg=BG2)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Recent CMs (last 10)",
                 bg=BG2, fg=ACCENT, font=FONT_HEADER).pack(side="left")
        tk.Label(hdr, text="  ✏  Double-click any row to edit",
                 bg=BG2, fg=TEXT_DIM, font=FONT_SMALL).pack(side="left", padx=10)

        style = ttk.Style()
        style.configure("Dash.Treeview",
            background=BG3, foreground=TEXT, fieldbackground=BG3,
            rowheight=22, font=FONT_SMALL)
        style.configure("Dash.Treeview.Heading",
            background=BG, foreground=ACCENT, font=FONT_SMALL)
        style.map("Dash.Treeview",
            background=[("selected",ACCENT)], foreground=[("selected","white")])

        cols = ("Date","Time","Station","Andon","Priority","Comments")
        self.rt = ttk.Treeview(self.recent_frame, columns=cols,
                               show="headings", style="Dash.Treeview", height=10)
        for c, w in zip(cols, [85,75,110,70,60,350]):
            self.rt.heading(c, text=c)
            self.rt.column(c, width=w)
        self.rt.pack(fill="both", expand=True, pady=4)
        self.rt.bind("<Double-1>", self._on_double_click)

    def _on_double_click(self, event):
        sel = self.rt.selection()
        if not sel:
            return
        rid = int(sel[0])
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM cms WHERE id=?", (rid,)).fetchone()
        if not row:
            return
        def _after_edit():
            self.refresh()
            if self.on_edit_cb:
                self.on_edit_cb()
        EditDialog(self, row, _after_edit)

    def refresh(self):
        for w in self.stats_frame.winfo_children(): w.destroy()

        with get_conn() as conn:
            total   = conn.execute("SELECT COUNT(*) FROM cms").fetchone()[0]
            today   = conn.execute(
                "SELECT COUNT(*) FROM cms WHERE date=?", (now_date(),)).fetchone()[0]
            open_cm = conn.execute(
                "SELECT COUNT(*) FROM cms WHERE resolved_date='' OR resolved_date IS NULL"
                ).fetchone()[0]
            this_m  = conn.execute(
                "SELECT COUNT(*) FROM cms WHERE strftime('%Y-%m',date)=?",
                (datetime.now().strftime("%Y-%m"),)).fetchone()[0]
            p1      = conn.execute(
                "SELECT COUNT(*) FROM cms WHERE criticality='P1'").fetchone()[0]
            high_a  = conn.execute(
                "SELECT COUNT(*) FROM cms WHERE upper(andon)='HIGH'").fetchone()[0]

        stats = [
            ("Total CMs", str(total),    ACCENT,   "📋"),
            ("This Month", str(this_m),  ACCENT2,  "📅"),
            ("Today",      str(today),   SUCCESS,  "🕐"),
            ("Open/Unresolved", str(open_cm), DANGER, "⚠️"),
            ("P1 Critical", str(p1),     DANGER,   "🔴"),
            ("High Andon",  str(high_a), ACCENT2,  "🔥"),
        ]
        for icon, value, color, emoji in stats:
            card = tk.Frame(self.stats_frame, bg=BG3,
                            highlightthickness=1, highlightbackground=color,
                            padx=18, pady=12)
            card.pack(side="left", padx=6, ipadx=4, ipady=2)
            tk.Label(card, text=emoji, bg=BG3, fg=color,
                     font=("Segoe UI",18)).pack()
            tk.Label(card, text=value, bg=BG3, fg=color,
                     font=("Segoe UI",22,"bold")).pack()
            tk.Label(card, text=icon, bg=BG3, fg=TEXT_DIM,
                     font=FONT_SMALL).pack()

        for row in self.rt.get_children(): self.rt.delete(row)
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id,date,time,station,andon,criticality,comments "
                "FROM cms ORDER BY date DESC, time DESC LIMIT 10"
            ).fetchall()
        for r in rows:
            self.rt.insert("", "end", iid=str(r["id"]), values=(
                r["date"], _fmt_time_12h(r["time"]), r["station"],
                r["andon"], r["criticality"],
                (r["comments"][:80]+"…") if len(r["comments"] or "")>80 else r["comments"]))

# ─── Main App ──────────────────────────────────────────────────────────────────

class CMApp(tk.Tk):
    def __init__(self):
        super().__init__()
        init_db()
        self.title("CM Manager — Corrective Maintenance Tracker")
        self.geometry("1280x760")
        self.minsize(1000, 600)
        self.configure(bg=BG)
        self._import_existing()
        self._build()

    def _import_existing(self):
        """Auto-import CM_Manager.xlsx if database is empty."""
        src = "/mnt/project/CM_Manager.xlsx"
        if not os.path.exists(src): return
        with get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM cms").fetchone()[0]
        if count > 0: return
        try:
            xl = pd.ExcelFile(src)
            for sheet in xl.sheet_names:
                df = pd.read_excel(src, sheet_name=sheet)
                _import_df(df, get_conn, sheet=sheet)
        except Exception as e:
            print(f"Auto-import warning: {e}")

    def _build(self):
        # ── Sidebar
        sidebar = tk.Frame(self, bg=BG, width=190)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="⚙️", bg=BG, fg=ACCENT,
                 font=("Segoe UI",28)).pack(pady=(20,2))
        tk.Label(sidebar, text="CM Manager", bg=BG, fg=TEXT,
                 font=("Segoe UI",13,"bold")).pack()
        tk.Label(sidebar, text="Corrective Maintenance", bg=BG, fg=TEXT_DIM,
                 font=("Segoe UI",8)).pack(pady=(0,20))

        ttk.Separator(sidebar, orient="horizontal").pack(fill="x", padx=10, pady=4)

        self._nav_buttons = {}
        self._active_tab  = tk.StringVar(value="dashboard")
        nav_items = [
            ("🏠", "Dashboard",      "dashboard"),
            ("➕", "New CM",         "new"),
            ("📋", "All Records",    "records"),
            ("📊", "Analytics",      "analytics"),
            ("⏱",  "MTBF",           "mtbf"),
            ("📈", "Top Breakdown",  "breakdown"),
            ("📥", "Import",         "import_"),
        ]
        for icon, lbl, key in nav_items:
            btn = tk.Button(sidebar, text=f"  {icon}  {lbl}",
                            bg=BG, fg=TEXT_DIM, relief="flat",
                            font=FONT_BODY, anchor="w", cursor="hand2",
                            padx=10, pady=10,
                            command=lambda k=key: self._switch(k))
            btn.pack(fill="x", padx=8, pady=2)
            self._nav_buttons[key] = btn

        # Version / db path
        tk.Label(sidebar, text=f"DB: {os.path.basename(DB_FILE)}",
                 bg=BG, fg=TEXT_DIM, font=("Segoe UI",7),
                 wraplength=160).pack(side="bottom", pady=12)

        # ── Main content area
        self._content = tk.Frame(self, bg=BG2)
        self._content.pack(side="right", fill="both", expand=True)

        self._pages = {}
        self._dashboard = DashboardView(self._content, on_edit_cb=self._after_save)
        self._pages["dashboard"] = self._dashboard

        self._analytics = AnalyticsView(self._content)
        self._pages["analytics"] = self._analytics

        self._records = RecordsView(self._content)
        self._pages["records"] = self._records

        self._entry = EntryForm(self._content, self._after_save)
        self._pages["new"] = self._entry

        self._import_view = ImportView(self._content, self._after_import)
        self._pages["import_"] = self._import_view

        self._mtbf = MTBFView(self._content)
        self._pages["mtbf"] = self._mtbf

        self._breakdown = TopBreakdownView(self._content)
        self._pages["breakdown"] = self._breakdown

        self._switch("dashboard")

    def _switch(self, key):
        for p in self._pages.values(): p.pack_forget()
        self._pages[key].pack(fill="both", expand=True)
        self._active_tab.set(key)
        for k, btn in self._nav_buttons.items():
            btn.configure(
                bg=ACCENT if k==key else BG,
                fg="white" if k==key else TEXT_DIM)

    def _after_save(self):
        # Reset all Records filters so the newly saved record is always visible
        self._records.prio_var.set("All")
        for lbl, (btn, afg, abg) in self._records._prio_btns.items():
            btn.configure(
                bg=ACCENT if lbl == "All" else BG3,
                fg="white" if lbl == "All" else TEXT_DIM,
                relief="flat", highlightthickness=0)
        self._records.station_var.set("All")
        self._records.month_var.set("All")
        self._records.year_var.set(str(datetime.now().year))
        self._records.search_var.set("")
        self._records.load()
        self._dashboard.refresh()
        self._analytics.render_all()
        self._mtbf.render()
        self._breakdown.render()

    def _after_import(self):
        self._records.load()
        self._dashboard.refresh()
        self._analytics.render_all()
        self._mtbf.render()
        self._breakdown.render()

# ─── Embeddable Panel (for integration into AIT_CMMS_REV3) ────────────────────

class CMManagerPanel(tk.Frame):
    """Self-contained CM Manager that lives inside any parent widget/tab."""

    def __init__(self, master):
        super().__init__(master, bg=BG)
        init_db()
        self._build()

    def _build(self):
        # ── Sidebar
        sidebar = tk.Frame(self, bg=BG, width=190)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="⚙️", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 28)).pack(pady=(20, 2))
        tk.Label(sidebar, text="CM Manager", bg=BG, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack()
        tk.Label(sidebar, text="Corrective Maintenance", bg=BG, fg=TEXT_DIM,
                 font=("Segoe UI", 8)).pack(pady=(0, 20))

        ttk.Separator(sidebar, orient="horizontal").pack(fill="x", padx=10, pady=4)

        self._nav_buttons = {}
        self._active_tab = tk.StringVar(value="dashboard")
        nav_items = [
            ("🏠", "Dashboard",     "dashboard"),
            ("➕", "New CM",        "new"),
            ("📋", "All Records",   "records"),
            ("📊", "Analytics",     "analytics"),
            ("⏱",  "MTBF",          "mtbf"),
            ("📈", "Top Breakdown", "breakdown"),
            ("📥", "Import",        "import_"),
        ]
        for icon, lbl, key in nav_items:
            btn = tk.Button(sidebar, text=f"  {icon}  {lbl}",
                            bg=BG, fg=TEXT_DIM, relief="flat",
                            font=FONT_BODY, anchor="w", cursor="hand2",
                            padx=10, pady=10,
                            command=lambda k=key: self._switch(k))
            btn.pack(fill="x", padx=8, pady=2)
            self._nav_buttons[key] = btn

        tk.Label(sidebar, text=f"DB: {os.path.basename(DB_FILE)}",
                 bg=BG, fg=TEXT_DIM, font=("Segoe UI", 7),
                 wraplength=160).pack(side="bottom", pady=12)

        # ── Main content area
        self._content = tk.Frame(self, bg=BG2)
        self._content.pack(side="right", fill="both", expand=True)

        self._pages = {}
        self._dashboard = DashboardView(self._content, on_edit_cb=self._after_save)
        self._pages["dashboard"] = self._dashboard

        self._analytics = AnalyticsView(self._content)
        self._pages["analytics"] = self._analytics

        self._records = RecordsView(self._content)
        self._pages["records"] = self._records

        self._entry = EntryForm(self._content, self._after_save)
        self._pages["new"] = self._entry

        self._import_view = ImportView(self._content, self._after_import)
        self._pages["import_"] = self._import_view

        self._mtbf = MTBFView(self._content)
        self._pages["mtbf"] = self._mtbf

        self._breakdown = TopBreakdownView(self._content)
        self._pages["breakdown"] = self._breakdown

        self._switch("dashboard")

    def _switch(self, key):
        for p in self._pages.values():
            p.pack_forget()
        self._pages[key].pack(fill="both", expand=True)
        self._active_tab.set(key)
        for k, btn in self._nav_buttons.items():
            btn.configure(
                bg=ACCENT if k == key else BG,
                fg="white" if k == key else TEXT_DIM)

    def _after_save(self):
        self._records.prio_var.set("All")
        for lbl, (btn, afg, abg) in self._records._prio_btns.items():
            btn.configure(
                bg=ACCENT if lbl == "All" else BG3,
                fg="white" if lbl == "All" else TEXT_DIM,
                relief="flat", highlightthickness=0)
        self._records.station_var.set("All")
        self._records.month_var.set("All")
        self._records.year_var.set(str(datetime.now().year))
        self._records.search_var.set("")
        self._records.load()
        self._dashboard.refresh()
        self._analytics.render_all()
        self._mtbf.render()
        self._breakdown.render()

    def _after_import(self):
        self._records.load()
        self._dashboard.refresh()
        self._analytics.render_all()
        self._mtbf.render()
        self._breakdown.render()


if __name__ == "__main__":
    app = CMApp()
    app.mainloop()
