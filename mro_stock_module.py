"""
AIT CMMS - MRO Stock Management Module
Add this to your existing AIT_CMMS_REV3.py file
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
import os
import threading
from PIL import Image, ImageTk
import shutil
import csv
import io
from database_utils import db_pool
from csv_manager import MROCSVManager

class MROStockManager:
    """MRO (Maintenance, Repair, Operations) Stock Management"""


    
    
    
    def __init__(self, parent_app):
        self.parent_app = parent_app
        self.conn = parent_app.conn
        self.root = parent_app.root
        from site_config import get_mro_csv_path
        self.mro_csv = MROCSVManager(self.conn, csv_path=get_mro_csv_path())
        self.init_mro_database()

    def _csv_sync_async(self, part_number: str):
        """Update one part row in MRO_STOCK.csv in a background thread."""
        threading.Thread(
            target=lambda: self.mro_csv.sync_part_row(part_number),
            daemon=True,
        ).start()

    def _csv_remove_async(self, part_number: str):
        """Mark a part Inactive in MRO_STOCK.csv in a background thread."""
        threading.Thread(
            target=lambda: self.mro_csv.remove_part_row(part_number),
            daemon=True,
        ).start()
        
    def init_mro_database(self):
        """Initialize MRO inventory table"""
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mro_inventory (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                part_number TEXT UNIQUE NOT NULL,
                model_number TEXT,
                equipment TEXT,
                engineering_system TEXT,
                unit_of_measure TEXT,
                quantity_in_stock REAL DEFAULT 0,
                unit_price REAL DEFAULT 0,
                minimum_stock REAL DEFAULT 0,
                supplier TEXT,
                location TEXT,
                rack TEXT,
                row TEXT,
                bin TEXT,
                picture_1_path TEXT,
                picture_2_path TEXT,
                picture_1_data BYTEA,
                picture_2_data BYTEA,
                notes TEXT,
                last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                created_date TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'Active'
            )
        ''')

        # Migrate existing tables to add new columns if they don't exist
        try:
            # Check if picture_1_data column exists
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='mro_inventory' AND column_name='picture_1_data'
            """)
            if not cursor.fetchone():
                cursor.execute('ALTER TABLE mro_inventory ADD COLUMN picture_1_data BYTEA')
                self.conn.commit()
                print("Added picture_1_data column to mro_inventory table")
        except Exception as e:
            self.conn.rollback()
            print(f"Note: Could not add picture_1_data column: {e}")

        try:
            # Check if picture_2_data column exists
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='mro_inventory' AND column_name='picture_2_data'
            """)
            if not cursor.fetchone():
                cursor.execute('ALTER TABLE mro_inventory ADD COLUMN picture_2_data BYTEA')
                self.conn.commit()
                print("Added picture_2_data column to mro_inventory table")
        except Exception as e:
            self.conn.rollback()
            print(f"Note: Could not add picture_2_data column: {e}")

        # === PERFORMANCE OPTIMIZATION: Create comprehensive MRO indexes ===
        print("CHECK: Creating MRO inventory performance indexes...")

        # Basic indexes for unique lookups
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_part_number
            ON mro_inventory(part_number)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_name
            ON mro_inventory(name)
        ''')

        # Functional indexes for case-insensitive searches (critical for filter performance)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_engineering_system_lower
            ON mro_inventory(LOWER(engineering_system))
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_status_lower
            ON mro_inventory(LOWER(status))
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_location_lower
            ON mro_inventory(LOWER(location))
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_equipment_lower
            ON mro_inventory(LOWER(equipment))
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_model_number_lower
            ON mro_inventory(LOWER(model_number))
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_part_number_lower
            ON mro_inventory(LOWER(part_number))
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_name_lower
            ON mro_inventory(LOWER(name))
        ''')

        # Partial index for low stock queries (most common filter)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_low_stock
            ON mro_inventory(status, quantity_in_stock, minimum_stock)
            WHERE quantity_in_stock < minimum_stock
        ''')

        # Covering index for statistics queries (eliminates table access)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_active_stock_value
            ON mro_inventory(status, quantity_in_stock, unit_price, minimum_stock)
            WHERE status = 'Active'
        ''')

        print("CHECK: MRO inventory indexes created successfully!")

        # Stock transactions table for tracking stock movements
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mro_stock_transactions (
                id SERIAL PRIMARY KEY,
                part_number TEXT NOT NULL,
                transaction_type TEXT NOT NULL,
                quantity REAL NOT NULL,
                transaction_date TEXT DEFAULT CURRENT_TIMESTAMP,
                technician_name TEXT,
                work_order TEXT,
                notes TEXT,
                FOREIGN KEY (part_number) REFERENCES mro_inventory (part_number)
            )
        ''')

        # CM parts usage table for tracking parts used in corrective maintenance
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cm_parts_used (
                id SERIAL PRIMARY KEY,
                cm_number TEXT NOT NULL,
                part_number TEXT NOT NULL,
                quantity_used REAL NOT NULL,
                total_cost REAL DEFAULT 0,
                recorded_date TEXT DEFAULT CURRENT_TIMESTAMP,
                recorded_by TEXT,
                notes TEXT,
                FOREIGN KEY (part_number) REFERENCES mro_inventory (part_number)
            )
        ''')

        # Indexes for faster CM parts and transaction queries
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_cm_parts_cm_number
            ON cm_parts_used(cm_number)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_cm_parts_part_number
            ON cm_parts_used(part_number)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_cm_parts_used_date
            ON cm_parts_used(recorded_date)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_transactions_date
            ON mro_stock_transactions(transaction_date)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_transactions_part_number
            ON mro_stock_transactions(part_number)
        ''')

        self.conn.commit()
        print("MRO inventory database initialized with performance indexes")
    
    def create_mro_tab(self, notebook, readonly=False):
        """Create MRO Stock Management tab

        Args:
            notebook: Parent notebook widget
            readonly: If True, creates a read-only view (no add/edit/delete buttons)
        """
        mro_frame = ttk.Frame(notebook)
        tab_text = 'MRO Stock (Read Only)' if readonly else 'MRO Stock'
        notebook.add(mro_frame, text=tab_text)

        # Top controls frame
        controls_frame = ttk.LabelFrame(mro_frame, text="MRO Stock Controls", padding=10)
        controls_frame.pack(fill='x', padx=10, pady=5)

        # Buttons row 1
        btn_frame1 = ttk.Frame(controls_frame)
        btn_frame1.pack(fill='x', pady=5)

        # Only show edit buttons if not readonly
        if not readonly:
            ttk.Button(btn_frame1, text="➕ Add New Part",
                      command=self.add_part_dialog, width=20).pack(side='left', padx=5)
            ttk.Button(btn_frame1, text="✏️ Edit Selected Part",
                      command=self.edit_selected_part, width=20).pack(side='left', padx=5)
            ttk.Button(btn_frame1, text="🗑️ Delete Selected Part",
                      command=self.delete_selected_part, width=20).pack(side='left', padx=5)

        # View and report buttons available in both modes
        ttk.Button(btn_frame1, text="📋 View Full Details",
                  command=self.view_part_details, width=20).pack(side='left', padx=5)
        ttk.Button(btn_frame1, text="📊 Parts Usage Report",
                  command=self.show_parts_usage_report, width=20).pack(side='left', padx=5)

        # Buttons row 2
        btn_frame2 = ttk.Frame(controls_frame)
        btn_frame2.pack(fill='x', pady=5)

        # Import only available in edit mode
        if not readonly:
            ttk.Button(btn_frame2, text="📥 Import from File",
                      command=self.import_from_file, width=20).pack(side='left', padx=5)

        # Export and reports available in both modes
        ttk.Button(btn_frame2, text="📤 Export to CSV",
                  command=self.export_to_csv, width=20).pack(side='left', padx=5)
        ttk.Button(btn_frame2, text="📊 Stock Report",
                  command=self.generate_stock_report, width=20).pack(side='left', padx=5)
        ttk.Button(btn_frame2, text="⚠️ Low Stock Alert",
                  command=self.show_low_stock, width=20).pack(side='left', padx=5)

        # Migrate only available in edit mode
        if not readonly:
            ttk.Button(btn_frame2, text="🔄 Migrate Photos to DB",
                      command=self.migrate_photos_to_database, width=20).pack(side='left', padx=5)

        # Search and filter frame
        search_frame = ttk.LabelFrame(mro_frame, text="Search & Filter", padding=10)
        search_frame.pack(fill='x', padx=10, pady=5)
        
        # Search bar
        ttk.Label(search_frame, text="Search:").pack(side='left', padx=5)
        self.mro_search_var = tk.StringVar()
        self.mro_search_var.trace('w', self.filter_mro_list)
        ttk.Entry(search_frame, textvariable=self.mro_search_var, 
                 width=40).pack(side='left', padx=5)
        
        # Filter by category
        ttk.Label(search_frame, text="System:").pack(side='left', padx=5)
        self.mro_system_filter = tk.StringVar(value='All')
        system_combo = ttk.Combobox(search_frame, textvariable=self.mro_system_filter,
                                    values=['All', 'Mechanical', 'Electrical', 'Pneumatic', 'Hydraulic'],
                                    width=15, state='readonly')
        system_combo.pack(side='left', padx=5)
        system_combo.bind('<<ComboboxSelected>>', self.filter_mro_list)
        
        # Status filter
        ttk.Label(search_frame, text="Status:").pack(side='left', padx=5)
        self.mro_status_filter = tk.StringVar(value='Active')
        status_combo = ttk.Combobox(search_frame, textvariable=self.mro_status_filter,
                                    values=['All', 'Active', 'Inactive', 'Low Stock'],
                                    width=15, state='readonly')
        status_combo.pack(side='left', padx=5)
        status_combo.bind('<<ComboboxSelected>>', self.filter_mro_list)

        # Location filter
        ttk.Label(search_frame, text="Location:").pack(side='left', padx=5)
        self.mro_location_filter = tk.StringVar(value='All')
        self.location_combo = ttk.Combobox(search_frame, textvariable=self.mro_location_filter,
                                           values=['All'],
                                           width=15, state='readonly')
        self.location_combo.pack(side='left', padx=5)
        self.location_combo.bind('<<ComboboxSelected>>', self.filter_mro_list)

        ttk.Button(search_frame, text="🔄 Refresh",
                  command=self.refresh_mro_list).pack(side='left', padx=5)
        
        # Inventory list
        list_frame = ttk.LabelFrame(mro_frame, text="MRO Inventory", padding=10)
        list_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        # Create treeview
        columns = ('Part Number', 'Name', 'Model', 'Equipment', 'System', 'Qty', 
                  'Min Stock', 'Unit', 'Price', 'Location', 'Status')
        self.mro_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=20)
        
        # Configure columns
        column_widths = {
            'Part Number': 120,
            'Name': 200,
            'Model': 100,
            'Equipment': 120,
            'System': 100,
            'Qty': 70,
            'Min Stock': 80,
            'Unit': 60,
            'Price': 80,
            'Location': 100,
            'Status': 80
        }
        
        for col in columns:
            self.mro_tree.heading(col, text=col, command=lambda c=col: self.sort_mro_column(c))
            self.mro_tree.column(col, width=column_widths[col], anchor='center')
        
        # Scrollbars
        vsb = ttk.Scrollbar(list_frame, orient='vertical', command=self.mro_tree.yview)
        hsb = ttk.Scrollbar(list_frame, orient='horizontal', command=self.mro_tree.xview)
        self.mro_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        # Pack elements
        self.mro_tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        
        # Double-click to view details
        self.mro_tree.bind('<Double-1>', lambda e: self.view_part_details())
        
        # Statistics frame
        stats_frame = ttk.LabelFrame(mro_frame, text="Inventory Statistics", padding=10)
        stats_frame.pack(fill='x', padx=10, pady=5)
        
        self.mro_stats_label = ttk.Label(stats_frame, text="Loading...", 
                                         font=('Arial', 10))
        self.mro_stats_label.pack()
        
        # Load initial data
        self.refresh_mro_list()
        
        return mro_frame
    
    def add_part_dialog(self):
        """Dialog to add new part"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Add New MRO Part")
        dialog.geometry("800x900")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Create scrollable frame
        canvas = tk.Canvas(dialog)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
    
        # ✅ FIX THIS LINE - it was incomplete!
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Form fields
        fields = {}
        row = 0
        
        # Basic Information
        ttk.Label(scrollable_frame, text="BASIC INFORMATION", 
                font=('Arial', 11, 'bold')).grid(row=row, column=0, columnspan=2, 
                                              sticky='w', padx=10, pady=10)
        row += 1
    
        field_configs = [
            ('Name*', 'name'),
            ('Part Number*', 'part_number'),
            ('Model Number', 'model_number'),
            ('Equipment', 'equipment'),
        ]
    
        for label, field_name in field_configs:
            ttk.Label(scrollable_frame, text=label).grid(row=row, column=0, 
                                                        sticky='w', padx=10, pady=5)
            fields[field_name] = ttk.Entry(scrollable_frame, width=50)
            fields[field_name].grid(row=row, column=1, sticky='w', padx=10, pady=5)
            row += 1
    
        # Stock Information
        ttk.Label(scrollable_frame, text="STOCK INFORMATION", 
                font=('Arial', 11, 'bold')).grid(row=row, column=0, columnspan=2, 
                                                sticky='w', padx=10, pady=10)
        row += 1
    
        stock_fields = [
            ('Engineering System*', 'engineering_system'),
            ('Unit of Measure*', 'unit_of_measure'),
            ('Quantity in Stock*', 'quantity_in_stock'),
            ('Unit Price', 'unit_price'),
            ('Minimum Stock*', 'minimum_stock'),
            ('Supplier', 'supplier'),
        ]
    
        for label, field_name in stock_fields:
            ttk.Label(scrollable_frame, text=label).grid(row=row, column=0, 
                                                        sticky='w', padx=10, pady=5)
            fields[field_name] = ttk.Entry(scrollable_frame, width=50)
            fields[field_name].grid(row=row, column=1, sticky='w', padx=10, pady=5)
            row += 1
    
        # Location Information
        ttk.Label(scrollable_frame, text="LOCATION INFORMATION", 
                font=('Arial', 11, 'bold')).grid(row=row, column=0, columnspan=2, 
                                                sticky='w', padx=10, pady=10)
        row += 1
    
        location_fields = [
            ('Location*', 'location'),
            ('Rack', 'rack'),
            ('Row', 'row'),
            ('Bin', 'bin'),
        ]
    
        for label, field_name in location_fields:
            ttk.Label(scrollable_frame, text=label).grid(row=row, column=0, 
                                                        sticky='w', padx=10, pady=5)
            fields[field_name] = ttk.Entry(scrollable_frame, width=50)
            fields[field_name].grid(row=row, column=1, sticky='w', padx=10, pady=5)
            row += 1
    
        # Pictures
        ttk.Label(scrollable_frame, text="PICTURES", 
                font=('Arial', 11, 'bold')).grid(row=row, column=0, columnspan=2, 
                                                sticky='w', padx=10, pady=10)
        row += 1
    
        fields['picture_1'] = tk.StringVar()
        fields['picture_2'] = tk.StringVar()
        
        ttk.Label(scrollable_frame, text="Picture 1:").grid(row=row, column=0, 
                                                            sticky='w', padx=10, pady=5)
        pic1_frame = ttk.Frame(scrollable_frame)
        pic1_frame.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        ttk.Entry(pic1_frame, textvariable=fields['picture_1'], width=35).pack(side='left')
        ttk.Button(pic1_frame, text="Browse", 
                command=lambda: self.browse_image(fields['picture_1'])).pack(side='left', padx=5)
        row += 1
    
        ttk.Label(scrollable_frame, text="Picture 2:").grid(row=row, column=0, 
                                                            sticky='w', padx=10, pady=5)
        pic2_frame = ttk.Frame(scrollable_frame)
        pic2_frame.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        ttk.Entry(pic2_frame, textvariable=fields['picture_2'], width=35).pack(side='left')
        ttk.Button(pic2_frame, text="Browse", 
                command=lambda: self.browse_image(fields['picture_2'])).pack(side='left', padx=5)
        row += 1
    
        # Notes
        ttk.Label(scrollable_frame, text="Notes:").grid(row=row, column=0, 
                                                        sticky='nw', padx=10, pady=5)
        fields['notes'] = tk.Text(scrollable_frame, width=50, height=5)
        fields['notes'].grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
    
        # Buttons
        btn_frame = ttk.Frame(scrollable_frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=20)
    
        def save_part():
            try:
                # Validate required fields
                required = ['name', 'part_number', 'engineering_system',
                        'unit_of_measure', 'quantity_in_stock', 'minimum_stock', 'location']

                for field in required:
                    if field in ['notes', 'picture_1', 'picture_2']:
                        continue
                    value = fields[field].get() if hasattr(fields[field], 'get') else ''
                    if not value:
                        messagebox.showerror("Error", f"Please fill in: {field.replace('_', ' ').title()}")
                        return

                # Read image files as binary data
                pic1_path = fields['picture_1'].get()
                pic2_path = fields['picture_2'].get()

                pic1_data = None
                pic2_data = None

                if pic1_path and os.path.exists(pic1_path):
                    with open(pic1_path, 'rb') as f:
                        pic1_data = f.read()

                if pic2_path and os.path.exists(pic2_path):
                    with open(pic2_path, 'rb') as f:
                        pic2_data = f.read()

                # Insert into database using connection pool
                notes_text = fields['notes'].get('1.0', 'end-1c') if 'notes' in fields else ''

                # Use connection pool to avoid SSL timeout issues
                with db_pool.get_cursor(commit=True) as cursor:
                    cursor.execute('''
                        INSERT INTO mro_inventory (
                            name, part_number, model_number, equipment, engineering_system,
                            unit_of_measure, quantity_in_stock, unit_price, minimum_stock,
                            supplier, location, rack, row, bin, picture_1_path, picture_2_path,
                            picture_1_data, picture_2_data, notes
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        fields['name'].get(),
                        fields['part_number'].get(),
                        fields['model_number'].get(),
                        fields['equipment'].get(),
                        fields['engineering_system'].get(),
                        fields['unit_of_measure'].get(),
                        float(fields['quantity_in_stock'].get() or 0),
                        float(fields['unit_price'].get() or 0),
                        float(fields['minimum_stock'].get() or 0),
                        fields['supplier'].get(),
                        fields['location'].get(),
                        fields['rack'].get(),
                        fields['row'].get(),
                        fields['bin'].get(),
                        pic1_path,
                        pic2_path,
                        pic1_data,
                        pic2_data,
                        notes_text
                    ))

                messagebox.showinfo("Success", "Part added successfully!")
                self._csv_sync_async(fields['part_number'].get().strip())
                dialog.destroy()
                self.refresh_mro_list()

            except Exception as e:
                error_msg = str(e).lower()
                if 'unique constraint' in error_msg or 'duplicate' in error_msg or 'already exists' in error_msg:
                    messagebox.showerror("Error", "Part number already exists!")
                elif 'ssl' in error_msg or 'connection' in error_msg:
                    messagebox.showerror("Database Connection Error",
                        "Failed to connect to database. This may be due to:\n"
                        "• Network connectivity issues\n"
                        "• SSL certificate problems\n"
                        "• Database timeout\n\n"
                        f"Technical details: {str(e)}\n\n"
                        "Please try again. If the problem persists, contact IT support.")
                else:
                    messagebox.showerror("Error", f"Failed to add part: {str(e)}")
    
        ttk.Button(btn_frame, text="💾 Save Part", command=save_part, width=20).pack(side='left', padx=10)
        ttk.Button(btn_frame, text="❌ Cancel", command=dialog.destroy, width=20).pack(side='left', padx=10)
        
        # ✅ CRITICAL: Pack canvas and scrollbar - THIS MUST BE AT THE END!
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
    
    def browse_image(self, var):
        """Browse for image file"""
        file_path = filedialog.askopenfilename(
            title="Select Image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif *.bmp"), ("All files", "*.*")]
        )
        if file_path:
            var.set(file_path)
    
    def edit_selected_part(self):
        """Edit selected part"""
        selected = self.mro_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a part to edit")
            return

        # DEBUG: Get part number using multiple methods to diagnose issue
        item = self.mro_tree.item(selected[0])
        part_number_from_values = str(item['values'][0]) if item['values'] else 'N/A'
        part_number_from_set = str(self.mro_tree.set(selected[0], 'Part Number'))

        # Use .set() method to get the displayed text from TreeView to preserve leading zeros
        # This avoids issues where TreeView converts "0319" to integer 319
        part_number = part_number_from_set.strip()

        try:
            # Get full part data - use explicit column list to ensure correct order
            with db_pool.get_cursor(commit=False) as cursor:
                # First, let's check what part numbers exist in database that are similar
                # Use TRIM() to handle leading/trailing spaces in part numbers
                cursor.execute('''
                    SELECT part_number FROM mro_inventory
                    WHERE TRIM(part_number) LIKE %s OR TRIM(part_number) = %s
                    ORDER BY part_number
                ''', (f'%{part_number}%', part_number))
                similar_parts = cursor.fetchall()

                # Use TRIM() to handle leading/trailing spaces in part numbers
                cursor.execute('''
                    SELECT id, name, part_number, model_number, equipment, engineering_system,
                           unit_of_measure, quantity_in_stock, unit_price, minimum_stock,
                           supplier, location, rack, row, bin, picture_1_path,
                           picture_2_path, picture_1_data, picture_2_data, notes,
                           last_updated, created_date, status
                    FROM mro_inventory WHERE TRIM(part_number) = %s
                ''', (part_number,))
                part_data = cursor.fetchone()

                if not part_data:
                    # Enhanced error message for debugging
                    similar_list = '\n'.join([f"  - '{p['part_number']}'" for p in similar_parts]) if similar_parts else '  (none)'
                    messagebox.showerror("Error",
                        f"Part not found in database.\n\n"
                        f"DEBUG INFO:\n"
                        f"Part number from .set(): '{part_number_from_set}'\n"
                        f"Part number from values[0]: '{part_number_from_values}'\n"
                        f"Final part number used: '{part_number}'\n"
                        f"Length: {len(part_number)} characters\n\n"
                        f"Similar part numbers in database:\n{similar_list}\n\n"
                        f"Try clicking the Refresh button and then edit again.")
                    return

                # Extract all data while cursor is still active
                part_dict = dict(part_data)
        except Exception as e:
            messagebox.showerror("Database Error",
                f"Error loading part data: {str(e)}\n\n"
                f"Part number: '{part_number}'")
            return

        # Create edit dialog (similar to add dialog but pre-filled)
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit Part: {part_number}")
        dialog.geometry("800x900")
        dialog.transient(self.root)
        dialog.grab_set()

        # Create scrollable frame
        canvas = tk.Canvas(dialog)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # part_dict was already extracted from cursor context above
        # Form fields (similar structure to add_part_dialog)
        fields = {}
        row = 0
        
        # Basic Information
        ttk.Label(scrollable_frame, text="BASIC INFORMATION", 
                 font=('Arial', 11, 'bold')).grid(row=row, column=0, columnspan=2, 
                                                  sticky='w', padx=10, pady=10)
        row += 1
        
        field_configs = [
            ('Name*', 'name'),
            ('Part Number*', 'part_number'),
            ('Model Number', 'model_number'),
            ('Equipment', 'equipment'),
        ]
        
        for label, field_name in field_configs:
            ttk.Label(scrollable_frame, text=label).grid(row=row, column=0, 
                                                         sticky='w', padx=10, pady=5)
            fields[field_name] = ttk.Entry(scrollable_frame, width=50)
            fields[field_name].insert(0, part_dict.get(field_name) or '')
            if field_name == 'part_number':
                fields[field_name].config(state='readonly')  # Don't allow changing part number
            fields[field_name].grid(row=row, column=1, sticky='w', padx=10, pady=5)
            row += 1
        
        # Engineering System
        ttk.Label(scrollable_frame, text="Engineering System*").grid(row=row, column=0, 
                                                                     sticky='w', padx=10, pady=5)
        fields['engineering_system'] = ttk.Combobox(scrollable_frame,
                                                     values=['Mechanical', 'Electrical', 'Pneumatic', 'Hydraulic'],
                                                     width=47, state='readonly')
        fields['engineering_system'].set(part_dict.get('engineering_system') or '')
        fields['engineering_system'].grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
        
        # Stock Information
        ttk.Label(scrollable_frame, text="STOCK INFORMATION", 
                 font=('Arial', 11, 'bold')).grid(row=row, column=0, columnspan=2, 
                                                  sticky='w', padx=10, pady=10)
        row += 1
        
        stock_fields = [
            ('Unit of Measure*', 'unit_of_measure'),
            ('Quantity in Stock*', 'quantity_in_stock'),
            ('Unit Price ($)', 'unit_price'),
            ('Minimum Stock*', 'minimum_stock'),
            ('Supplier', 'supplier'),
        ]
        
        for label, field_name in stock_fields:
            ttk.Label(scrollable_frame, text=label).grid(row=row, column=0, 
                                                         sticky='w', padx=10, pady=5)
            fields[field_name] = ttk.Entry(scrollable_frame, width=50)
            fields[field_name].insert(0, str(part_dict.get(field_name) or ''))
            fields[field_name].grid(row=row, column=1, sticky='w', padx=10, pady=5)
            row += 1
        
        # Location Information
        ttk.Label(scrollable_frame, text="LOCATION INFORMATION", 
                 font=('Arial', 11, 'bold')).grid(row=row, column=0, columnspan=2, 
                                                  sticky='w', padx=10, pady=10)
        row += 1
        
        location_fields = [
            ('Location*', 'location'),
            ('Rack', 'rack'),
            ('Row', 'row'),
            ('Bin', 'bin'),
        ]
        
        for label, field_name in location_fields:
            ttk.Label(scrollable_frame, text=label).grid(row=row, column=0, 
                                                         sticky='w', padx=10, pady=5)
            fields[field_name] = ttk.Entry(scrollable_frame, width=50)
            fields[field_name].insert(0, part_dict.get(field_name) or '')
            fields[field_name].grid(row=row, column=1, sticky='w', padx=10, pady=5)
            row += 1
        
        # Status
        ttk.Label(scrollable_frame, text="Status*").grid(row=row, column=0, 
                                                         sticky='w', padx=10, pady=5)
        fields['status'] = ttk.Combobox(scrollable_frame,
                                       values=['Active', 'Inactive'],
                                       width=47, state='readonly')
        fields['status'].set(part_dict.get('status') or 'Active')
        fields['status'].grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
        
        # Pictures
        ttk.Label(scrollable_frame, text="PICTURES",
                 font=('Arial', 11, 'bold')).grid(row=row, column=0, columnspan=2,
                                                  sticky='w', padx=10, pady=10)
        row += 1

        # Initialize photo fields - start empty to indicate "no change"
        fields['picture_1'] = tk.StringVar(value='')
        fields['picture_2'] = tk.StringVar(value='')

        # Show current photo status
        pic1_status = "📷 Photo stored in database" if part_dict.get('picture_1_data') else "No photo"
        ttk.Label(scrollable_frame, text="Picture 1:").grid(row=row, column=0,
                                                            sticky='w', padx=10, pady=5)
        pic1_frame = ttk.Frame(scrollable_frame)
        pic1_frame.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        ttk.Label(pic1_frame, text=pic1_status, foreground='green' if part_dict.get('picture_1_data') else 'gray').pack(side='left', padx=5)
        ttk.Entry(pic1_frame, textvariable=fields['picture_1'], width=25).pack(side='left')
        ttk.Button(pic1_frame, text="Browse New",
                  command=lambda: self.browse_image(fields['picture_1'])).pack(side='left', padx=5)
        row += 1

        # Show current photo status
        pic2_status = "📷 Photo stored in database" if part_dict.get('picture_2_data') else "No photo"
        ttk.Label(scrollable_frame, text="Picture 2:").grid(row=row, column=0,
                                                            sticky='w', padx=10, pady=5)
        pic2_frame = ttk.Frame(scrollable_frame)
        pic2_frame.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        ttk.Label(pic2_frame, text=pic2_status, foreground='green' if part_dict.get('picture_2_data') else 'gray').pack(side='left', padx=5)
        ttk.Entry(pic2_frame, textvariable=fields['picture_2'], width=25).pack(side='left')
        ttk.Button(pic2_frame, text="Browse New",
                  command=lambda: self.browse_image(fields['picture_2'])).pack(side='left', padx=5)
        row += 1
        
        # Notes
        ttk.Label(scrollable_frame, text="Notes:").grid(row=row, column=0, 
                                                        sticky='nw', padx=10, pady=5)
        fields['notes'] = tk.Text(scrollable_frame, width=50, height=5)
        fields['notes'].insert('1.0', part_dict.get('notes') or '')
        fields['notes'].grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
        
        # Buttons
        btn_frame = ttk.Frame(scrollable_frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=20)
        
        def update_part():
            try:
                # Read image files as binary data
                pic1_path = fields['picture_1'].get()
                pic2_path = fields['picture_2'].get()

                # Get existing photo data and paths from database first
                with db_pool.get_cursor(commit=False) as cursor:
                    # Use TRIM() to handle leading/trailing spaces in part numbers
                    cursor.execute('SELECT picture_1_path, picture_2_path, picture_1_data, picture_2_data FROM mro_inventory WHERE TRIM(part_number) = %s', (part_number,))
                    existing_data = cursor.fetchone()
                    existing_pic1_path = existing_data['picture_1_path'] if existing_data else None
                    existing_pic2_path = existing_data['picture_2_path'] if existing_data else None
                    existing_pic1_data = existing_data['picture_1_data'] if existing_data else None
                    existing_pic2_data = existing_data['picture_2_data'] if existing_data else None

                # Only read new photo data if a NEW file is selected
                # Default to existing data and paths
                final_pic1_path = existing_pic1_path
                final_pic2_path = existing_pic2_path
                pic1_data = existing_pic1_data
                pic2_data = existing_pic2_data

                # Check if user selected a new file for picture 1
                if pic1_path and os.path.exists(pic1_path):
                    # User browsed and selected a new file
                    with open(pic1_path, 'rb') as f:
                        pic1_data = f.read()
                    final_pic1_path = pic1_path

                # Check if user selected a new file for picture 2
                if pic2_path and os.path.exists(pic2_path):
                    # User browsed and selected a new file
                    with open(pic2_path, 'rb') as f:
                        pic2_data = f.read()
                    final_pic2_path = pic2_path

                notes_text = fields['notes'].get('1.0', 'end-1c')

                with db_pool.get_cursor(commit=True) as cursor:
                    # Use TRIM() to handle leading/trailing spaces in part numbers
                    cursor.execute('''
                        UPDATE mro_inventory SET
                            name = %s, model_number = %s, equipment = %s, engineering_system = %s,
                            unit_of_measure = %s, quantity_in_stock = %s, unit_price = %s,
                            minimum_stock = %s, supplier = %s, location = %s, rack = %s,
                            row = %s, bin = %s, picture_1_path = %s, picture_2_path = %s,
                            picture_1_data = %s, picture_2_data = %s,
                            notes = %s, status = %s, last_updated = %s
                        WHERE TRIM(part_number) = %s
                    ''', (
                        fields['name'].get(),
                        fields['model_number'].get(),
                        fields['equipment'].get(),
                        fields['engineering_system'].get(),
                        fields['unit_of_measure'].get(),
                        float(fields['quantity_in_stock'].get() or 0),
                        float(fields['unit_price'].get() or 0),
                        float(fields['minimum_stock'].get() or 0),
                        fields['supplier'].get(),
                        fields['location'].get(),
                        fields['rack'].get(),
                        fields['row'].get(),
                        fields['bin'].get(),
                        final_pic1_path,
                        final_pic2_path,
                        pic1_data,
                        pic2_data,
                        notes_text,
                        fields['status'].get(),
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        part_number
                    ))

                messagebox.showinfo("Success", "Part updated successfully!")
                self._csv_sync_async(part_number)
                dialog.destroy()
                self.refresh_mro_list()

            except Exception as e:
                messagebox.showerror("Error", f"Failed to update part: {str(e)}")
        
        ttk.Button(btn_frame, text="💾 Update Part", command=update_part, width=20).pack(side='left', padx=10)
        ttk.Button(btn_frame, text="❌ Cancel", command=dialog.destroy, width=20).pack(side='left', padx=10)
        
        # Pack canvas and scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
    
    def delete_selected_part(self):
        """Delete selected part or mark as inactive if it has transaction history"""
        selected = self.mro_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a part to delete")
            return

        # Use .set() method to get the displayed text from TreeView to preserve leading zeros
        # This avoids issues where TreeView converts "0319" to integer 319
        part_number = str(self.mro_tree.set(selected[0], 'Part Number')).strip()
        part_name = str(self.mro_tree.set(selected[0], 'Name')).strip()

        try:
            cursor = self.conn.cursor()

            # Check if part has any transaction history
            # Use TRIM() to handle leading/trailing spaces in part numbers
            cursor.execute(
                'SELECT COUNT(*) FROM mro_stock_transactions WHERE TRIM(part_number) = %s',
                (part_number,)
            )
            transaction_count = cursor.fetchone()[0]

            # Check if part has been used in CM work orders
            # Use TRIM() to handle leading/trailing spaces in part numbers
            cursor.execute(
                'SELECT COUNT(*) FROM cm_parts_used WHERE TRIM(part_number) = %s',
                (part_number,)
            )
            cm_usage_count = cursor.fetchone()[0]

            total_history = transaction_count + cm_usage_count

            if total_history > 0:
                # Part has history - offer to mark as inactive instead
                result = messagebox.askyesno(
                    "Part Has Transaction History",
                    f"Part '{part_name}' (#{part_number}) has transaction history:\n\n"
                    f"• {transaction_count} stock transaction(s)\n"
                    f"• {cm_usage_count} CM work order usage(s)\n\n"
                    f"To preserve historical data, this part cannot be deleted.\n\n"
                    f"Would you like to mark it as INACTIVE instead?\n"
                    f"(It will be hidden from active inventory but history will be preserved)"
                )

                if result:
                    # Use TRIM() to handle leading/trailing spaces in part numbers
                    cursor.execute(
                        "UPDATE mro_inventory SET status = 'Inactive' WHERE TRIM(part_number) = %s",
                        (part_number,)
                    )
                    self.conn.commit()
                    self._csv_sync_async(part_number)
                    messagebox.showinfo("Success",
                                      f"Part '{part_name}' marked as INACTIVE.\n\n"
                                      f"Transaction history preserved.")
                    self.refresh_mro_list()
                else:
                    cursor.close()
                    return
            else:
                # No history - safe to delete permanently
                result = messagebox.askyesno("Confirm Delete",
                                            f"Are you sure you want to permanently delete:\n\n"
                                            f"Part Number: {part_number}\n"
                                            f"Name: {part_name}\n\n"
                                            f"This part has no transaction history.\n"
                                            f"This action cannot be undone!")

                if result:
                    # Use TRIM() to handle leading/trailing spaces in part numbers
                    cursor.execute('DELETE FROM mro_inventory WHERE TRIM(part_number) = %s', (part_number,))
                    self.conn.commit()
                    self._csv_remove_async(part_number)
                    messagebox.showinfo("Success", "Part deleted successfully!")
                    self.refresh_mro_list()
                else:
                    cursor.close()
                    return

            cursor.close()

        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Error", f"Failed to delete/deactivate part: {str(e)}")
    
    
    def view_part_details(self):
        """Enhanced part details view with CM history integration"""
        selected = self.mro_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a part to view")
            return

        # Use .set() method to get the displayed text from TreeView to preserve leading zeros
        # This avoids issues where TreeView converts "0319" to integer 319
        part_number = str(self.mro_tree.set(selected[0], 'Part Number')).strip()

        try:
            # Get full part data - use explicit column list to ensure correct order
            with db_pool.get_cursor(commit=False) as cursor:
                # Use TRIM() to handle leading/trailing spaces in part numbers
                cursor.execute('''
                    SELECT id, name, part_number, model_number, equipment, engineering_system,
                           unit_of_measure, quantity_in_stock, unit_price, minimum_stock,
                           supplier, location, rack, row, bin, picture_1_path,
                           picture_2_path, picture_1_data, picture_2_data, notes,
                           last_updated, created_date, status
                    FROM mro_inventory WHERE TRIM(part_number) = %s
                ''', (part_number,))
                part_data = cursor.fetchone()

                if not part_data:
                    # Enhanced error message for debugging
                    messagebox.showerror("Error",
                        f"Part not found in database.\n\n"
                        f"Part number from tree: '{part_number}'\n"
                        f"Length: {len(part_number)} characters\n\n"
                        f"Try clicking the Refresh button and then try again.")
                    return

                # Extract all data while cursor is still active (RealDictCursor data becomes invalid after context exits)
                id = part_data['id']
                name = part_data['name']
                part_num = part_data['part_number']
                model = part_data['model_number']
                equipment = part_data['equipment']
                eng_system = part_data['engineering_system']
                unit = part_data['unit_of_measure']
                qty_stock = part_data['quantity_in_stock']
                unit_price = part_data['unit_price']
                min_stock = part_data['minimum_stock']
                supplier = part_data['supplier']
                location = part_data['location']
                rack = part_data['rack']
                row_num = part_data['row']
                bin_num = part_data['bin']
                pic1_path = part_data['picture_1_path']
                pic2_path = part_data['picture_2_path']
                pic1_data = part_data['picture_1_data']
                pic2_data = part_data['picture_2_data']
                notes = part_data['notes']
                last_updated = part_data['last_updated']
                created_date = part_data['created_date']
                status = part_data['status']
        except Exception as e:
            messagebox.showerror("Database Error",
                f"Error loading part details: {str(e)}\n\n"
                f"Part number: '{part_number}'")
            return

        # Create details dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Part Details - {part_number}")
        dialog.geometry("900x700")
        dialog.transient(self.root)

        # Create notebook for tabs
        notebook = ttk.Notebook(dialog)
        notebook.pack(fill='both', expand=True, padx=10, pady=10)

        # ============================================================
        # TAB 1: Part Information
        # ============================================================
        info_frame = ttk.Frame(notebook)
        notebook.add(info_frame, text='📋 Part Information')

        # Create scrollable canvas
        canvas = tk.Canvas(info_frame)
        scrollbar = ttk.Scrollbar(info_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Data already extracted from cursor context above
        row = 0
    
        # Display part information
        fields = [
            ("Part Number:", part_num),
            ("Part Name:", name),
            ("Model Number:", model or 'N/A'),
            ("Equipment:", equipment or 'N/A'),
            ("Engineering System:", eng_system or 'N/A'),
            ("", ""),  # Spacer
            ("Quantity in Stock:", f"{qty_stock} {unit}"),
            ("Minimum Stock:", f"{min_stock} {unit}"),
            ("Unit of Measure:", unit),
            ("Unit Price:", f"${unit_price:.2f}"),
            ("Total Value:", f"${qty_stock * unit_price:.2f}"),
            ("", ""),  # Spacer
            ("Supplier:", supplier or 'N/A'),
            ("Location:", location or 'N/A'),
            ("Rack:", rack or 'N/A'),
            ("Row:", row_num or 'N/A'),
            ("Bin:", bin_num or 'N/A'),
            ("", ""),  # Spacer
            ("Status:", status),
            ("Created Date:", created_date[:10] if created_date else 'N/A'),
            ("Last Updated:", last_updated[:10] if last_updated else 'N/A'),
        ]
    
        for label, value in fields:
            if label:  # Not a spacer
                ttk.Label(scrollable_frame, text=label, 
                        font=('Arial', 10, 'bold')).grid(
                            row=row, column=0, sticky='w', padx=20, pady=5)
                ttk.Label(scrollable_frame, text=str(value), 
                        font=('Arial', 10)).grid(
                            row=row, column=1, sticky='w', padx=20, pady=5)
            row += 1
    
        # Notes section
        if notes:
            ttk.Label(scrollable_frame, text="Notes:",
                    font=('Arial', 10, 'bold')).grid(
                        row=row, column=0, sticky='nw', padx=20, pady=5)
            notes_display = tk.Text(scrollable_frame, width=50, height=4, wrap='word')
            notes_display.insert('1.0', notes)
            notes_display.config(state='disabled')
            notes_display.grid(row=row, column=1, sticky='w', padx=20, pady=5)
            row += 1

        # Pictures section
        row += 1
        if pic1_data or pic2_data or pic1_path or pic2_path:
            ttk.Label(scrollable_frame, text="Pictures:",
                    font=('Arial', 10, 'bold')).grid(
                        row=row, column=0, sticky='nw', padx=20, pady=10)

            pic_frame = ttk.Frame(scrollable_frame)
            pic_frame.grid(row=row, column=1, sticky='w', padx=20, pady=10)

            # Display Picture 1
            pic1_displayed = False
            if pic1_data:
                try:
                    # Load from database binary data
                    img1 = Image.open(io.BytesIO(pic1_data))
                    img1.thumbnail((200, 200))
                    photo1 = ImageTk.PhotoImage(img1)
                    label1 = ttk.Label(pic_frame, image=photo1)
                    label1.image = photo1  # Keep a reference
                    label1.pack(side='left', padx=5)
                    ttk.Label(pic_frame, text="Picture 1",
                            font=('Arial', 8)).pack(side='left', padx=5)
                    pic1_displayed = True
                except Exception as e:
                    ttk.Label(pic_frame, text=f"Picture 1: Error loading from database",
                            foreground='red').pack(side='left', padx=5)
            elif pic1_path and os.path.exists(pic1_path):
                try:
                    # Fallback to file path for legacy data
                    img1 = Image.open(pic1_path)
                    img1.thumbnail((200, 200))
                    photo1 = ImageTk.PhotoImage(img1)
                    label1 = ttk.Label(pic_frame, image=photo1)
                    label1.image = photo1  # Keep a reference
                    label1.pack(side='left', padx=5)
                    ttk.Label(pic_frame, text="Picture 1",
                            font=('Arial', 8)).pack(side='left', padx=5)
                    pic1_displayed = True
                except Exception as e:
                    ttk.Label(pic_frame, text=f"Picture 1: Error loading image",
                            foreground='red').pack(side='left', padx=5)
            elif pic1_path:
                ttk.Label(pic_frame, text=f"Picture 1: (File not found)",
                        foreground='gray').pack(side='left', padx=5)

            # Display Picture 2
            pic2_displayed = False
            if pic2_data:
                try:
                    # Load from database binary data
                    img2 = Image.open(io.BytesIO(pic2_data))
                    img2.thumbnail((200, 200))
                    photo2 = ImageTk.PhotoImage(img2)
                    label2 = ttk.Label(pic_frame, image=photo2)
                    label2.image = photo2  # Keep a reference
                    label2.pack(side='left', padx=5)
                    ttk.Label(pic_frame, text="Picture 2",
                            font=('Arial', 8)).pack(side='left', padx=5)
                    pic2_displayed = True
                except Exception as e:
                    ttk.Label(pic_frame, text=f"Picture 2: Error loading from database",
                            foreground='red').pack(side='left', padx=5)
            elif pic2_path and os.path.exists(pic2_path):
                try:
                    # Fallback to file path for legacy data
                    img2 = Image.open(pic2_path)
                    img2.thumbnail((200, 200))
                    photo2 = ImageTk.PhotoImage(img2)
                    label2 = ttk.Label(pic_frame, image=photo2)
                    label2.image = photo2  # Keep a reference
                    label2.pack(side='left', padx=5)
                    ttk.Label(pic_frame, text="Picture 2",
                            font=('Arial', 8)).pack(side='left', padx=5)
                    pic2_displayed = True
                except Exception as e:
                    ttk.Label(pic_frame, text=f"Picture 2: Error loading image",
                            foreground='red').pack(side='left', padx=5)
            elif pic2_path:
                ttk.Label(pic_frame, text=f"Picture 2: (File not found)",
                        foreground='gray').pack(side='left', padx=5)

            row += 1

        # Stock status indicator
        row += 1
        if qty_stock < min_stock:
            status_text = "⚠️ LOW STOCK - Reorder Recommended"
            status_color = 'red'
        elif qty_stock < min_stock * 1.5:
            status_text = "⚡ Stock Getting Low"
            status_color = 'orange'
        else:
            status_text = "✅ Stock Level OK"
            status_color = 'green'
    
        ttk.Label(scrollable_frame, text=status_text, 
                font=('Arial', 11, 'bold'), foreground=status_color).grid(
                    row=row, column=0, columnspan=2, pady=20)
    
        # ============================================================
        # TAB 2: CM Usage History (NEW INTEGRATION!)
        # ============================================================
        history_frame = ttk.Frame(notebook)
        notebook.add(history_frame, text='🔧 CM Usage History')
        
        # Header
        header_frame = ttk.Frame(history_frame)
        header_frame.pack(fill='x', padx=10, pady=10)
    
        ttk.Label(header_frame, text=f"Corrective Maintenance History for {part_number}",
                font=('Arial', 11, 'bold')).pack()

        try:
            # Get CM usage data - use new cursor context
            with db_pool.get_cursor(commit=False) as cursor:
                # Use TRIM() to handle leading/trailing spaces in part numbers
                cursor.execute('''
                    SELECT
                        cp.cm_number,
                        cm.description,
                        cm.bfm_equipment_no,
                        cp.quantity_used,
                        mi.unit_price,
                        cp.recorded_date,
                        cp.recorded_by,
                        cm.status,
                        cp.notes
                    FROM cm_parts_used cp
                    LEFT JOIN corrective_maintenance cm ON cp.cm_number = cm.cm_number
                    LEFT JOIN mro_inventory mi ON cp.part_number = mi.part_number
                    WHERE TRIM(cp.part_number) = %s
                    ORDER BY cp.recorded_date DESC
                    LIMIT 50
                ''', (part_number,))

                cm_history = cursor.fetchall()

                # Statistics frame
                stats_frame = ttk.LabelFrame(history_frame, text="Usage Statistics", padding=10)
                stats_frame.pack(fill='x', padx=10, pady=5)

                if cm_history:
                    total_cms = len(cm_history)
                    # Access dictionary keys instead of indices
                    total_qty_used = sum(row['quantity_used'] for row in cm_history)
                    # Calculate total cost using current unit_price, not cached total_cost
                    total_cost = sum((row['quantity_used'] or 0) * (row['unit_price'] or 0) for row in cm_history)

                    stats_text = (f"Total CMs: {total_cms} | "
                                f"Total Quantity Used: {total_qty_used:.2f} {unit} | "
                                f"Total Cost: ${total_cost:.2f}")
                    ttk.Label(stats_frame, text=stats_text, font=('Arial', 10)).pack()

                    # Recent usage (last 30 days)
                    # Use TRIM() to handle leading/trailing spaces in part numbers
                    cursor.execute('''
                        SELECT SUM(quantity_used)
                        FROM cm_parts_used
                        WHERE TRIM(part_number) = %s
                        AND recorded_date::timestamp >= CURRENT_DATE - INTERVAL '30 days'
                    ''', (part_number,))

                    recent_result = cursor.fetchone()
                    recent_usage = recent_result['sum'] if recent_result and recent_result['sum'] else 0
                    ttk.Label(stats_frame, text=f"Usage Last 30 Days: {recent_usage:.2f} {unit}",
                            font=('Arial', 9, 'italic')).pack()
                else:
                    ttk.Label(stats_frame, text="No CM usage history available",
                            font=('Arial', 10, 'italic')).pack()
        except Exception as e:
            messagebox.showerror("Database Error", f"Error loading CM history: {str(e)}")
            return
    
        # History treeview
        tree_frame = ttk.Frame(history_frame)
        tree_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
        columns = ('CM #', 'Description', 'Equipment', 'Qty Used', 'Cost', 'Date', 'Technician', 'Status', 'Notes')
        history_tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=15)
    
        for col in columns:
            history_tree.heading(col, text=col)
    
        history_tree.column('CM #', width=100)
        history_tree.column('Description', width=150)
        history_tree.column('Equipment', width=100)
        history_tree.column('Qty Used', width=70)
        history_tree.column('Cost', width=70)
        history_tree.column('Date', width=85)
        history_tree.column('Technician', width=100)
        history_tree.column('Status', width=70)
        history_tree.column('Notes', width=120)
    
        for row in cm_history:
            # Access dictionary keys instead of indices
            # Calculate cost from current unit_price, not cached total_cost
            qty = row['quantity_used'] or 0
            unit_price = row['unit_price'] or 0
            calculated_cost = qty * unit_price

            history_tree.insert('', 'end', values=(
                row['cm_number'],
                row['description'][:30] + '...' if row['description'] and len(row['description']) > 30 else row['description'] or 'N/A',
                row['bfm_equipment_no'] or 'N/A',
                f"{qty:.2f}",
                f"${calculated_cost:.2f}",
                row['recorded_date'][:10] if row['recorded_date'] else '',
                row['recorded_by'] or 'N/A',
                row['status'] or 'Unknown',
                row['notes'][:20] + '...' if row['notes'] and len(row['notes']) > 20 else row['notes'] or ''
            ))
    
        history_tree.pack(side='left', fill='both', expand=True)
    
        scrollbar_hist = ttk.Scrollbar(tree_frame, orient='vertical', command=history_tree.yview)
        scrollbar_hist.pack(side='right', fill='y')
        history_tree.configure(yscrollcommand=scrollbar_hist.set)
        
        # Double-click to view CM details
        def on_cm_double_click(event):
            selected = history_tree.selection()
            if selected:
                item = history_tree.item(selected[0])
                cm_number = item['values'][0]
            
                # Try to open CM details if main app has the method
                if hasattr(self.parent_app, 'parts_integration'):
                    self.parent_app.parts_integration.show_cm_parts_details(cm_number)
    
        history_tree.bind('<Double-Button-1>', on_cm_double_click)
    
        # ============================================================
        # TAB 3: Transaction History (All transactions)
        # ============================================================
        trans_frame = ttk.Frame(notebook)
        notebook.add(trans_frame, text='📊 All Transactions')
    
        # Header
        trans_header = ttk.Frame(trans_frame)
        trans_header.pack(fill='x', padx=10, pady=10)
    
        ttk.Label(trans_header, text=f"All Stock Transactions for {part_number}", 
                font=('Arial', 11, 'bold')).pack()
    
        # Get all transactions - use new cursor context
        with db_pool.get_cursor(commit=False) as cursor:
            # Use TRIM() to handle leading/trailing spaces in part numbers
            cursor.execute('''
                SELECT
                    transaction_date,
                    transaction_type,
                    quantity,
                    technician_name,
                    work_order,
                    notes
                FROM mro_stock_transactions
                WHERE TRIM(part_number) = %s
                ORDER BY transaction_date DESC
                LIMIT 100
            ''', (part_number,))

            transactions = cursor.fetchall()

            # Transactions treeview
            trans_tree_frame = ttk.Frame(trans_frame)
            trans_tree_frame.pack(fill='both', expand=True, padx=10, pady=5)

            trans_columns = ('Date', 'Type', 'Quantity', 'Technician', 'Work Order', 'Notes')
            trans_tree = ttk.Treeview(trans_tree_frame, columns=trans_columns, show='headings', height=20)

            for col in trans_columns:
                trans_tree.heading(col, text=col)

            trans_tree.column('Date', width=150)
            trans_tree.column('Type', width=120)
            trans_tree.column('Quantity', width=80)
            trans_tree.column('Technician', width=120)
            trans_tree.column('Work Order', width=120)
            trans_tree.column('Notes', width=200)

            for row in transactions:
                # Access dictionary keys instead of indices
                qty = row['quantity']
                qty_display = f"+{qty:.2f}" if qty > 0 else f"{qty:.2f}"

                trans_tree.insert('', 'end', values=(
                    row['transaction_date'][:19] if row['transaction_date'] else '',
                    row['transaction_type'] or 'N/A',
                    qty_display,
                    row['technician_name'] or 'N/A',
                    row['work_order'] or 'N/A',
                    row['notes'] or ''
                ), tags=('addition',) if qty > 0 else ('deduction',))
    
        trans_tree.pack(side='left', fill='both', expand=True)
    
        scrollbar_trans = ttk.Scrollbar(trans_tree_frame, orient='vertical', command=trans_tree.yview)
        scrollbar_trans.pack(side='right', fill='y')
        trans_tree.configure(yscrollcommand=scrollbar_trans.set)
    
        # Color code transactions
        trans_tree.tag_configure('addition', foreground='green')
        trans_tree.tag_configure('deduction', foreground='red')
    
        # ============================================================
        # Bottom buttons
        # ============================================================
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill='x', padx=10, pady=10)
    
        def view_all_cm_history():
            """Open dedicated CM history viewer"""
            if hasattr(self.parent_app, 'parts_integration'):
                self.parent_app.parts_integration.show_part_cm_history(part_number)
    
        if cm_history:
            ttk.Button(button_frame, text="📈 View Full CM Analysis", 
                    command=view_all_cm_history).pack(side='left', padx=5)
    
        ttk.Button(button_frame, text="Close", 
                command=dialog.destroy).pack(side='right', padx=5)

    
    def show_parts_usage_report(self):
        """Show comprehensive parts usage report"""
        report_dialog = tk.Toplevel(self.root)
        report_dialog.title("Parts Usage by CM Report")
        report_dialog.geometry("900x600")

        # Create report content
        report_frame = ttk.Frame(report_dialog)
        report_frame.pack(fill='both', expand=True, padx=10, pady=10)

        ttk.Label(report_frame, text="Parts Consumption Analysis",
                font=('Arial', 12, 'bold')).pack(pady=10)

        try:
            # Get summary data
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT
                    mi.part_number,
                    mi.name,
                    mi.quantity_in_stock,
                    COUNT(DISTINCT cp.cm_number) as cm_count,
                    SUM(cp.quantity_used) as total_qty_used,
                    mi.unit_price,
                    SUM(cp.quantity_used * mi.unit_price) as total_cost
                FROM cm_parts_used cp
                JOIN mro_inventory mi ON cp.part_number = mi.part_number
                WHERE cp.recorded_date::timestamp >= CURRENT_DATE - INTERVAL '90 days'
                GROUP BY mi.part_number, mi.name, mi.quantity_in_stock, mi.unit_price
                ORDER BY total_cost DESC
                LIMIT 50
            ''')

            usage_data = cursor.fetchall()
        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Database Error", f"Error loading usage report: {str(e)}")
            report_dialog.destroy()
            return

        # Display in treeview
        columns = ('Part #', 'Part Name', 'Qty in Stock', 'CMs Used In', 'Total Qty Used', 'Unit Price', 'Total Cost')
        tree = ttk.Treeview(report_frame, columns=columns, show='headings')

        for col in columns:
            tree.heading(col, text=col)

        tree.column('Part #', width=120)
        tree.column('Part Name', width=200)
        tree.column('Qty in Stock', width=100)
        tree.column('CMs Used In', width=100)
        tree.column('Total Qty Used', width=110)
        tree.column('Unit Price', width=100)
        tree.column('Total Cost', width=100)

        for row in usage_data:
            tree.insert('', 'end', values=(
                row[0],  # part_number
                row[1],  # name
                f"{row[2]:.2f}",  # quantity_in_stock
                row[3],  # cm_count
                f"{row[4]:.2f}" if row[4] else '0.00',  # total_qty_used
                f"${row[5]:.2f}" if row[5] else '$0.00',  # unit_price
                f"${row[6]:.2f}" if row[6] else '$0.00'  # total_cost
            ))
    
        tree.pack(fill='both', expand=True, padx=10, pady=10)
    
        ttk.Label(report_frame, text="(Last 90 days)", 
                font=('Arial', 9, 'italic')).pack()
    
        ttk.Button(report_dialog, text="Close", 
                command=report_dialog.destroy).pack(pady=10)
    
    
    def stock_transaction_dialog(self, part_number):
        """Dialog for stock transactions (add/remove stock)"""
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Stock Transaction: {part_number}")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Get current stock
        cursor = self.conn.cursor()
        # Use TRIM() to handle leading/trailing spaces in part numbers
        cursor.execute('SELECT quantity_in_stock, unit_of_measure, name FROM mro_inventory WHERE TRIM(part_number) = %s',
                      (part_number,))
        result = cursor.fetchone()
        current_stock = result[0] if result else 0
        unit = result[1] if result else ''
        part_name = result[2] if result else ''
        
        ttk.Label(dialog, text=f"Part: {part_name}", 
                 font=('Arial', 12, 'bold')).pack(pady=10)
        ttk.Label(dialog, text=f"Current Stock: {current_stock} {unit}", 
                 font=('Arial', 11)).pack(pady=5)
        
        # Transaction type
        ttk.Label(dialog, text="Transaction Type:").pack(pady=5)
        trans_type = tk.StringVar(value='Add')
        ttk.Radiobutton(dialog, text="➕ Add Stock", variable=trans_type, 
                       value='Add').pack()
        ttk.Radiobutton(dialog, text="➖ Remove Stock", variable=trans_type, 
                       value='Remove').pack()
        
        # Quantity
        ttk.Label(dialog, text="Quantity:").pack(pady=5)
        qty_entry = ttk.Entry(dialog, width=20)
        qty_entry.pack(pady=5)
        
        # Work order
        ttk.Label(dialog, text="Work Order (Optional):").pack(pady=5)
        wo_entry = ttk.Entry(dialog, width=30)
        wo_entry.pack(pady=5)
        
        # Notes
        ttk.Label(dialog, text="Notes:").pack(pady=5)
        notes_text = tk.Text(dialog, height=4, width=50)
        notes_text.pack(pady=5)
        
        def process_transaction():
            try:
                qty = float(qty_entry.get())
                trans_type_val = trans_type.get()
                
                if trans_type_val == 'Remove':
                    qty = -qty
                
                new_stock = current_stock + qty
                
                if new_stock < 0:
                    messagebox.showerror("Error", "Cannot remove more stock than available!")
                    return
                
                # Update stock
                cursor = self.conn.cursor()
                # Use TRIM() to handle leading/trailing spaces in part numbers
                cursor.execute('''
                    UPDATE mro_inventory
                    SET quantity_in_stock = %s, last_updated = %s
                    WHERE TRIM(part_number) = %s
                ''', (new_stock, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), part_number))
                
                # Log transaction
                cursor.execute('''
                    INSERT INTO mro_stock_transactions 
                    (part_number, transaction_type, quantity, technician_name, 
                     work_order, notes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (
                    part_number,
                    trans_type_val,
                    abs(qty),
                    self.parent_app.current_user if hasattr(self.parent_app, 'current_user') else 'System',
                    wo_entry.get(),
                    notes_text.get('1.0', 'end-1c')
                ))
                
                self.conn.commit()
                messagebox.showinfo("Success", 
                                  f"Stock updated!\n"
                                  f"Previous: {current_stock} {unit}\n"
                                  f"Change: {qty:+.1f} {unit}\n"
                                  f"New Stock: {new_stock} {unit}")
                dialog.destroy()
                self.refresh_mro_list()
                
            except ValueError:
                messagebox.showerror("Error", "Please enter a valid quantity")
            except Exception as e:
                messagebox.showerror("Error", f"Transaction failed: {str(e)}")
        
        ttk.Button(dialog, text="💾 Process Transaction", 
                  command=process_transaction, width=25).pack(pady=10)
        ttk.Button(dialog, text="❌ Cancel", 
                  command=dialog.destroy, width=25).pack(pady=5)
    
    def import_from_file(self):
        """Import parts from inventory.txt or CSV file"""
        file_path = filedialog.askopenfilename(
            title="Select Inventory File",
            filetypes=[("Text files", "*.txt"), ("CSV files", "*.csv"), ("All files", "*.*")]
        )
        
        if not file_path:
            return
        
        try:
            imported_count = 0
            skipped_count = 0
            
            with open(file_path, 'r', encoding='utf-8') as f:
                if file_path.endswith('.csv'):
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            self.import_part_from_dict(row)
                            imported_count += 1
                        except:
                            skipped_count += 1
                else:
                    # Parse text file format
                    content = f.read()
                    # You can customize this based on your inventory.txt format
                    messagebox.showinfo("Info", 
                                      "Please use CSV format for bulk import.\n\n"
                                      "Required columns:\n"
                                      "Name, Part Number, Model Number, Equipment, "
                                      "Engineering System, Unit of Measure, Quantity in Stock, "
                                      "Unit Price, Minimum Stock, Supplier, Location, Rack, Row, Bin")
                    return
            
            self.conn.commit()
            messagebox.showinfo("Import Complete", 
                              f"Successfully imported: {imported_count} parts\n"
                              f"Skipped (duplicates/errors): {skipped_count} parts")
            self.refresh_mro_list()
            
        except Exception as e:
            messagebox.showerror("Import Error", f"Failed to import file:\n{str(e)}")
    
    def import_part_from_dict(self, data):
        """Import a single part from dictionary"""
        cursor = self.conn.cursor()
        
        cursor.execute('''
            INSERT INTO mro_inventory (
                name, part_number, model_number, equipment, engineering_system,
                unit_of_measure, quantity_in_stock, unit_price, minimum_stock,
                supplier, location, rack, row, bin
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (part_number) DO NOTHING
        ''', (
            data.get('Name', ''),
            data.get('Part Number', ''),
            data.get('Model Number', ''),
            data.get('Equipment', ''),
            data.get('Engineering System', ''),
            data.get('Unit of Measure', ''),
            float(data.get('Quantity in Stock', 0) or 0),
            float(data.get('Unit Price', 0) or 0),
            float(data.get('Minimum Stock', 0) or 0),
            data.get('Supplier', ''),
            data.get('Location', ''),
            data.get('Rack', ''),
            data.get('Row', ''),
            data.get('Bin', '')
        ))
    
    def export_to_csv(self):
        """Export inventory to CSV"""
        file_path = filedialog.asksaveasfilename(
            title="Export Inventory",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        
        if not file_path:
            return
        
        try:
            cursor = self.conn.cursor()
            # Select specific columns for export (exclude binary picture data)
            cursor.execute('''
                SELECT id, name, part_number, model_number, equipment, engineering_system,
                       unit_of_measure, quantity_in_stock, unit_price, minimum_stock,
                       supplier, location, rack, row, bin, picture_1_path, picture_2_path,
                       notes, last_updated, created_date, status
                FROM mro_inventory ORDER BY part_number
            ''')
            rows = cursor.fetchall()

            columns = ['ID', 'Name', 'Part Number', 'Model Number', 'Equipment',
                      'Engineering System', 'Unit of Measure', 'Quantity in Stock',
                      'Unit Price', 'Minimum Stock', 'Supplier', 'Location', 'Rack',
                      'Row', 'Bin', 'Picture 1 Path', 'Picture 2 Path', 'Notes',
                      'Last Updated', 'Created Date', 'Status']

            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                writer.writerows(rows)

            messagebox.showinfo("Success", f"Inventory exported to:\n{file_path}")

        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export:\n{str(e)}")
    
    def generate_stock_report(self):
        """Generate comprehensive stock report"""
        report_dialog = tk.Toplevel(self.root)
        report_dialog.title("Stock Report")
        report_dialog.geometry("900x700")
        report_dialog.transient(self.root)
        
        # Report text
        report_frame = ttk.Frame(report_dialog)
        report_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        report_text = tk.Text(report_frame, wrap='word', font=('Courier', 10))
        report_scrollbar = ttk.Scrollbar(report_frame, command=report_text.yview)
        report_text.configure(yscrollcommand=report_scrollbar.set)
        
        report_text.pack(side='left', fill='both', expand=True)
        report_scrollbar.pack(side='right', fill='y')
        
        # Generate report
        cursor = self.conn.cursor()
        
        report = []
        report.append("=" * 80)
        report.append("MRO INVENTORY STOCK REPORT")
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("=" * 80)
        report.append("")
        
        # Summary statistics
        cursor.execute("SELECT COUNT(*) FROM mro_inventory WHERE status = 'Active'")
        total_parts = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(quantity_in_stock * unit_price) FROM mro_inventory WHERE status = 'Active'")
        total_value = cursor.fetchone()[0] or 0
        
        cursor.execute('''
            SELECT COUNT(*) FROM mro_inventory
            WHERE quantity_in_stock < minimum_stock AND status = 'Active'
        ''')
        low_stock_count = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(quantity_in_stock) FROM mro_inventory WHERE status = 'Active'")
        total_quantity = cursor.fetchone()[0] or 0

        report.append("SUMMARY")
        report.append("-" * 80)
        report.append(f"Total Active Parts: {total_parts}")
        report.append(f"Total Quantity in Stock: {total_quantity:,.1f}")
        report.append(f"Total Inventory Value: ${total_value:,.2f}")
        report.append(f"Low Stock Items: {low_stock_count}")
        report.append("")
        
        # Low stock items
        if low_stock_count > 0:
            report.append("LOW STOCK ALERTS")
            report.append("-" * 80)
            cursor.execute('''
                SELECT part_number, name, quantity_in_stock, minimum_stock, 
                       unit_of_measure, location
                FROM mro_inventory 
                WHERE quantity_in_stock < minimum_stock AND status = 'Active'
                ORDER BY (minimum_stock - quantity_in_stock) DESC
            ''')
            
            for row in cursor.fetchall():
                part_no, name, qty, min_qty, unit, loc = row
                deficit = min_qty - qty
                report.append(f"  Part: {part_no} - {name}")
                report.append(f"  Current: {qty} {unit} | Minimum: {min_qty} {unit} | Deficit: {deficit} {unit}")
                report.append(f"  Location: {loc}")
                report.append("")
        
        # Inventory by system
        report.append("INVENTORY BY ENGINEERING SYSTEM")
        report.append("-" * 80)
        cursor.execute('''
            SELECT engineering_system, COUNT(*), SUM(quantity_in_stock * unit_price)
            FROM mro_inventory 
            WHERE status = 'Active'
            GROUP BY engineering_system
            ORDER BY engineering_system
        ''')
        
        for row in cursor.fetchall():
            system, count, value = row
            report.append(f"  {system or 'Unknown'}: {count} parts, ${value or 0:,.2f} value")

        report.append("")

        # CM Parts Usage by Month
        report.append("CM PARTS USAGE - MONTHLY BREAKDOWN")
        report.append("-" * 80)

        try:
            # Get monthly summary of parts used in CMs
            cursor.execute('''
                SELECT
                    TO_CHAR(recorded_date::timestamp, 'YYYY-MM') as month,
                    COUNT(DISTINCT cm_number) as cm_count,
                    COUNT(*) as parts_entries,
                    SUM(quantity_used) as total_quantity,
                    SUM(total_cost) as total_cost
                FROM cm_parts_used
                GROUP BY TO_CHAR(recorded_date::timestamp, 'YYYY-MM')
                ORDER BY month DESC
                LIMIT 12
            ''')

            monthly_data = cursor.fetchall()

            if monthly_data:
                report.append("")
                report.append(f"{'Month':<12} {'CMs':<8} {'Parts':<10} {'Qty Used':<15} {'Total Cost':<15}")
                report.append("-" * 80)

                grand_total_cost = 0
                for row in monthly_data:
                    month = row[0]
                    cm_count = row[1]
                    parts_entries = row[2]
                    total_qty = float(row[3]) if row[3] else 0
                    total_cost = float(row[4]) if row[4] else 0
                    grand_total_cost += total_cost

                    report.append(f"{month:<12} {cm_count:<8} {parts_entries:<10} {total_qty:<15.1f} ${total_cost:<14,.2f}")

                report.append("-" * 80)
                report.append(f"{'Total Cost (Last 12 Months):':<60} ${grand_total_cost:,.2f}")
            else:
                report.append("  No CM parts usage data available")

            report.append("")

            # Top 10 most used parts in CMs
            report.append("TOP 10 PARTS USED IN CMs (ALL TIME)")
            report.append("-" * 80)

            cursor.execute('''
                SELECT
                    cpu.part_number,
                    mi.name,
                    COUNT(DISTINCT cpu.cm_number) as cm_count,
                    SUM(cpu.quantity_used) as total_qty,
                    mi.unit_price,
                    SUM(cpu.quantity_used * mi.unit_price) as total_cost
                FROM cm_parts_used cpu
                LEFT JOIN mro_inventory mi ON cpu.part_number = mi.part_number
                GROUP BY cpu.part_number, mi.name, mi.unit_price
                ORDER BY total_qty DESC
                LIMIT 10
            ''')

            top_parts = cursor.fetchall()

            if top_parts:
                report.append("")
                report.append(f"{'Part Number':<15} {'Description':<30} {'CMs':<8} {'Qty':<12} {'Cost':<15}")
                report.append("-" * 80)

                for row in top_parts:
                    part_num = row[0]
                    name = (row[1] or 'N/A')[:28]  # Truncate to fit
                    cm_count = row[2]
                    qty = float(row[3]) if row[3] else 0
                    # total_cost is now at index 5 (calculated from current unit_price)
                    cost = float(row[5]) if row[5] else 0

                    report.append(f"{part_num:<15} {name:<30} {cm_count:<8} {qty:<12.1f} ${cost:<14,.2f}")
            else:
                report.append("  No parts usage data available")

        except Exception as e:
            report.append(f"  Error loading CM parts data: {str(e)}")

        report.append("")
        report.append("=" * 80)
        report.append("END OF REPORT")
        report.append("=" * 80)
        
        report_text.insert('1.0', '\n'.join(report))
        report_text.config(state='disabled')
        
        # Export button
        def export_report():
            file_path = filedialog.asksaveasfilename(
                title="Export Stock Report",
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
            )
            if file_path:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(report))
                messagebox.showinfo("Success", f"Report exported to:\n{file_path}")
        
        ttk.Button(report_dialog, text="📤 Export Report", 
                  command=export_report).pack(pady=10)
    
    def show_low_stock(self):
        """Show low stock alert dialog"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT part_number, name, quantity_in_stock, minimum_stock, 
                   unit_of_measure, location, supplier
            FROM mro_inventory 
            WHERE quantity_in_stock < minimum_stock AND status = 'Active'
            ORDER BY (minimum_stock - quantity_in_stock) DESC
        ''')
        
        low_stock_items = cursor.fetchall()
        
        if not low_stock_items:
            messagebox.showinfo("Stock Status", "✅ All items are adequately stocked!")
            return
        
        # Create alert dialog
        alert_dialog = tk.Toplevel(self.root)
        alert_dialog.title(f"⚠️ Low Stock Alert ({len(low_stock_items)} items)")
        alert_dialog.geometry("1000x600")
        alert_dialog.transient(self.root)
        
        ttk.Label(alert_dialog, 
                 text=f"⚠️ {len(low_stock_items)} items are below minimum stock level",
                 font=('Arial', 12, 'bold'), foreground='red').pack(pady=10)
        
        # Create treeview
        tree_frame = ttk.Frame(alert_dialog)
        tree_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        columns = ('Part Number', 'Name', 'Current', 'Minimum', 'Deficit', 
                  'Unit', 'Location', 'Supplier')
        tree = ttk.Treeview(tree_frame, columns=columns, show='headings')
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=120)
        
        vsb = ttk.Scrollbar(tree_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        
        tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')
        
        # Populate tree
        for item in low_stock_items:
            part_no, name, current, minimum, unit, location, supplier = item
            deficit = minimum - current
            tree.insert('', 'end', values=(
                part_no, name, f"{current:.1f}", f"{minimum:.1f}", 
                f"{deficit:.1f}", unit, location or 'N/A', supplier or 'N/A'
            ))
        
        ttk.Button(alert_dialog, text="Close", 
                  command=alert_dialog.destroy).pack(pady=10)
    
    def refresh_mro_list(self):
        """Refresh MRO inventory list"""
        self.update_location_filter()
        self.filter_mro_list()
        self.update_mro_statistics()
    
    def filter_mro_list(self, *args):
        """Filter MRO list based on search and filters - OPTIMIZED"""
        search_term = self.mro_search_var.get().lower()
        system_filter = self.mro_system_filter.get()
        status_filter = self.mro_status_filter.get()
        location_filter = self.mro_location_filter.get()

        # Clear existing items
        for item in self.mro_tree.get_children():
            self.mro_tree.delete(item)

        # OPTIMIZED: Only select columns needed for display (not all 23 columns)
        query = '''SELECT part_number, name, model_number, equipment, engineering_system,
                          unit_of_measure, quantity_in_stock, unit_price, minimum_stock,
                          location, status
                   FROM mro_inventory WHERE 1=1'''
        params = []

        # OPTIMIZED: Use LOWER() which now has functional indexes
        if system_filter != 'All':
            query += ' AND LOWER(engineering_system) = LOWER(%s)'
            params.append(system_filter)

        if status_filter == 'Low Stock':
            # OPTIMIZED: This uses the partial index idx_mro_low_stock
            query += ' AND quantity_in_stock < minimum_stock'
        elif status_filter != 'All':
            # OPTIMIZED: Uses functional index on LOWER(status)
            query += ' AND LOWER(status) = LOWER(%s)'
            params.append(status_filter)

        # Location filter
        if location_filter != 'All':
            query += ' AND LOWER(location) = LOWER(%s)'
            params.append(location_filter)

        if search_term:
            # OPTIMIZED: LOWER() functions now use functional indexes
            query += ''' AND (
                LOWER(name) LIKE %s OR
                LOWER(part_number) LIKE %s OR
                LOWER(model_number) LIKE %s OR
                LOWER(equipment) LIKE %s OR
                LOWER(location) LIKE %s
            )'''
            search_param = f'%{search_term}%'
            params.extend([search_param] * 5)

        query += ' ORDER BY part_number'

        with db_pool.get_cursor(commit=False) as cursor:
            cursor.execute(query, params)

            # OPTIMIZED: Process results with reduced column set
            for idx, row in enumerate(cursor.fetchall()):
                # Access row data by column names (RealDictCursor returns dicts)
                part_number = row['part_number']

                # DEBUG: Log part numbers containing "319" to diagnose leading zero issue
                if '319' in str(part_number):
                    print(f"DEBUG: Loading part from DB: '{part_number}' (type: {type(part_number).__name__}, len: {len(part_number)})")

                name = row['name']
                model_number = row['model_number']
                equipment = row['equipment']
                engineering_system = row['engineering_system']
                unit_of_measure = row['unit_of_measure']
                qty = float(row['quantity_in_stock'])
                unit_price = float(row['unit_price'])
                min_stock = float(row['minimum_stock'])
                location = row['location']
                status = row['status']

                # Determine display status
                display_status = '⚠️ LOW' if qty < min_stock else status

                # Ensure part_number is explicitly a string to prevent TreeView auto-conversion
                part_number_str = str(part_number)

                self.mro_tree.insert('', 'end', values=(
                    part_number_str,  # Explicitly use string version
                    name,
                    model_number,
                    equipment,
                    engineering_system,
                    f"{qty:.1f}",
                    f"{min_stock:.1f}",
                    unit_of_measure,
                    f"${unit_price:.2f}",
                    location,
                    display_status
                ), tags=('low_stock',) if qty < min_stock else ())

                # Yield to event loop every 50 items to keep UI responsive
                if idx % 50 == 0:
                    self.root.update_idletasks()

        # Color low stock items
        self.mro_tree.tag_configure('low_stock', background='#ffcccc')

    def update_location_filter(self):
        """Update location filter dropdown with unique locations from database"""
        try:
            with db_pool.get_cursor(commit=False) as cursor:
                cursor.execute('''
                    SELECT DISTINCT location
                    FROM mro_inventory
                    WHERE location IS NOT NULL AND location != ''
                    ORDER BY location
                ''')

                locations = ['All'] + [row['location'] for row in cursor.fetchall()]

                # Update combobox values
                if hasattr(self, 'location_combo'):
                    current_value = self.mro_location_filter.get()
                    self.location_combo['values'] = locations

                    # Preserve current selection if it still exists
                    if current_value not in locations:
                        self.mro_location_filter.set('All')
        except Exception as e:
            print(f"Error updating location filter: {e}")

    def update_mro_statistics(self):
        """Update inventory statistics - OPTIMIZED to use single query"""
        with db_pool.get_cursor(commit=False) as cursor:
            # OPTIMIZED: Combined query - 3x faster than separate queries
            # Uses the covering index idx_mro_active_stock_value
            cursor.execute('''
                SELECT
                    COUNT(*) as total_parts,
                    COALESCE(SUM(quantity_in_stock * unit_price), 0) as total_value,
                    COUNT(*) FILTER (WHERE quantity_in_stock < minimum_stock) as low_stock_count
                FROM mro_inventory
                WHERE status = 'Active'
            ''')

            result = cursor.fetchone()
            total = result['total_parts']
            value = result['total_value']
            low_stock = result['low_stock_count']

            stats_text = (f"Total Parts: {total} | "
                         f"Total Value: ${value:,.2f} | "
                         f"Low Stock Items: {low_stock}")

            self.mro_stats_label.config(text=stats_text)
    
    def sort_mro_column(self, col):
        """Sort MRO treeview by column"""
        # Implement sorting logic here
        pass

    def migrate_photos_to_database(self):
        """Migrate existing photos from file paths to database binary storage"""
        try:
            cursor = self.conn.cursor()

            # Get all parts with photo paths but no binary data
            cursor.execute('''
                SELECT part_number, picture_1_path, picture_2_path
                FROM mro_inventory
                WHERE (picture_1_path IS NOT NULL AND picture_1_path != '' AND picture_1_data IS NULL)
                   OR (picture_2_path IS NOT NULL AND picture_2_path != '' AND picture_2_data IS NULL)
            ''')

            parts_to_migrate = cursor.fetchall()

            if not parts_to_migrate:
                messagebox.showinfo("Migration Complete", "No photos need migration. All photos are already in the database!")
                return

            migrated_count = 0
            skipped_count = 0
            error_count = 0

            for part_number, pic1_path, pic2_path in parts_to_migrate:
                pic1_data = None
                pic2_data = None

                # Try to read picture 1
                if pic1_path and os.path.exists(pic1_path):
                    try:
                        with open(pic1_path, 'rb') as f:
                            pic1_data = f.read()
                    except Exception as e:
                        error_count += 1
                        print(f"Error reading {pic1_path}: {e}")

                # Try to read picture 2
                if pic2_path and os.path.exists(pic2_path):
                    try:
                        with open(pic2_path, 'rb') as f:
                            pic2_data = f.read()
                    except Exception as e:
                        error_count += 1
                        print(f"Error reading {pic2_path}: {e}")

                # Update database with binary data
                if pic1_data or pic2_data:
                    try:
                        # Use TRIM() to handle leading/trailing spaces in part numbers
                        cursor.execute('''
                            UPDATE mro_inventory
                            SET picture_1_data = COALESCE(picture_1_data, %s),
                                picture_2_data = COALESCE(picture_2_data, %s)
                            WHERE TRIM(part_number) = %s
                        ''', (pic1_data, pic2_data, part_number))
                        migrated_count += 1
                    except Exception as e:
                        error_count += 1
                        print(f"Error updating database for {part_number}: {e}")
                else:
                    skipped_count += 1

            self.conn.commit()

            messagebox.showinfo(
                "Migration Complete",
                f"Photo migration completed!\n\n"
                f"Successfully migrated: {migrated_count} parts\n"
                f"Skipped (files not found): {skipped_count} parts\n"
                f"Errors: {error_count} parts"
            )

        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Migration Error", f"Failed to migrate photos:\n{str(e)}")


# ============================================================================
# INTEGRATION INSTRUCTIONS
# ============================================================================
"""
To integrate this MRO Stock Management into your existing CMMS application:

1. Add this import at the top of your AIT_CMMS_REV3.py file:
   from mro_stock_module import MROStockManager

2. In your AIT_CMMS class __init__ method, add:
   self.mro_manager = MROStockManager(self)

3. In your create_all_manager_tabs() or create_gui() method, add:
   self.mro_manager.create_mro_tab(self.notebook)

4. The MRO Stock system will automatically use your existing SQLite database.

Example integration code:

    def create_all_manager_tabs(self):
        # ... your existing tabs ...
        
        # Add MRO Stock tab
        self.mro_manager.create_mro_tab(self.notebook)
"""