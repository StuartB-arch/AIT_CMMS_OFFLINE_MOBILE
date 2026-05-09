#!/usr/bin/env python3
"""
Analyze and report on assets that appear in both CANNOT FIND and DEACTIVATED lists.
Uses the same database connection configuration as the main CMMS application.
"""

import sys
import os
from datetime import datetime

# Add current directory to path to import database_utils
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database_utils import db_pool

# Database configuration (same as AIT_CMMS_REV3.py)
DB_CONFIG = {
    'host': 'ep-tiny-paper-ad8glt26-pooler.c-2.us-east-1.aws.neon.tech',
    'port': 5432,
    'database': 'neondb',
    'user': 'neondb_owner',
    'password': 'npg_2Nm6hyPVWiIH',
    'sslmode': 'require'
}

def analyze_duplicates():
    """Analyze assets that appear in both cannot_find and deactivated tables."""

    print("\n" + "="*120)
    print("ANALYZING DUPLICATE ASSETS")
    print("="*120)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    try:
        # Initialize connection pool
        print("Connecting to NEON cloud database...")
        db_pool.initialize(DB_CONFIG, min_conn=1, max_conn=5)
        print("✓ Connected successfully\n")

        # Query for duplicates
        query = """
        SELECT
            cf.bfm_equipment_no,
            e.sap_material_no,
            e.description,
            cf.location as cannot_find_location,
            cf.reported_by,
            cf.reported_date,
            cf.status as cannot_find_status,
            d.deactivated_by,
            d.deactivated_date,
            d.reason as deactivation_reason,
            d.status as deactivated_status
        FROM cannot_find_assets cf
        INNER JOIN deactivated_assets d ON cf.bfm_equipment_no = d.bfm_equipment_no
        LEFT JOIN equipment e ON cf.bfm_equipment_no = e.bfm_equipment_no
        WHERE cf.status = 'Missing'
        ORDER BY cf.bfm_equipment_no;
        """

        with db_pool.get_cursor() as cursor:
            cursor.execute(query)
            results = cursor.fetchall()

        if not results:
            print("✓ NO DUPLICATES FOUND!")
            print("="*120)
            print("\nAll Cannot Find assets are properly separated from Deactivated assets.")
            print("No cleanup needed - your data is clean!\n")
            return []

        # Print summary
        print(f"⚠ FOUND {len(results)} DUPLICATE ASSET(S)")
        print("="*120)
        print("\nThese assets are in BOTH the Cannot Find list AND the Deactivated list.")
        print("Recommendation: Remove them from the Cannot Find list.\n")

        # Print table
        print(f"{'BFM Number':<15} {'SAP Number':<12} {'Description':<40} {'Deactivated Date':<17} {'Reason':<30}")
        print("-"*120)

        duplicate_bfm_numbers = []

        for row in results:
            bfm_no = row['bfm_equipment_no'] or "N/A"
            sap_no = row['sap_material_no'] or "N/A"
            description = (row['description'] or "N/A")[:38]
            deactivated_date = row['deactivated_date'] or "N/A"
            reason = (row['deactivation_reason'] or "N/A")[:28]

            print(f"{bfm_no:<15} {sap_no:<12} {description:<40} {deactivated_date:<17} {reason:<30}")
            duplicate_bfm_numbers.append(bfm_no)

        # Print detailed information
        print("\n" + "="*120)
        print("DETAILED INFORMATION")
        print("="*120)

        for idx, row in enumerate(results, 1):
            print(f"\n[{idx}] BFM Number: {row['bfm_equipment_no']}")
            print(f"    SAP Number: {row['sap_material_no'] or 'N/A'}")
            print(f"    Description: {row['description'] or 'N/A'}")
            print(f"    ---")
            print(f"    Cannot Find Location: {row['cannot_find_location'] or 'N/A'}")
            print(f"    Reported By: {row['reported_by'] or 'N/A'}")
            print(f"    Reported Date: {row['reported_date'] or 'N/A'}")
            print(f"    Cannot Find Status: {row['cannot_find_status'] or 'N/A'}")
            print(f"    ---")
            print(f"    Deactivated By: {row['deactivated_by'] or 'N/A'}")
            print(f"    Deactivated Date: {row['deactivated_date'] or 'N/A'}")
            print(f"    Deactivation Reason: {row['deactivation_reason'] or 'N/A'}")
            print(f"    Deactivated Status: {row['deactivated_status'] or 'N/A'}")

        # Print BFM numbers list
        print("\n" + "="*120)
        print("BFM NUMBERS TO REMOVE FROM 'CANNOT FIND' LIST")
        print("="*120)
        print("\nCopy this list:\n")
        for bfm in duplicate_bfm_numbers:
            print(f"  {bfm}")

        # Save to file
        output_file = f"duplicate_assets_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(output_file, 'w') as f:
            f.write("="*120 + "\n")
            f.write("ASSETS FOUND IN BOTH 'CANNOT FIND' AND 'DEACTIVATED' LISTS\n")
            f.write("="*120 + "\n")
            f.write(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total duplicates found: {len(results)}\n\n")

            f.write(f"{'BFM Number':<15} {'SAP Number':<12} {'Description':<40} {'Deactivated Date':<17} {'Reason':<30}\n")
            f.write("-"*120 + "\n")

            for row in results:
                bfm_no = row['bfm_equipment_no'] or "N/A"
                sap_no = row['sap_material_no'] or "N/A"
                description = (row['description'] or "N/A")[:38]
                deactivated_date = row['deactivated_date'] or "N/A"
                reason = (row['deactivation_reason'] or "N/A")[:28]
                f.write(f"{bfm_no:<15} {sap_no:<12} {description:<40} {deactivated_date:<17} {reason:<30}\n")

            f.write("\n" + "="*120 + "\n")
            f.write("DETAILED INFORMATION\n")
            f.write("="*120 + "\n")

            for idx, row in enumerate(results, 1):
                f.write(f"\n[{idx}] BFM Number: {row['bfm_equipment_no']}\n")
                f.write(f"    SAP Number: {row['sap_material_no'] or 'N/A'}\n")
                f.write(f"    Description: {row['description'] or 'N/A'}\n")
                f.write(f"    ---\n")
                f.write(f"    Cannot Find Location: {row['cannot_find_location'] or 'N/A'}\n")
                f.write(f"    Reported By: {row['reported_by'] or 'N/A'}\n")
                f.write(f"    Reported Date: {row['reported_date'] or 'N/A'}\n")
                f.write(f"    Cannot Find Status: {row['cannot_find_status'] or 'N/A'}\n")
                f.write(f"    ---\n")
                f.write(f"    Deactivated By: {row['deactivated_by'] or 'N/A'}\n")
                f.write(f"    Deactivated Date: {row['deactivated_date'] or 'N/A'}\n")
                f.write(f"    Deactivation Reason: {row['deactivation_reason'] or 'N/A'}\n")
                f.write(f"    Deactivated Status: {row['deactivated_status'] or 'N/A'}\n")

            f.write("\n" + "="*120 + "\n")
            f.write("BFM NUMBERS TO REMOVE FROM 'CANNOT FIND' LIST\n")
            f.write("="*120 + "\n\n")
            for bfm in duplicate_bfm_numbers:
                f.write(f"  {bfm}\n")

        print(f"\n✓ Full report saved to: {output_file}")

        # Generate cleanup SQL
        sql_file = f"cleanup_duplicate_assets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
        with open(sql_file, 'w') as f:
            f.write("-- SQL Script to Remove Duplicate Assets from Cannot Find List\n")
            f.write(f"-- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"-- Total assets to remove: {len(duplicate_bfm_numbers)}\n\n")
            f.write("-- BACKUP FIRST: Create a backup of cannot_find_assets table\n")
            f.write("-- CREATE TABLE cannot_find_assets_backup AS SELECT * FROM cannot_find_assets;\n\n")
            f.write("BEGIN;\n\n")

            for bfm in duplicate_bfm_numbers:
                f.write(f"DELETE FROM cannot_find_assets WHERE bfm_equipment_no = '{bfm}';\n")

            f.write("\n-- Review the changes before committing\n")
            f.write("-- If everything looks good, run: COMMIT;\n")
            f.write("-- If you want to undo, run: ROLLBACK;\n\n")
            f.write("-- COMMIT;\n")

        print(f"✓ SQL cleanup script saved to: {sql_file}")
        print("\n⚠️  IMPORTANT: Review the SQL file before executing!")
        print("   The script includes a transaction (BEGIN/COMMIT) for safety.")

        print(f"\n{'='*120}")
        print(f"SUMMARY: Found {len(duplicate_bfm_numbers)} duplicate asset(s)")
        print(f"{'='*120}")
        print("\nRECOMMENDATION: These assets are deactivated, so they should be removed")
        print("from the Cannot Find list. Use the generated SQL script to clean them up.\n")

        return duplicate_bfm_numbers

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return []

    finally:
        # Close connection pool
        db_pool.close_all()
        print("\nDatabase connection closed.\n")

if __name__ == "__main__":
    print("\n" + "="*120)
    print("DUPLICATE ASSET ANALYZER")
    print("="*120)
    print("\nSearching for assets in both CANNOT FIND and DEACTIVATED lists...")
    print("This will identify duplicates that should be removed from the Cannot Find list.\n")

    duplicates = analyze_duplicates()

    if not duplicates:
        print("✓ Analysis complete - no cleanup needed!\n")
    else:
        print("✓ Analysis complete - review the reports and SQL script above.\n")
