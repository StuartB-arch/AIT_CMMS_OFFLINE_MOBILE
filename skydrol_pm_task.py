"""
Skydrol PM Task Module
======================
Manages the weekly combined preventive maintenance inspection for ALL
hydraulic units' Skydrol fluid level check and top-off.

Previously this module scheduled three separate weekly inspections — one
per physical unit (HYD-UNIT-001, HYD-UNIT-002, HYD-UNIT-003).  It now
schedules a SINGLE combined weekly inspection (HYD-UNITS-ALL) that covers
all three units in one task assigned to one technician.

On startup, legacy individual templates for HYD-UNIT-001/002/003 are
automatically removed from pm_templates and any open (not yet completed)
individual scheduled rows are cleared from weekly_pm_schedules.

Responsibilities
----------------
* Ensure the combined hydraulic-units equipment record exists in the
  equipment table (needed to satisfy the FK constraint on weekly_pm_schedules).
  NOTE: weekly_pm is intentionally left FALSE so the normal PM scheduler
  does NOT pick this unit up in its round-robin pool.  All scheduling is
  handled exclusively by generate_weekly_skydrol_pm().
* Create / update the single combined Skydrol PM checklist template.
* On every run: delete any open 'Scheduled' entries for this week (combined
  and legacy) and insert one fresh assignment for HYD-UNITS-ALL.
* On startup: remove legacy individual templates (one-time migration).

Designed to integrate cleanly with the existing AIT CMMS scheduling pipeline:

    from skydrol_pm_task import SkydrolPMTaskManager

    # One-time setup (safe to call every start-up)
    SkydrolPMTaskManager(conn).setup()

    # Called by generate_weekly_assignments() alongside normal PM generation
    skydrol_mgr = SkydrolPMTaskManager(conn)
    skydrol_result = skydrol_mgr.generate_weekly_skydrol_pm(
        week_start_str, available_technicians
    )
"""

import json
import random
from datetime import datetime
from typing import Dict, List

# ---------------------------------------------------------------------------
# Combined Hydraulic Unit — single equipment record for all three units
# ---------------------------------------------------------------------------
COMBINED_UNIT: Dict = {
    "bfm_equipment_no": "HYD-UNITS-ALL",
    "sap_material_no":  "96099000",
    "description":      "HYDRAULIC UNITS — ALL (HYD Unit 01 / 02 / 03)",
    "tool_id_drawing_no": "HYD-PWR-ALL",
    "location":         "LCS001 / LCS002 / LCS030/040",
}

# Legacy individual BFM numbers — kept here so the module can clean up
# their old pm_templates entries and open schedule rows automatically.
LEGACY_HYDRAULIC_UNIT_BFMS: List[str] = [
    "HYD-UNIT-001",
    "HYD-UNIT-002",
    "HYD-UNIT-003",
]

# ---------------------------------------------------------------------------
# Combined PM Checklist — Skydrol Level Inspection & Top-Off (All Units)
# ---------------------------------------------------------------------------
# Steps are grouped by physical unit so the technician can work through
# each unit in sequence without back-tracking.
# ---------------------------------------------------------------------------
SKYDROL_CHECKLIST: List[str] = [
    # --- General pre-inspection (applies to entire task) ---
    "Don required PPE before starting — chemical-resistant gloves, safety glasses "
    "or full face-shield, and a protective apron. PPE must remain on for the entire inspection.",

    # --- HYD UNIT 01 (LCS001) ---
    "HYD UNIT 01 (LCS001) — Verify unit is de-energized and hydraulic pressure is at zero "
    "before opening any lines or the reservoir.",
    "HYD UNIT 01 (LCS001) — Inspect all hydraulic lines, fittings, and seals for visible "
    "leaks or seepage.",
    "HYD UNIT 01 (LCS001) — Locate the Skydrol reservoir sight glass or level indicator; "
    "record the current fluid level status (FULL / LOW / CRITICAL) in the maintenance log.",
    "HYD UNIT 01 (LCS001) — If level is LOW or CRITICAL, confirm Skydrol grade on the unit "
    "nameplate (LD-4 or LD-5 — do NOT mix grades), then top off to the FULL mark using a "
    "clean, labeled, dedicated transfer container. Record quantity added (oz or liters).",
    "HYD UNIT 01 (LCS001) — Check hydraulic filter condition indicator; replace filter element "
    "if the bypass indicator is active.",
    "HYD UNIT 01 (LCS001) — Wipe all external surfaces with a clean lint-free cloth; "
    "re-inspect for residual spills or seepage.",

    # --- HYD UNIT 02 (LCS002) ---
    "HYD UNIT 02 (LCS002) — Verify unit is de-energized and hydraulic pressure is at zero "
    "before opening any lines or the reservoir.",
    "HYD UNIT 02 (LCS002) — Inspect all hydraulic lines, fittings, and seals for visible "
    "leaks or seepage.",
    "HYD UNIT 02 (LCS002) — Locate the Skydrol reservoir sight glass or level indicator; "
    "record the current fluid level status (FULL / LOW / CRITICAL) in the maintenance log.",
    "HYD UNIT 02 (LCS002) — If level is LOW or CRITICAL, confirm Skydrol grade on the unit "
    "nameplate (LD-4 or LD-5 — do NOT mix grades), then top off to the FULL mark using a "
    "clean, labeled, dedicated transfer container. Record quantity added (oz or liters).",
    "HYD UNIT 02 (LCS002) — Check hydraulic filter condition indicator; replace filter element "
    "if the bypass indicator is active.",
    "HYD UNIT 02 (LCS002) — Wipe all external surfaces with a clean lint-free cloth; "
    "re-inspect for residual spills or seepage.",

    # --- HYD UNIT 03 (LCS030/040) ---
    "HYD UNIT 03 (LCS030/040) — Verify unit is de-energized and hydraulic pressure is at zero "
    "before opening any lines or the reservoir.",
    "HYD UNIT 03 (LCS030/040) — Inspect all hydraulic lines, fittings, and seals for visible "
    "leaks or seepage.",
    "HYD UNIT 03 (LCS030/040) — Locate the Skydrol reservoir sight glass or level indicator; "
    "record the current fluid level status (FULL / LOW / CRITICAL) in the maintenance log.",
    "HYD UNIT 03 (LCS030/040) — If level is LOW or CRITICAL, confirm Skydrol grade on the unit "
    "nameplate (LD-4 or LD-5 — do NOT mix grades), then top off to the FULL mark using a "
    "clean, labeled, dedicated transfer container. Record quantity added (oz or liters).",
    "HYD UNIT 03 (LCS030/040) — Check hydraulic filter condition indicator; replace filter "
    "element if the bypass indicator is active.",
    "HYD UNIT 03 (LCS030/040) — Wipe all external surfaces with a clean lint-free cloth; "
    "re-inspect for residual spills or seepage.",

    # --- Post-inspection (applies to all units) ---
    "Dispose of all waste fluid, contaminated rags, and empty containers in approved "
    "hazardous-waste receptacles per the site environmental SOP.",
    "If ANY unit required more than 10 % of its reservoir capacity in a single service event, "
    "open a Corrective Maintenance (CM) ticket for root-cause investigation.",
    "Verify the AIT identification sticker is applied and legible on all three units.",
    "Confirm all tools, PPE, and materials have been collected and the work area is clean.",
    "Sign off: Date / Technician Stamp / Total Hours for this combined inspection.",
]

SKYDROL_SAFETY_NOTES: str = (
    "WARNING: Skydrol is a fire-resistant phosphate-ester hydraulic fluid and a known skin, "
    "eye, and respiratory irritant. Always wear chemical-resistant gloves, safety glasses or a "
    "full face shield, and a protective apron when handling. In case of skin or eye contact, "
    "flush immediately with large amounts of water for at least 15 minutes and seek medical "
    "attention. Consult the Skydrol Safety Data Sheet (SDS) before performing any service. "
    "Keep containers sealed when not in use to prevent moisture contamination."
)

SKYDROL_SPECIAL_INSTRUCTIONS: str = (
    "This is a COMBINED inspection covering all three hydraulic units "
    "(HYD Unit 01 — LCS001, HYD Unit 02 — LCS002, HYD Unit 03 — LCS030/040). "
    "Complete the checklist for each unit in sequence before moving to the next.\n\n"
    "1. Confirm fluid type on EACH unit's nameplate BEFORE topping off — never mix Skydrol grades.\n"
    "2. Use only dedicated, clearly labeled Skydrol transfer equipment.\n"
    "3. Keep fluid containers sealed when not in use to prevent moisture absorption.\n"
    "4. If more than 10 % of any reservoir capacity is added in a single service, escalate for "
    "root-cause investigation and open a CM ticket.\n"
    "5. Refer to the OEM hydraulic unit manual for system pressure specifications and reservoir "
    "capacity for each unit.\n"
    "6. Skydrol spills are an environmental hazard — follow site spill-response procedures."
)

# ---------------------------------------------------------------------------
# Manager Class
# ---------------------------------------------------------------------------

class SkydrolPMTaskManager:
    """
    Manages the single combined weekly Skydrol fluid-level check PM that
    covers all three hydraulic units (HYD Unit 01 / 02 / 03).

    IMPORTANT — scheduling ownership
    ---------------------------------
    The combined equipment record (HYD-UNITS-ALL) is stored in the
    ``equipment`` table with ALL pm-type flags set to FALSE.  This keeps it
    out of the normal PM scheduler's pool.  All scheduling is performed
    exclusively by ``generate_weekly_skydrol_pm()``, which produces exactly
    ONE weekly_pm_schedules row covering all three physical units.

    Parameters
    ----------
    conn : psycopg2 connection
        Active database connection (same ``self.conn`` object used by the
        main CMMS application).
    """

    PM_TYPE: str = "Weekly"
    ESTIMATED_HOURS: float = 1.5  # ~30 min per unit × 3 units

    def __init__(self, conn):
        self.conn = conn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """
        Idempotent start-up routine.
        Ensures the combined equipment record and PM template exist, removes
        legacy individual templates for HYD-UNIT-001/002/003, and disables
        all PM scheduling flags on those legacy equipment records so the
        normal round-robin scheduler never picks them up.
        Safe to call on every application launch.
        """
        self._ensure_combined_unit()
        self._ensure_pm_template()
        self._cleanup_legacy_templates()
        self._disable_legacy_unit_scheduling()

    def generate_weekly_skydrol_pm(
        self,
        week_start_str: str,
        available_technicians: List[str],
    ) -> Dict:
        """
        Schedule ONE combined Skydrol inspection covering all hydraulic units.

        Steps:
          1. Delete any open 'Scheduled' entries for the week for the combined
             unit AND the three legacy individual units (handles systems mid-
             migration).
          2. Insert a single new 'Scheduled' row for HYD-UNITS-ALL, assigned
             to a randomly chosen technician.

        Already-completed rows (status != 'Scheduled') are left untouched.

        Parameters
        ----------
        week_start_str : str
            ISO-format week start date, e.g. ``"2025-03-10"`` (Monday).
        available_technicians : list[str]
            Names eligible for random assignment.

        Returns
        -------
        dict
            ``success`` (bool), ``tasks_added`` (int),
            ``assignments`` (list[dict]), ``error`` (str – on failure only)
        """
        if not available_technicians:
            return {
                "success": False,
                "tasks_added": 0,
                "assignments": [],
                "error": "No technicians available for Skydrol PM assignment.",
            }

        try:
            week_start_dt = datetime.strptime(week_start_str, "%Y-%m-%d")
            cursor = self.conn.cursor()

            # Remove any open schedule rows for this week — combined unit and
            # all three legacy individual units — so we always emit a fresh
            # single combined assignment.
            all_bfms = [COMBINED_UNIT["bfm_equipment_no"]] + LEGACY_HYDRAULIC_UNIT_BFMS
            for bfm_no in all_bfms:
                cursor.execute(
                    """
                    DELETE FROM weekly_pm_schedules
                    WHERE week_start_date = %s
                      AND bfm_equipment_no = %s
                      AND pm_type          = %s
                      AND status           = 'Scheduled'
                    """,
                    (week_start_str, bfm_no, self.PM_TYPE),
                )
                deleted = cursor.rowcount
                if deleted:
                    print(
                        f"INFO [Skydrol]: Removed existing open schedule for "
                        f"{bfm_no} week {week_start_str}."
                    )

            # Pick one technician for the combined inspection.
            technician = random.choice(available_technicians)
            scheduled_date = week_start_dt.strftime("%Y-%m-%d")

            cursor.execute(
                """
                INSERT INTO weekly_pm_schedules
                    (week_start_date, bfm_equipment_no, pm_type,
                     assigned_technician, scheduled_date, status)
                VALUES (%s, %s, %s, %s, %s, 'Scheduled')
                """,
                (
                    week_start_str,
                    COMBINED_UNIT["bfm_equipment_no"],
                    self.PM_TYPE,
                    technician,
                    scheduled_date,
                ),
            )

            assignment = {
                "bfm_no":         COMBINED_UNIT["bfm_equipment_no"],
                "description":    COMBINED_UNIT["description"],
                "pm_type":        self.PM_TYPE,
                "technician":     technician,
                "scheduled_date": scheduled_date,
                "location":       COMBINED_UNIT["location"],
                "task":           "Combined Skydrol fluid inspection — HYD Unit 01 / 02 / 03",
            }

            print(
                f"INFO [Skydrol]: Scheduled combined hydraulic inspection "
                f"({COMBINED_UNIT['bfm_equipment_no']}) \u2192 {technician} on {scheduled_date}"
            )

            self.conn.commit()

            return {
                "success": True,
                "tasks_added": 1,
                "assignments": [assignment],
            }

        except Exception as exc:
            try:
                self.conn.rollback()
            except Exception:
                pass
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "tasks_added": 0,
                "assignments": [],
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_combined_unit(self) -> None:
        """
        Insert or update the combined hydraulic-units equipment record.

        All PM-type flags are set to FALSE so the normal round-robin
        scheduler ignores this record.  It exists solely to satisfy the FK
        constraint on weekly_pm_schedules and to supply description /
        location for the schedule display.
        """
        cursor = self.conn.cursor()
        u = COMBINED_UNIT

        cursor.execute(
            """
            INSERT INTO equipment
                (sap_material_no, bfm_equipment_no, description,
                 tool_id_drawing_no, location,
                 weekly_pm, monthly_pm, six_month_pm, annual_pm,
                 status)
            VALUES (%s, %s, %s, %s, %s,
                    FALSE, FALSE, FALSE, FALSE,
                    'Active')
            ON CONFLICT (bfm_equipment_no) DO UPDATE
                SET description      = EXCLUDED.description,
                    location         = EXCLUDED.location,
                    weekly_pm        = FALSE,
                    monthly_pm       = FALSE,
                    six_month_pm     = FALSE,
                    annual_pm        = FALSE,
                    status           = 'Active',
                    updated_date     = CURRENT_TIMESTAMP
            """,
            (
                u["sap_material_no"],
                u["bfm_equipment_no"],
                u["description"],
                u["tool_id_drawing_no"],
                u["location"],
            ),
        )
        print(
            f"INFO [Skydrol]: Equipment record upserted for "
            f"{u['bfm_equipment_no']} (combined — all hydraulic units)."
        )
        self.conn.commit()

    def _ensure_pm_template(self) -> None:
        """Create or update the single combined Skydrol PM checklist template."""
        cursor = self.conn.cursor()

        # Guard: pm_templates table may not exist on a brand-new installation.
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name   = 'pm_templates'
            )
            """
        )
        row = cursor.fetchone()
        if not (row and row[0]):
            print(
                "INFO [Skydrol]: pm_templates table not yet created — "
                "template will be created on next startup."
            )
            return

        bfm_no = COMBINED_UNIT["bfm_equipment_no"]
        template_name = "Skydrol Level Check — All Hydraulic Units (HYD 01 / 02 / 03)"
        checklist_json = json.dumps(
            [
                {"step": idx + 1, "description": item}
                for idx, item in enumerate(SKYDROL_CHECKLIST)
            ]
        )

        cursor.execute(
            """
            SELECT id FROM pm_templates
            WHERE bfm_equipment_no = %s AND pm_type = %s
            """,
            (bfm_no, self.PM_TYPE),
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                """
                UPDATE pm_templates
                SET template_name        = %s,
                    checklist_items      = %s,
                    special_instructions = %s,
                    safety_notes         = %s,
                    estimated_hours      = %s,
                    updated_date         = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    template_name,
                    checklist_json,
                    SKYDROL_SPECIAL_INSTRUCTIONS,
                    SKYDROL_SAFETY_NOTES,
                    self.ESTIMATED_HOURS,
                    existing[0],
                ),
            )
            print(f"INFO [Skydrol]: Updated combined PM template for {bfm_no}.")
        else:
            cursor.execute(
                """
                INSERT INTO pm_templates
                    (bfm_equipment_no, template_name, pm_type,
                     checklist_items, special_instructions,
                     safety_notes, estimated_hours)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    bfm_no,
                    template_name,
                    self.PM_TYPE,
                    checklist_json,
                    SKYDROL_SPECIAL_INSTRUCTIONS,
                    SKYDROL_SAFETY_NOTES,
                    self.ESTIMATED_HOURS,
                ),
            )
            print(f"INFO [Skydrol]: Created combined PM template for {bfm_no}.")

        self.conn.commit()

    def _disable_legacy_unit_scheduling(self) -> None:
        """
        Set all PM-type flags to FALSE for HYD-UNIT-001, HYD-UNIT-002, and
        HYD-UNIT-003 in the equipment table, and remove any open 'Scheduled'
        rows for those units from weekly_pm_schedules.

        This prevents the normal round-robin PM scheduler from ever picking
        up the three individual hydraulic units — all scheduling for those
        units is handled exclusively by generate_weekly_skydrol_pm() via the
        combined HYD-UNITS-ALL record.

        Safe to call repeatedly (idempotent): if the flags are already FALSE
        and there are no open rows, it silently becomes a no-op.
        """
        cursor = self.conn.cursor()

        for bfm_no in LEGACY_HYDRAULIC_UNIT_BFMS:
            # Disable all PM scheduling flags on the legacy equipment record.
            cursor.execute(
                """
                UPDATE equipment
                SET weekly_pm    = FALSE,
                    monthly_pm   = FALSE,
                    six_month_pm = FALSE,
                    annual_pm    = FALSE
                WHERE bfm_equipment_no = %s
                """,
                (bfm_no,),
            )
            if cursor.rowcount:
                print(
                    f"INFO [Skydrol]: Disabled all PM flags for legacy unit "
                    f"{bfm_no} — scheduling is handled by HYD-UNITS-ALL."
                )

            # Remove any open (Scheduled) schedule rows for the legacy unit
            # so stale individual assignments cannot remain visible.
            cursor.execute(
                """
                DELETE FROM weekly_pm_schedules
                WHERE bfm_equipment_no = %s
                  AND status = 'Scheduled'
                """,
                (bfm_no,),
            )
            removed = cursor.rowcount
            if removed:
                print(
                    f"INFO [Skydrol]: Removed {removed} open schedule row(s) "
                    f"for legacy unit {bfm_no}."
                )

        self.conn.commit()

    def _cleanup_legacy_templates(self) -> None:
        """
        Remove individual pm_templates rows for HYD-UNIT-001/002/003.

        This is a one-time migration step.  Once the rows are gone this
        function becomes a no-op (the DELETE affects zero rows).
        """
        cursor = self.conn.cursor()

        # Guard: pm_templates table may not exist on a brand-new installation.
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name   = 'pm_templates'
            )
            """
        )
        row = cursor.fetchone()
        if not (row and row[0]):
            return

        for bfm_no in LEGACY_HYDRAULIC_UNIT_BFMS:
            cursor.execute(
                """
                DELETE FROM pm_templates
                WHERE bfm_equipment_no = %s AND pm_type = %s
                """,
                (bfm_no, self.PM_TYPE),
            )
            removed = cursor.rowcount
            if removed:
                print(
                    f"INFO [Skydrol]: Removed legacy individual PM template for "
                    f"{bfm_no} (replaced by combined HYD-UNITS-ALL template)."
                )

        self.conn.commit()
