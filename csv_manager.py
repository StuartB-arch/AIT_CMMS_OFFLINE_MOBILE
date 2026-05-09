"""
csv_manager.py — AIT CMMS CSV Integration
Handles bidirectional sync between PM_MASTER_2026_CLEANED.csv and the PostgreSQL database.

  startup_sync()   → reads CSV, upserts into DB (new rows + updates PM flags/dates)
  shutdown_export()→ reads DB, writes updated PM dates back to CSV
  update_equipment_pm_dates() → updates a single record after PM completion
"""
import os
import shutil
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable


CSV_FILENAME = "PM_MASTER_2026_CLEANED.csv"

# Maps CSV column headers to database column names
_CSV_TO_DB = {
    "SAP Material No":    "sap_material_no",
    "BFM Equipment No":   "bfm_equipment_no",
    "Description":        "description",
    "Tool ID/Drawing No": "tool_id_drawing_no",
    "Location":           "location",
    "Master LIN":         "master_lin",
    "Monthly PM":         "monthly_pm",
    "Six Month PM":       "six_month_pm",
    "Annual PM":          "annual_pm",
    "Last Monthly PM":    "last_monthly_pm",
    "Last Six Month PM":  "last_six_month_pm",
    "Last Annual PM":     "last_annual_pm",
    "Next Monthly PM":    "next_monthly_pm",
    "Next Six Month PM":  "next_six_month_pm",
    "Next Annual PM":     "next_annual_pm",
    "Status":             "status",
}

_PM_INTERVALS = {
    "Monthly":   ("Last Monthly PM",   "Next Monthly PM",   30),
    "Six Month": ("Last Six Month PM", "Next Six Month PM", 180),
    "Annual":    ("Last Annual PM",    "Next Annual PM",    365),
}


def _csv_path() -> Path:
    return Path(__file__).parent / CSV_FILENAME


def _parse_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes")


def _norm_date(val) -> Optional[str]:
    """Normalize date to YYYY-MM-DD string; returns None if blank/invalid."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("none", "nat", "nan", ""):
        return None
    for fmt in ("%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.split(" ")[0], fmt.split(" ")[0]).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return s  # return as-is if unparseable


def _newer(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Return the more recent of two YYYY-MM-DD date strings; None beats nothing."""
    if not a:
        return b
    if not b:
        return a
    try:
        return a if datetime.strptime(a[:10], "%Y-%m-%d") >= datetime.strptime(b[:10], "%Y-%m-%d") else b
    except ValueError:
        return a


def _fmt_date(val) -> str:
    if not val:
        return ""
    return str(val).split(" ")[0]


def _fmt_bool(val) -> str:
    return "True" if val else "False"


def _safe_str(val) -> str:
    s = str(val).strip() if val is not None else ""
    return "" if s.lower() in ("nan", "none") else s


class CSVManager:
    """Manages read/write sync between PM_MASTER_2026_CLEANED.csv and PostgreSQL."""

    def __init__(self, conn, csv_path: Optional[str] = None):
        self.conn = conn
        self.path = Path(csv_path) if csv_path else _csv_path()

    # ── Startup ──────────────────────────────────────────────────────────────

    def startup_sync(self, status_cb: Optional[Callable] = None) -> dict:
        """
        Read CSV and batch-upsert all records into the database.
        Uses a single INSERT … ON CONFLICT DO UPDATE so the entire 2 800-row
        CSV is sent in one round-trip instead of one query per row.
        PM dates are merged: whichever is more recent (DB or CSV) wins.
        Returns a result dict: {inserted, updated, skipped, errors}
        """
        from sqlite_compat import execute_values

        if not self.path.exists():
            msg = f"PM Master CSV not found: {self.path}"
            print(f"[CSVManager] WARNING: {msg}")
            return {"inserted": 0, "updated": 0, "skipped": 0, "errors": 0, "message": msg}

        if status_cb:
            status_cb("Reading PM Master CSV…")

        try:
            df = pd.read_csv(self.path, encoding="utf-8-sig", dtype=str)
            df.columns = df.columns.str.strip()
        except Exception as exc:
            print(f"[CSVManager] ERROR reading CSV: {exc}")
            return {"inserted": 0, "updated": 0, "skipped": 0, "errors": 1, "message": str(exc)}

        rows = []
        skipped = 0
        for _, row in df.iterrows():
            bfm_no = _safe_str(row.get("BFM Equipment No", ""))
            if not bfm_no:
                skipped += 1
                continue
            rows.append((
                _safe_str(row.get("SAP Material No", "")),
                bfm_no,
                _safe_str(row.get("Description", "")),
                _safe_str(row.get("Tool ID/Drawing No", "")),
                _safe_str(row.get("Location", "")),
                _safe_str(row.get("Master LIN", "")),
                _parse_bool(row.get("Monthly PM", "False")),
                _parse_bool(row.get("Six Month PM", "False")),
                _parse_bool(row.get("Annual PM", "False")),
                _norm_date(row.get("Last Monthly PM")),
                _norm_date(row.get("Last Six Month PM")),
                _norm_date(row.get("Last Annual PM")),
                _norm_date(row.get("Next Monthly PM")),
                _norm_date(row.get("Next Six Month PM")),
                _norm_date(row.get("Next Annual PM")),
                _safe_str(row.get("Status", "Active")) or "Active",
            ))

        if not rows:
            return {"inserted": 0, "updated": 0, "skipped": skipped, "errors": 0}

        if status_cb:
            status_cb(f"Syncing {len(rows)} equipment records to database…")

        try:
            cursor = self.conn.cursor()

            # Batch upsert: one round-trip for all rows.
            # For last PM dates the GREATEST() picks whichever date is more recent
            # so that PM completions recorded in the DB are never overwritten by
            # an older CSV value.
            execute_values(
                cursor,
                """
                INSERT INTO equipment (
                    sap_material_no, bfm_equipment_no, description,
                    tool_id_drawing_no, location, master_lin,
                    monthly_pm, six_month_pm, annual_pm,
                    last_monthly_pm, last_six_month_pm, last_annual_pm,
                    next_monthly_pm, next_six_month_pm, next_annual_pm,
                    status
                ) VALUES %s
                ON CONFLICT (bfm_equipment_no) DO UPDATE SET
                    sap_material_no    = EXCLUDED.sap_material_no,
                    description        = EXCLUDED.description,
                    tool_id_drawing_no = EXCLUDED.tool_id_drawing_no,
                    location           = EXCLUDED.location,
                    master_lin         = EXCLUDED.master_lin,
                    monthly_pm         = EXCLUDED.monthly_pm,
                    six_month_pm       = EXCLUDED.six_month_pm,
                    annual_pm          = EXCLUDED.annual_pm,
                    last_monthly_pm    = CASE
                                             WHEN equipment.last_monthly_pm IS NULL
                                                  THEN EXCLUDED.last_monthly_pm
                                             WHEN EXCLUDED.last_monthly_pm IS NULL
                                                  THEN equipment.last_monthly_pm
                                             WHEN equipment.last_monthly_pm > EXCLUDED.last_monthly_pm
                                                  THEN equipment.last_monthly_pm
                                             ELSE EXCLUDED.last_monthly_pm END,
                    last_six_month_pm  = CASE
                                             WHEN equipment.last_six_month_pm IS NULL
                                                  THEN EXCLUDED.last_six_month_pm
                                             WHEN EXCLUDED.last_six_month_pm IS NULL
                                                  THEN equipment.last_six_month_pm
                                             WHEN equipment.last_six_month_pm > EXCLUDED.last_six_month_pm
                                                  THEN equipment.last_six_month_pm
                                             ELSE EXCLUDED.last_six_month_pm END,
                    last_annual_pm     = CASE
                                             WHEN equipment.last_annual_pm IS NULL
                                                  THEN EXCLUDED.last_annual_pm
                                             WHEN EXCLUDED.last_annual_pm IS NULL
                                                  THEN equipment.last_annual_pm
                                             WHEN equipment.last_annual_pm > EXCLUDED.last_annual_pm
                                                  THEN equipment.last_annual_pm
                                             ELSE EXCLUDED.last_annual_pm END,
                    next_monthly_pm    = EXCLUDED.next_monthly_pm,
                    next_six_month_pm  = EXCLUDED.next_six_month_pm,
                    next_annual_pm     = EXCLUDED.next_annual_pm,
                    status             = CASE
                                             WHEN equipment.status IN ('Missing', 'Deactivated', 'Run to Failure')
                                             THEN equipment.status
                                             ELSE EXCLUDED.status
                                         END,
                    updated_date       = CURRENT_TIMESTAMP
                """,
                rows,
                page_size=500,
            )

            self.conn.commit()

            msg = f"CSV sync complete: {len(rows)} records upserted, {skipped} skipped"
            print(f"[CSVManager] {msg}")
            if status_cb:
                status_cb(msg)
            return {"inserted": len(rows), "updated": 0, "skipped": skipped, "errors": 0}

        except Exception as exc:
            print(f"[CSVManager] ERROR during batch upsert: {exc}")
            try:
                self.conn.rollback()
            except Exception:
                pass
            return {"inserted": 0, "updated": 0, "skipped": skipped, "errors": 1}

    # ── Shutdown ─────────────────────────────────────────────────────────────

    def shutdown_export(self, status_cb: Optional[Callable] = None) -> bool:
        """
        Export current database equipment state back to the CSV.
        Creates a timestamped backup of the original CSV first.
        Returns True on success.
        """
        if status_cb:
            status_cb("Exporting PM data to CSV…")

        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """SELECT sap_material_no, bfm_equipment_no, description,
                          tool_id_drawing_no, location, master_lin,
                          monthly_pm, six_month_pm, annual_pm,
                          last_monthly_pm, last_six_month_pm, last_annual_pm,
                          next_monthly_pm, next_six_month_pm, next_annual_pm,
                          status
                   FROM equipment ORDER BY id"""
            )
            rows = cursor.fetchall()
        except Exception as exc:
            print(f"[CSVManager] ERROR querying DB for export: {exc}")
            return False

        db_by_bfm = {row[1]: row for row in rows if row[1]}

        # Load existing CSV to preserve the ID column and row order
        if self.path.exists():
            try:
                existing_df = pd.read_csv(self.path, encoding="utf-8-sig", dtype=str)
                existing_df.columns = existing_df.columns.str.strip()
            except Exception as exc:
                print(f"[CSVManager] WARNING: could not read existing CSV: {exc}")
                existing_df = None
        else:
            existing_df = None

        if existing_df is not None and "BFM Equipment No" in existing_df.columns:
            # Update rows in place
            for idx, csv_row in existing_df.iterrows():
                bfm_no = _safe_str(csv_row.get("BFM Equipment No", ""))
                if bfm_no in db_by_bfm:
                    r = db_by_bfm[bfm_no]
                    existing_df.at[idx, "SAP Material No"]    = _safe_str(r[0])
                    existing_df.at[idx, "Description"]        = _safe_str(r[2])
                    existing_df.at[idx, "Tool ID/Drawing No"] = _safe_str(r[3])
                    existing_df.at[idx, "Location"]           = _safe_str(r[4])
                    existing_df.at[idx, "Master LIN"]         = _safe_str(r[5])
                    existing_df.at[idx, "Monthly PM"]         = _fmt_bool(r[6])
                    existing_df.at[idx, "Six Month PM"]       = _fmt_bool(r[7])
                    existing_df.at[idx, "Annual PM"]          = _fmt_bool(r[8])
                    existing_df.at[idx, "Last Monthly PM"]    = _fmt_date(r[9])
                    existing_df.at[idx, "Last Six Month PM"]  = _fmt_date(r[10])
                    existing_df.at[idx, "Last Annual PM"]     = _fmt_date(r[11])
                    existing_df.at[idx, "Next Monthly PM"]    = _fmt_date(r[12])
                    existing_df.at[idx, "Next Six Month PM"]  = _fmt_date(r[13])
                    existing_df.at[idx, "Next Annual PM"]     = _fmt_date(r[14])
                    existing_df.at[idx, "Status"]             = _safe_str(r[15]) or "Active"

            # Append records added via the app that aren't yet in the CSV
            existing_bfm = set(existing_df["BFM Equipment No"].str.strip().tolist())
            next_id = int(existing_df["ID"].max()) + 1 if "ID" in existing_df.columns else len(existing_df) + 1
            new_rows = []
            for bfm_no, r in db_by_bfm.items():
                if bfm_no not in existing_bfm:
                    new_rows.append({
                        "ID":                next_id,
                        "SAP Material No":   _safe_str(r[0]),
                        "BFM Equipment No":  bfm_no,
                        "Description":       _safe_str(r[2]),
                        "Tool ID/Drawing No":_safe_str(r[3]),
                        "Location":          _safe_str(r[4]),
                        "Master LIN":        _safe_str(r[5]),
                        "Monthly PM":        _fmt_bool(r[6]),
                        "Six Month PM":      _fmt_bool(r[7]),
                        "Annual PM":         _fmt_bool(r[8]),
                        "Last Monthly PM":   _fmt_date(r[9]),
                        "Last Six Month PM": _fmt_date(r[10]),
                        "Last Annual PM":    _fmt_date(r[11]),
                        "Next Monthly PM":   _fmt_date(r[12]),
                        "Next Six Month PM": _fmt_date(r[13]),
                        "Next Annual PM":    _fmt_date(r[14]),
                        "Status":            _safe_str(r[15]) or "Active",
                    })
                    next_id += 1
            if new_rows:
                existing_df = pd.concat([existing_df, pd.DataFrame(new_rows)], ignore_index=True)

            output_df = existing_df
        else:
            # Build fresh CSV from DB data
            output_rows = []
            for i, (bfm_no, r) in enumerate(db_by_bfm.items(), 1):
                output_rows.append({
                    "ID":                i,
                    "SAP Material No":   _safe_str(r[0]),
                    "BFM Equipment No":  bfm_no,
                    "Description":       _safe_str(r[2]),
                    "Tool ID/Drawing No":_safe_str(r[3]),
                    "Location":          _safe_str(r[4]),
                    "Master LIN":        _safe_str(r[5]),
                    "Monthly PM":        _fmt_bool(r[6]),
                    "Six Month PM":      _fmt_bool(r[7]),
                    "Annual PM":         _fmt_bool(r[8]),
                    "Last Monthly PM":   _fmt_date(r[9]),
                    "Last Six Month PM": _fmt_date(r[10]),
                    "Last Annual PM":    _fmt_date(r[11]),
                    "Next Monthly PM":   _fmt_date(r[12]),
                    "Next Six Month PM": _fmt_date(r[13]),
                    "Next Annual PM":    _fmt_date(r[14]),
                    "Status":            _safe_str(r[15]) or "Active",
                })
            output_df = pd.DataFrame(output_rows)

        # Keep exactly one rolling backup (overwrite it each time)
        if self.path.exists():
            backup = self.path.with_name(f"{self.path.stem}_backup.csv")
            try:
                shutil.copy2(self.path, backup)
                print(f"[CSVManager] Backup updated → {backup.name}")
            except Exception as exc:
                print(f"[CSVManager] WARNING: backup failed: {exc}")

        try:
            output_df.to_csv(self.path, index=False, encoding="utf-8-sig")
            msg = f"CSV export complete ({len(output_df)} records) → {self.path.name}"
            print(f"[CSVManager] {msg}")
            if status_cb:
                status_cb(msg)
            return True
        except Exception as exc:
            print(f"[CSVManager] ERROR writing CSV: {exc}")
            return False

    # ── Per-completion update ─────────────────────────────────────────────────

    def update_equipment_pm_dates(self, bfm_no: str, pm_type: str, completion_date: str) -> bool:
        """
        Update Last/Next PM date columns in the CSV for one equipment record.
        Called immediately after a PM completion is saved to the database.
        pm_type must be one of: 'Monthly', 'Six Month', 'Annual'
        """
        if pm_type not in _PM_INTERVALS:
            return False
        if not self.path.exists():
            return False

        try:
            df = pd.read_csv(self.path, encoding="utf-8-sig", dtype=str)
            df.columns = df.columns.str.strip()
            mask = df["BFM Equipment No"].str.strip() == bfm_no
            if not mask.any():
                return False

            last_col, next_col, days = _PM_INTERVALS[pm_type]
            comp_dt = datetime.strptime(completion_date[:10], "%Y-%m-%d")
            next_dt = comp_dt + timedelta(days=days)

            df.loc[mask, last_col] = comp_dt.strftime("%Y-%m-%d")
            df.loc[mask, next_col] = next_dt.strftime("%Y-%m-%d")
            df.to_csv(self.path, index=False, encoding="utf-8-sig")
            return True
        except Exception as exc:
            print(f"[CSVManager] ERROR updating PM dates for {bfm_no}: {exc}")
            return False

    # ── Location map ─────────────────────────────────────────────────────────

    def get_location_map(self) -> dict:
        """
        Return {bfm_no: location} for every row in the CSV.
        Used as a fast fallback when the equipment table has a blank location.
        Rows with no BFM number are skipped; rows with a blank location are
        included so callers can distinguish "not in CSV" from "CSV says blank".
        """
        if not self.path.exists():
            return {}
        try:
            df = pd.read_csv(self.path, encoding="utf-8-sig", dtype=str)
            df.columns = df.columns.str.strip()
            result = {}
            for _, row in df.iterrows():
                bfm_no = _safe_str(row.get("BFM Equipment No", ""))
                if bfm_no:
                    result[bfm_no] = _safe_str(row.get("Location", ""))
            return result
        except Exception as exc:
            print(f"[CSVManager] ERROR reading location map: {exc}")
            return {}

    # ── Single-row live sync ──────────────────────────────────────────────────

    def sync_equipment_row(self, bfm_no: str) -> bool:
        """
        Read one equipment record from the database and update (or insert)
        its row in the CSV immediately.  Called after any DB commit that
        changes PM dates, PM flags, or status for a single piece of equipment.
        Fast: one DB query + one CSV read/write.
        """
        if not self.path.exists():
            return False

        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """SELECT sap_material_no, bfm_equipment_no, description,
                          tool_id_drawing_no, location, master_lin,
                          monthly_pm, six_month_pm, annual_pm,
                          last_monthly_pm, last_six_month_pm, last_annual_pm,
                          next_monthly_pm, next_six_month_pm, next_annual_pm,
                          status
                   FROM equipment WHERE bfm_equipment_no = %s""",
                (bfm_no,),
            )
            row = cursor.fetchone()
            if not row:
                return False

            df = pd.read_csv(self.path, encoding="utf-8-sig", dtype=str)
            df.columns = df.columns.str.strip()

            mask = df["BFM Equipment No"].str.strip() == bfm_no

            def _apply(idx):
                df.at[idx, "SAP Material No"]    = _safe_str(row[0])
                df.at[idx, "Description"]        = _safe_str(row[2])
                df.at[idx, "Tool ID/Drawing No"] = _safe_str(row[3])
                df.at[idx, "Location"]           = _safe_str(row[4])
                df.at[idx, "Master LIN"]         = _safe_str(row[5])
                df.at[idx, "Monthly PM"]         = _fmt_bool(row[6])
                df.at[idx, "Six Month PM"]       = _fmt_bool(row[7])
                df.at[idx, "Annual PM"]          = _fmt_bool(row[8])
                df.at[idx, "Last Monthly PM"]    = _fmt_date(row[9])
                df.at[idx, "Last Six Month PM"]  = _fmt_date(row[10])
                df.at[idx, "Last Annual PM"]     = _fmt_date(row[11])
                df.at[idx, "Next Monthly PM"]    = _fmt_date(row[12])
                df.at[idx, "Next Six Month PM"]  = _fmt_date(row[13])
                df.at[idx, "Next Annual PM"]     = _fmt_date(row[14])
                df.at[idx, "Status"]             = _safe_str(row[15]) or "Active"

            if mask.any():
                for idx in df.index[mask]:
                    _apply(idx)
            else:
                # Equipment was added via the app — append a new row
                next_id = int(df["ID"].max()) + 1 if "ID" in df.columns else len(df) + 1
                new_row = {
                    "ID":                next_id,
                    "SAP Material No":   _safe_str(row[0]),
                    "BFM Equipment No":  bfm_no,
                    "Description":       _safe_str(row[2]),
                    "Tool ID/Drawing No":_safe_str(row[3]),
                    "Location":          _safe_str(row[4]),
                    "Master LIN":        _safe_str(row[5]),
                    "Monthly PM":        _fmt_bool(row[6]),
                    "Six Month PM":      _fmt_bool(row[7]),
                    "Annual PM":         _fmt_bool(row[8]),
                    "Last Monthly PM":   _fmt_date(row[9]),
                    "Last Six Month PM": _fmt_date(row[10]),
                    "Last Annual PM":    _fmt_date(row[11]),
                    "Next Monthly PM":   _fmt_date(row[12]),
                    "Next Six Month PM": _fmt_date(row[13]),
                    "Next Annual PM":    _fmt_date(row[14]),
                    "Status":            _safe_str(row[15]) or "Active",
                }
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

            df.to_csv(self.path, index=False, encoding="utf-8-sig")
            print(f"[CSVManager] Live sync: updated {bfm_no} in CSV")
            return True

        except Exception as exc:
            print(f"[CSVManager] ERROR sync_equipment_row({bfm_no}): {exc}")
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# MRO Stock CSV Manager
# ═══════════════════════════════════════════════════════════════════════════════

MRO_CSV_FILENAME = "MRO_STOCK.csv"

# Columns written to / read from the CSV (binary image data is excluded)
MRO_COLUMNS = [
    "part_number", "name", "model_number", "equipment", "engineering_system",
    "unit_of_measure", "quantity_in_stock", "unit_price", "minimum_stock",
    "supplier", "location", "rack", "row", "bin",
    "picture_1_path", "picture_2_path", "notes", "status", "last_updated",
]

def _mro_csv_path() -> Path:
    return Path(__file__).parent / MRO_CSV_FILENAME

def _safe_float(val) -> float:
    try:
        return float(val) if val not in (None, "", "nan", "None") else 0.0
    except (ValueError, TypeError):
        return 0.0


class MROCSVManager:
    """
    Bidirectional sync between MRO_STOCK.csv and the mro_inventory table.

      startup_sync()     → reads CSV, batch-upserts into mro_inventory
      shutdown_export()  → reads DB, writes MRO_STOCK.csv (single rolling backup)
      sync_part_row()    → live single-row update after add / edit
      remove_part_row()  → marks a row Inactive / deleted in the CSV
    """

    def __init__(self, conn, csv_path: Optional[str] = None):
        self.conn = conn
        self.path = Path(csv_path) if csv_path else _mro_csv_path()

    # ── Startup ──────────────────────────────────────────────────────────────

    def startup_sync(self, status_cb: Optional[Callable] = None) -> dict:
        """
        Read MRO_STOCK.csv and batch-upsert into mro_inventory.
        Uses INSERT … ON CONFLICT (part_number) DO UPDATE so the entire
        file is sent in one round-trip. Binary image data is NOT touched.
        """
        from sqlite_compat import execute_values

        if not self.path.exists():
            print(f"[MROCSVManager] No CSV found at {self.path} — skipping startup sync")
            return {"upserted": 0, "skipped": 0, "errors": 0}

        if status_cb:
            status_cb("Reading MRO Stock CSV…")

        try:
            df = pd.read_csv(self.path, encoding="utf-8-sig", dtype=str)
            df.columns = df.columns.str.strip()
        except Exception as exc:
            print(f"[MROCSVManager] ERROR reading CSV: {exc}")
            return {"upserted": 0, "skipped": 0, "errors": 1}

        rows = []
        skipped = 0
        for _, row in df.iterrows():
            pn = _safe_str(row.get("part_number", ""))
            if not pn:
                skipped += 1
                continue
            rows.append((
                pn,
                _safe_str(row.get("name", "")),
                _safe_str(row.get("model_number", "")),
                _safe_str(row.get("equipment", "")),
                _safe_str(row.get("engineering_system", "")),
                _safe_str(row.get("unit_of_measure", "")),
                _safe_float(row.get("quantity_in_stock", 0)),
                _safe_float(row.get("unit_price", 0)),
                _safe_float(row.get("minimum_stock", 0)),
                _safe_str(row.get("supplier", "")),
                _safe_str(row.get("location", "")),
                _safe_str(row.get("rack", "")),
                _safe_str(row.get("row", "")),
                _safe_str(row.get("bin", "")),
                _safe_str(row.get("picture_1_path", "")),
                _safe_str(row.get("picture_2_path", "")),
                _safe_str(row.get("notes", "")),
                _safe_str(row.get("status", "Active")) or "Active",
            ))

        if not rows:
            return {"upserted": 0, "skipped": skipped, "errors": 0}

        if status_cb:
            status_cb(f"Syncing {len(rows)} MRO parts to database…")

        try:
            cursor = self.conn.cursor()
            execute_values(
                cursor,
                """
                INSERT INTO mro_inventory (
                    part_number, name, model_number, equipment, engineering_system,
                    unit_of_measure, quantity_in_stock, unit_price, minimum_stock,
                    supplier, location, rack, "row", bin,
                    picture_1_path, picture_2_path, notes, status
                ) VALUES %s
                ON CONFLICT (part_number) DO UPDATE SET
                    name               = EXCLUDED.name,
                    model_number       = EXCLUDED.model_number,
                    equipment          = EXCLUDED.equipment,
                    engineering_system = EXCLUDED.engineering_system,
                    unit_of_measure    = EXCLUDED.unit_of_measure,
                    quantity_in_stock  = EXCLUDED.quantity_in_stock,
                    unit_price         = EXCLUDED.unit_price,
                    minimum_stock      = EXCLUDED.minimum_stock,
                    supplier           = EXCLUDED.supplier,
                    location           = EXCLUDED.location,
                    rack               = EXCLUDED.rack,
                    "row"              = EXCLUDED."row",
                    bin                = EXCLUDED.bin,
                    picture_1_path     = EXCLUDED.picture_1_path,
                    picture_2_path     = EXCLUDED.picture_2_path,
                    notes              = EXCLUDED.notes,
                    status             = EXCLUDED.status,
                    last_updated       = CURRENT_TIMESTAMP
                """,
                rows,
                page_size=200,
            )
            self.conn.commit()
            msg = f"MRO sync complete: {len(rows)} parts upserted"
            print(f"[MROCSVManager] {msg}")
            if status_cb:
                status_cb(msg)
            return {"upserted": len(rows), "skipped": skipped, "errors": 0}
        except Exception as exc:
            print(f"[MROCSVManager] ERROR batch upsert: {exc}")
            try:
                self.conn.rollback()
            except Exception:
                pass
            return {"upserted": 0, "skipped": skipped, "errors": 1}

    # ── Shutdown ─────────────────────────────────────────────────────────────

    def shutdown_export(self, status_cb: Optional[Callable] = None) -> bool:
        """Export all mro_inventory rows to MRO_STOCK.csv with a single rolling backup."""
        if status_cb:
            status_cb("Exporting MRO stock to CSV…")

        try:
            cursor = self.conn.cursor()
            cursor.execute(
                f"""SELECT {', '.join(f'"{c}"' if c == 'row' else c
                                      for c in MRO_COLUMNS)}
                    FROM mro_inventory ORDER BY part_number"""
            )
            rows = cursor.fetchall()
        except Exception as exc:
            print(f"[MROCSVManager] ERROR querying DB for export: {exc}")
            return False

        df = pd.DataFrame(rows, columns=MRO_COLUMNS)

        # Single rolling backup
        if self.path.exists():
            backup = self.path.with_name(f"{self.path.stem}_backup.csv")
            try:
                shutil.copy2(self.path, backup)
                print(f"[MROCSVManager] Backup updated → {backup.name}")
            except Exception as exc:
                print(f"[MROCSVManager] WARNING: backup failed: {exc}")

        try:
            df.to_csv(self.path, index=False, encoding="utf-8-sig")
            msg = f"MRO CSV export complete ({len(df)} parts) → {self.path.name}"
            print(f"[MROCSVManager] {msg}")
            if status_cb:
                status_cb(msg)
            return True
        except Exception as exc:
            print(f"[MROCSVManager] ERROR writing CSV: {exc}")
            return False

    # ── Live single-row sync ──────────────────────────────────────────────────

    def sync_part_row(self, part_number: str) -> bool:
        """Read one part from DB and update (or append) its CSV row immediately."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                f"""SELECT {', '.join(f'"{c}"' if c == 'row' else c
                                      for c in MRO_COLUMNS)}
                    FROM mro_inventory WHERE TRIM(part_number) = %s""",
                (part_number,),
            )
            db_row = cursor.fetchone()
            if not db_row:
                return False

            row_dict = dict(zip(MRO_COLUMNS, db_row))

            if self.path.exists():
                df = pd.read_csv(self.path, encoding="utf-8-sig", dtype=str)
                df.columns = df.columns.str.strip()
                mask = df["part_number"].str.strip() == part_number
                if mask.any():
                    for col in MRO_COLUMNS:
                        df.loc[mask, col] = "" if row_dict[col] is None else str(row_dict[col])
                else:
                    df = pd.concat(
                        [df, pd.DataFrame([{c: ("" if row_dict[c] is None else str(row_dict[c]))
                                            for c in MRO_COLUMNS}])],
                        ignore_index=True,
                    )
            else:
                df = pd.DataFrame([{c: ("" if row_dict[c] is None else str(row_dict[c]))
                                    for c in MRO_COLUMNS}])

            df.to_csv(self.path, index=False, encoding="utf-8-sig")
            print(f"[MROCSVManager] Live sync: updated part {part_number}")
            return True
        except Exception as exc:
            print(f"[MROCSVManager] ERROR sync_part_row({part_number}): {exc}")
            return False

    def remove_part_row(self, part_number: str) -> bool:
        """Mark a part's Status as 'Inactive' in the CSV (mirrors a soft-delete in DB)."""
        if not self.path.exists():
            return False
        try:
            df = pd.read_csv(self.path, encoding="utf-8-sig", dtype=str)
            df.columns = df.columns.str.strip()
            mask = df["part_number"].str.strip() == part_number
            if mask.any():
                df.loc[mask, "status"] = "Inactive"
                df.to_csv(self.path, index=False, encoding="utf-8-sig")
            return True
        except Exception as exc:
            print(f"[MROCSVManager] ERROR remove_part_row({part_number}): {exc}")
            return False
