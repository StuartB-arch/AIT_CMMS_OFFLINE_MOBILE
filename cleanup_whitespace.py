#!/usr/bin/env python3
"""
Database cleanup script to remove newlines and whitespace from text fields
"""

import sys
import os

# Add the current directory to path to import database utils
sys.path.insert(0, os.path.dirname(__file__))

from database_utils import DatabaseConnectionPool

# Database configuration
DB_CONFIG = {
    'host': 'ep-tiny-paper-ad8glt26-pooler.c-2.us-east-1.aws.neon.tech',
    'port': 5432,
    'database': 'neondb',
    'user': 'neondb_owner',
    'password': 'npg_2Nm6hyPVWiIH',
    'sslmode': 'require'
}

def cleanup_database():
    """Remove newlines and extra whitespace from equipment table text fields"""

    try:
        # Initialize connection pool
        db_pool = DatabaseConnectionPool()
        db_pool.initialize(DB_CONFIG, min_conn=1, max_conn=2)

        print("=" * 100)
        print("DATABASE WHITESPACE CLEANUP TOOL")
        print("=" * 100)

        with db_pool.get_cursor(commit=False) as cursor:
            # First, find all records with whitespace issues
            print("\nScanning for assets with whitespace issues...")

            cursor.execute('''
                SELECT
                    bfm_equipment_no,
                    sap_material_no,
                    description,
                    tool_id_drawing_no,
                    location,
                    master_lin
                FROM equipment
                WHERE
                    bfm_equipment_no != TRIM(bfm_equipment_no) OR
                    sap_material_no != TRIM(sap_material_no) OR
                    description != TRIM(description) OR
                    tool_id_drawing_no != TRIM(tool_id_drawing_no) OR
                    location != TRIM(location) OR
                    master_lin != TRIM(master_lin)
            ''')

            affected_assets = cursor.fetchall()

            if not affected_assets:
                print("\n✓ No whitespace issues found! Database is clean.")
                return

            print(f"\n⚠ Found {len(affected_assets)} asset(s) with whitespace issues:\n")

            # Show affected assets
            for i, asset in enumerate(affected_assets, 1):
                bfm = asset['bfm_equipment_no']
                print(f"{i}. BFM: '{bfm}' (length: {len(bfm) if bfm else 0})")
                print(f"   SAP: '{asset['sap_material_no']}'")
                print(f"   Description: '{asset['description']}'")
                print()

        # Ask for confirmation
        print("=" * 100)
        response = input("Do you want to clean these records? (yes/no): ").strip().lower()

        if response != 'yes':
            print("\n❌ Cleanup cancelled by user.")
            return

        # Perform cleanup
        print("\nCleaning database...")

        with db_pool.get_cursor(commit=True) as cursor:
            # Update all text fields to remove leading/trailing whitespace
            cursor.execute('''
                UPDATE equipment
                SET
                    bfm_equipment_no = TRIM(bfm_equipment_no),
                    sap_material_no = TRIM(sap_material_no),
                    description = TRIM(description),
                    tool_id_drawing_no = TRIM(tool_id_drawing_no),
                    location = TRIM(location),
                    master_lin = TRIM(master_lin)
                WHERE
                    bfm_equipment_no != TRIM(bfm_equipment_no) OR
                    sap_material_no != TRIM(sap_material_no) OR
                    description != TRIM(description) OR
                    tool_id_drawing_no != TRIM(tool_id_drawing_no) OR
                    location != TRIM(location) OR
                    master_lin != TRIM(master_lin)
            ''')

            rows_affected = cursor.rowcount
            print(f"\n✓ Successfully cleaned {rows_affected} record(s)!")

        # Verify cleanup
        print("\nVerifying cleanup...")

        with db_pool.get_cursor(commit=False) as cursor:
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM equipment
                WHERE
                    bfm_equipment_no != TRIM(bfm_equipment_no) OR
                    sap_material_no != TRIM(sap_material_no) OR
                    description != TRIM(description) OR
                    tool_id_drawing_no != TRIM(tool_id_drawing_no) OR
                    location != TRIM(location) OR
                    master_lin != TRIM(master_lin)
            ''')

            remaining = cursor.fetchone()['count']

            if remaining == 0:
                print("✓ Verification successful - all whitespace removed!")
            else:
                print(f"⚠ Warning: {remaining} records still have whitespace issues")

        print("\n" + "=" * 100)
        print("CLEANUP COMPLETE")
        print("=" * 100)
        print("\nYou can now:")
        print("1. Restart your CMMS application")
        print("2. Try editing those assets again - they should work now!")
        print("3. Run diagnose_assets.py again to verify the fix")

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    cleanup_database()
