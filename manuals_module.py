"""
Equipment Manuals and Prints Management Module
Provides functionality for uploading, searching, viewing, and printing equipment manuals
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
import os
import tempfile
import subprocess
import platform
from database_utils import DatabaseConnectionPool


class ManualsManager:
    """Manager for equipment manuals and technical prints"""

    def __init__(self, parent_app):
        """Initialize the Manuals Manager

        Args:
            parent_app: Reference to main application (AITCMMSSystem)
        """
        self.parent_app = parent_app
        self.root = parent_app.root
        self.conn = None
        self.db_pool = DatabaseConnectionPool()

        # Initialize database tables
        self.init_manuals_database()

    def init_manuals_database(self):
        """Create manuals table if it doesn't exist"""
        try:
            with self.db_pool.get_cursor() as cursor:
                # Create manuals table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS equipment_manuals (
                        id SERIAL PRIMARY KEY,
                        title TEXT NOT NULL,
                        description TEXT,
                        category TEXT,
                        sap_number TEXT,
                        bfm_number TEXT,
                        equipment_name TEXT,
                        file_name TEXT NOT NULL,
                        file_extension TEXT,
                        file_data BYTEA NOT NULL,
                        file_size INTEGER,
                        uploaded_by TEXT,
                        upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        tags TEXT,
                        status TEXT DEFAULT 'Active',
                        notes TEXT
                    )
                ''')

                # Create indexes for better search performance
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_manuals_sap_number
                    ON equipment_manuals(sap_number)
                ''')

                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_manuals_bfm_number
                    ON equipment_manuals(bfm_number)
                ''')

                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_manuals_equipment_name
                    ON equipment_manuals(equipment_name)
                ''')

                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_manuals_category
                    ON equipment_manuals(category)
                ''')

                print("Equipment manuals database initialized successfully")

        except Exception as e:
            print(f"Error initializing manuals database: {e}")
            messagebox.showerror("Database Error", f"Failed to initialize manuals database: {e}")

    def create_manuals_tab(self, notebook):
        """Create Equipment Manuals tab

        Args:
            notebook: Parent notebook widget
        """
        manuals_frame = ttk.Frame(notebook)
        notebook.add(manuals_frame, text='Manuals')

        # Top controls frame
        controls_frame = ttk.LabelFrame(manuals_frame, text="Manuals Controls", padding=10)
        controls_frame.pack(fill='x', padx=10, pady=5)

        # Buttons row 1
        btn_frame1 = ttk.Frame(controls_frame)
        btn_frame1.pack(fill='x', pady=5)

        ttk.Button(btn_frame1, text="📤 Upload Manual/Print",
                  command=self.upload_manual_dialog, width=22).pack(side='left', padx=5)
        ttk.Button(btn_frame1, text="👁️ View Selected",
                  command=self.view_selected_manual, width=22).pack(side='left', padx=5)
        ttk.Button(btn_frame1, text="🖨️ Print Selected",
                  command=self.print_selected_manual, width=22).pack(side='left', padx=5)
        ttk.Button(btn_frame1, text="📥 Download Selected",
                  command=self.download_selected_manual, width=22).pack(side='left', padx=5)

        # Buttons row 2
        btn_frame2 = ttk.Frame(controls_frame)
        btn_frame2.pack(fill='x', pady=5)

        ttk.Button(btn_frame2, text="✏️ Edit Details",
                  command=self.edit_manual_details, width=22).pack(side='left', padx=5)
        ttk.Button(btn_frame2, text="🗑️ Delete Selected",
                  command=self.delete_manual, width=22).pack(side='left', padx=5)
        ttk.Button(btn_frame2, text="🔄 Refresh",
                  command=self.refresh_manuals_list, width=22).pack(side='left', padx=5)

        # Search and filter frame
        search_frame = ttk.LabelFrame(manuals_frame, text="Search & Filter", padding=10)
        search_frame.pack(fill='x', padx=10, pady=5)

        # Row 1: Text search
        search_row1 = ttk.Frame(search_frame)
        search_row1.pack(fill='x', pady=5)

        ttk.Label(search_row1, text="Search:").pack(side='left', padx=5)
        self.manuals_search_var = tk.StringVar()
        self.manuals_search_var.trace('w', self.filter_manuals_list)
        ttk.Entry(search_row1, textvariable=self.manuals_search_var,
                 width=40).pack(side='left', padx=5)

        ttk.Label(search_row1, text="SAP Number:").pack(side='left', padx=(20, 5))
        self.sap_search_var = tk.StringVar()
        self.sap_search_var.trace('w', self.filter_manuals_list)
        ttk.Entry(search_row1, textvariable=self.sap_search_var,
                 width=20).pack(side='left', padx=5)

        ttk.Label(search_row1, text="BFM Number:").pack(side='left', padx=(20, 5))
        self.bfm_search_var = tk.StringVar()
        self.bfm_search_var.trace('w', self.filter_manuals_list)
        ttk.Entry(search_row1, textvariable=self.bfm_search_var,
                 width=20).pack(side='left', padx=5)

        # Row 2: Category filter
        search_row2 = ttk.Frame(search_frame)
        search_row2.pack(fill='x', pady=5)

        ttk.Label(search_row2, text="Category:").pack(side='left', padx=5)
        self.category_filter = tk.StringVar(value='All')
        category_combo = ttk.Combobox(search_row2, textvariable=self.category_filter,
                                      values=['All', 'Equipment Manual', 'Service Manual', 'Parts Catalog',
                                              'Wiring Diagram', 'Schematic', 'Installation Guide',
                                              'Safety Procedure', 'Technical Print', 'Other'],
                                      width=20, state='readonly')
        category_combo.pack(side='left', padx=5)
        category_combo.bind('<<ComboboxSelected>>', self.filter_manuals_list)

        ttk.Label(search_row2, text="Status:").pack(side='left', padx=(20, 5))
        self.status_filter = tk.StringVar(value='Active')
        status_combo = ttk.Combobox(search_row2, textvariable=self.status_filter,
                                    values=['All', 'Active', 'Archived'],
                                    width=15, state='readonly')
        status_combo.pack(side='left', padx=5)
        status_combo.bind('<<ComboboxSelected>>', self.filter_manuals_list)

        # Manuals list
        list_frame = ttk.LabelFrame(manuals_frame, text="Equipment Manuals & Prints", padding=10)
        list_frame.pack(fill='both', expand=True, padx=10, pady=5)

        # Create treeview
        columns = ('ID', 'Title', 'Description', 'SAP Number', 'BFM Number',
                  'Equipment', 'Category', 'File Name', 'Size (KB)', 'Uploaded By', 'Upload Date')
        self.manuals_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=20)

        # Configure columns
        column_widths = {
            'ID': 50,
            'Title': 200,
            'Description': 250,
            'SAP Number': 100,
            'BFM Number': 100,
            'Equipment': 150,
            'Category': 120,
            'File Name': 150,
            'Size (KB)': 80,
            'Uploaded By': 120,
            'Upload Date': 120
        }

        for col in columns:
            self.manuals_tree.heading(col, text=col, command=lambda c=col: self.sort_manuals_column(c))
            self.manuals_tree.column(col, width=column_widths[col], anchor='center' if col in ['ID', 'Size (KB)'] else 'w')

        # Scrollbars
        vsb = ttk.Scrollbar(list_frame, orient='vertical', command=self.manuals_tree.yview)
        hsb = ttk.Scrollbar(list_frame, orient='horizontal', command=self.manuals_tree.xview)
        self.manuals_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        # Pack elements
        self.manuals_tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')

        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        # Double-click to view
        self.manuals_tree.bind('<Double-1>', lambda e: self.view_selected_manual())

        # Statistics frame
        stats_frame = ttk.LabelFrame(manuals_frame, text="Statistics", padding=10)
        stats_frame.pack(fill='x', padx=10, pady=5)

        self.manuals_stats_label = ttk.Label(stats_frame, text="Loading...",
                                             font=('Arial', 10))
        self.manuals_stats_label.pack()

        # Load initial data
        self.refresh_manuals_list()

        return manuals_frame

    def upload_manual_dialog(self):
        """Dialog to upload a new manual or print"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Upload Equipment Manual/Print")
        dialog.geometry("700x650")
        dialog.transient(self.root)
        dialog.grab_set()

        # Main frame with scrollbar
        main_frame = ttk.Frame(dialog, padding=20)
        main_frame.pack(fill='both', expand=True)

        row = 0

        # File selection
        ttk.Label(main_frame, text="File Selection:", font=('Arial', 10, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', pady=(0, 10))
        row += 1

        ttk.Label(main_frame, text="Select File:*").grid(row=row, column=0, sticky='w', pady=5)
        file_frame = ttk.Frame(main_frame)
        file_frame.grid(row=row, column=1, sticky='ew', pady=5)

        file_path_var = tk.StringVar()
        file_entry = ttk.Entry(file_frame, textvariable=file_path_var, width=50, state='readonly')
        file_entry.pack(side='left', padx=(0, 5), fill='x', expand=True)

        def browse_file():
            file_path = filedialog.askopenfilename(
                title="Select Manual or Print",
                filetypes=[
                    ("PDF files", "*.pdf"),
                    ("Image files", "*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff"),
                    ("Document files", "*.doc *.docx"),
                    ("All files", "*.*")
                ]
            )
            if file_path:
                file_path_var.set(file_path)
                # Auto-fill file name if empty
                if not title_entry.get():
                    title_entry.delete(0, tk.END)
                    title_entry.insert(0, os.path.splitext(os.path.basename(file_path))[0])

        ttk.Button(file_frame, text="Browse", command=browse_file, width=12).pack(side='left')
        row += 1

        ttk.Separator(main_frame, orient='horizontal').grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=15)
        row += 1

        # Document details
        ttk.Label(main_frame, text="Document Details:", font=('Arial', 10, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', pady=(0, 10))
        row += 1

        ttk.Label(main_frame, text="Title:*").grid(row=row, column=0, sticky='w', pady=5)
        title_entry = ttk.Entry(main_frame, width=50)
        title_entry.grid(row=row, column=1, sticky='ew', pady=5)
        row += 1

        ttk.Label(main_frame, text="Description:").grid(row=row, column=0, sticky='nw', pady=5)
        description_text = tk.Text(main_frame, width=50, height=4, wrap='word')
        description_text.grid(row=row, column=1, sticky='ew', pady=5)
        row += 1

        ttk.Label(main_frame, text="Category:*").grid(row=row, column=0, sticky='w', pady=5)
        category_var = tk.StringVar(value='Equipment Manual')
        category_combo = ttk.Combobox(main_frame, textvariable=category_var,
                                      values=['Equipment Manual', 'Service Manual', 'Parts Catalog',
                                              'Wiring Diagram', 'Schematic', 'Installation Guide',
                                              'Safety Procedure', 'Technical Print', 'Other'],
                                      width=47, state='readonly')
        category_combo.grid(row=row, column=1, sticky='ew', pady=5)
        row += 1

        ttk.Separator(main_frame, orient='horizontal').grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=15)
        row += 1

        # Equipment identification
        ttk.Label(main_frame, text="Equipment Identification:", font=('Arial', 10, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', pady=(0, 10))
        row += 1

        ttk.Label(main_frame, text="SAP Number:").grid(row=row, column=0, sticky='w', pady=5)
        sap_entry = ttk.Entry(main_frame, width=50)
        sap_entry.grid(row=row, column=1, sticky='ew', pady=5)
        row += 1

        ttk.Label(main_frame, text="BFM Number:").grid(row=row, column=0, sticky='w', pady=5)
        bfm_entry = ttk.Entry(main_frame, width=50)
        bfm_entry.grid(row=row, column=1, sticky='ew', pady=5)
        row += 1

        ttk.Label(main_frame, text="Equipment Name:").grid(row=row, column=0, sticky='w', pady=5)
        equipment_entry = ttk.Entry(main_frame, width=50)
        equipment_entry.grid(row=row, column=1, sticky='ew', pady=5)
        row += 1

        ttk.Separator(main_frame, orient='horizontal').grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=15)
        row += 1

        # Additional info
        ttk.Label(main_frame, text="Additional Information:", font=('Arial', 10, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', pady=(0, 10))
        row += 1

        ttk.Label(main_frame, text="Tags:").grid(row=row, column=0, sticky='w', pady=5)
        tags_entry = ttk.Entry(main_frame, width=50)
        tags_entry.grid(row=row, column=1, sticky='ew', pady=5)
        ttk.Label(main_frame, text="(comma-separated)", font=('Arial', 8, 'italic')).grid(
            row=row+1, column=1, sticky='w', pady=(0, 5))
        row += 2

        ttk.Label(main_frame, text="Notes:").grid(row=row, column=0, sticky='nw', pady=5)
        notes_text = tk.Text(main_frame, width=50, height=3, wrap='word')
        notes_text.grid(row=row, column=1, sticky='ew', pady=5)
        row += 1

        # Configure grid weights
        main_frame.columnconfigure(1, weight=1)

        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill='x', padx=20, pady=(10, 20))

        def save_manual():
            # Validate required fields
            if not file_path_var.get():
                messagebox.showerror("Error", "Please select a file to upload")
                return

            if not title_entry.get().strip():
                messagebox.showerror("Error", "Please enter a title")
                return

            if not category_var.get():
                messagebox.showerror("Error", "Please select a category")
                return

            try:
                # Read file data
                file_path = file_path_var.get()
                if not os.path.exists(file_path):
                    messagebox.showerror("Error", "Selected file does not exist")
                    return

                with open(file_path, 'rb') as f:
                    file_data = f.read()

                file_size = len(file_data)
                file_name = os.path.basename(file_path)
                file_extension = os.path.splitext(file_name)[1].lower()

                # Get current user
                uploaded_by = getattr(self.parent_app, 'current_user', 'Unknown')

                # Insert into database
                with self.db_pool.get_cursor() as cursor:
                    cursor.execute('''
                        INSERT INTO equipment_manuals
                        (title, description, category, sap_number, bfm_number,
                         equipment_name, file_name, file_extension, file_data,
                         file_size, uploaded_by, tags, notes)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        title_entry.get().strip(),
                        description_text.get('1.0', 'end-1c').strip(),
                        category_var.get(),
                        sap_entry.get().strip() or None,
                        bfm_entry.get().strip() or None,
                        equipment_entry.get().strip() or None,
                        file_name,
                        file_extension,
                        file_data,
                        file_size,
                        uploaded_by,
                        tags_entry.get().strip() or None,
                        notes_text.get('1.0', 'end-1c').strip() or None
                    ))

                messagebox.showinfo("Success", f"Manual '{title_entry.get()}' uploaded successfully!")
                dialog.destroy()
                self.refresh_manuals_list()

            except Exception as e:
                messagebox.showerror("Error", f"Failed to upload manual: {e}")
                print(f"Upload error: {e}")

        ttk.Button(button_frame, text="Upload", command=save_manual, width=15).pack(side='right', padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy, width=15).pack(side='right')

    def refresh_manuals_list(self):
        """Refresh the manuals list"""
        # Clear existing items
        for item in self.manuals_tree.get_children():
            self.manuals_tree.delete(item)

        try:
            with self.db_pool.get_cursor() as cursor:
                cursor.execute('''
                    SELECT id, title, description, sap_number, bfm_number,
                           equipment_name, category, file_name, file_size,
                           uploaded_by, upload_date, status
                    FROM equipment_manuals
                    ORDER BY upload_date DESC
                ''')

                rows = cursor.fetchall()

                for row in rows:
                    # Access columns by name (RealDictCursor returns dict-like rows)
                    manual_id = row['id']
                    title = row['title']
                    description = row['description']
                    sap_num = row['sap_number']
                    bfm_num = row['bfm_number']
                    equipment = row['equipment_name']
                    category = row['category']
                    file_name = row['file_name']
                    file_size = row['file_size']
                    uploaded_by = row['uploaded_by']
                    upload_date = row['upload_date']
                    status = row['status']

                    # Format file size
                    size_kb = f"{int(file_size) / 1024:.1f}" if file_size else "0"

                    # Format date
                    date_str = upload_date.strftime('%Y-%m-%d %H:%M') if upload_date else ''

                    # Truncate long descriptions
                    desc_display = (description[:50] + '...') if description and len(description) > 50 else (description or '')

                    self.manuals_tree.insert('', 'end', values=(
                        manual_id,
                        title,
                        desc_display,
                        sap_num or '',
                        bfm_num or '',
                        equipment or '',
                        category,
                        file_name,
                        size_kb,
                        uploaded_by or '',
                        date_str
                    ))

                # Update statistics
                total_manuals = len(rows)
                total_size = sum(int(row['file_size']) for row in rows if row['file_size']) / (1024 * 1024)  # Convert to MB

                self.manuals_stats_label.config(
                    text=f"Total Manuals: {total_manuals} | Total Size: {total_size:.2f} MB"
                )

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load manuals: {e}")
            print(f"Refresh error: {e}")

    def filter_manuals_list(self, *args):
        """Filter manuals based on search criteria"""
        search_text = self.manuals_search_var.get().lower()
        sap_text = self.sap_search_var.get().lower()
        bfm_text = self.bfm_search_var.get().lower()
        category = self.category_filter.get()
        status = self.status_filter.get()

        # Clear existing items
        for item in self.manuals_tree.get_children():
            self.manuals_tree.delete(item)

        try:
            with self.db_pool.get_cursor() as cursor:
                # Build query with filters
                query = '''
                    SELECT id, title, description, sap_number, bfm_number,
                           equipment_name, category, file_name, file_size,
                           uploaded_by, upload_date, status
                    FROM equipment_manuals
                    WHERE 1=1
                '''
                params = []

                if search_text:
                    query += ''' AND (
                        LOWER(title) LIKE %s OR
                        LOWER(description) LIKE %s OR
                        LOWER(equipment_name) LIKE %s OR
                        LOWER(file_name) LIKE %s OR
                        LOWER(tags) LIKE %s
                    )'''
                    search_param = f'%{search_text}%'
                    params.extend([search_param] * 5)

                if sap_text:
                    query += ' AND LOWER(sap_number) LIKE %s'
                    params.append(f'%{sap_text}%')

                if bfm_text:
                    query += ' AND LOWER(bfm_number) LIKE %s'
                    params.append(f'%{bfm_text}%')

                if category != 'All':
                    query += ' AND category = %s'
                    params.append(category)

                if status != 'All':
                    query += ' AND status = %s'
                    params.append(status)

                query += ' ORDER BY upload_date DESC'

                cursor.execute(query, params)
                rows = cursor.fetchall()

                for row in rows:
                    # Access columns by name (RealDictCursor returns dict-like rows)
                    manual_id = row['id']
                    title = row['title']
                    description = row['description']
                    sap_num = row['sap_number']
                    bfm_num = row['bfm_number']
                    equipment = row['equipment_name']
                    category = row['category']
                    file_name = row['file_name']
                    file_size = row['file_size']
                    uploaded_by = row['uploaded_by']
                    upload_date = row['upload_date']
                    status = row['status']

                    size_kb = f"{int(file_size) / 1024:.1f}" if file_size else "0"
                    date_str = upload_date.strftime('%Y-%m-%d %H:%M') if upload_date else ''
                    desc_display = (description[:50] + '...') if description and len(description) > 50 else (description or '')

                    self.manuals_tree.insert('', 'end', values=(
                        manual_id,
                        title,
                        desc_display,
                        sap_num or '',
                        bfm_num or '',
                        equipment or '',
                        category,
                        file_name,
                        size_kb,
                        uploaded_by or '',
                        date_str
                    ))

                # Update statistics
                total_manuals = len(rows)
                total_size = sum(int(row['file_size']) for row in rows if row['file_size']) / (1024 * 1024)
                self.manuals_stats_label.config(
                    text=f"Filtered Results: {total_manuals} | Total Size: {total_size:.2f} MB"
                )

        except Exception as e:
            messagebox.showerror("Error", f"Failed to filter manuals: {e}")
            print(f"Filter error: {e}")

    def view_selected_manual(self):
        """View the selected manual"""
        selected = self.manuals_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a manual to view")
            return

        try:
            manual_id = self.manuals_tree.item(selected[0])['values'][0]

            with self.db_pool.get_cursor() as cursor:
                cursor.execute('''
                    SELECT file_name, file_extension, file_data
                    FROM equipment_manuals
                    WHERE id = %s
                ''', (manual_id,))

                row = cursor.fetchone()
                if not row:
                    messagebox.showerror("Error", "Manual not found in database")
                    return

                file_name = row['file_name']
                file_extension = row['file_extension']
                file_data = row['file_data']

                # Create temporary file
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                    temp_file.write(file_data)
                    temp_path = temp_file.name

                # Open with default application
                self._open_file(temp_path)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to view manual: {e}")
            print(f"View error: {e}")

    def print_selected_manual(self):
        """Print the selected manual"""
        selected = self.manuals_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a manual to print")
            return

        try:
            manual_id = self.manuals_tree.item(selected[0])['values'][0]

            with self.db_pool.get_cursor() as cursor:
                cursor.execute('''
                    SELECT file_name, file_extension, file_data
                    FROM equipment_manuals
                    WHERE id = %s
                ''', (manual_id,))

                row = cursor.fetchone()
                if not row:
                    messagebox.showerror("Error", "Manual not found in database")
                    return

                file_name = row['file_name']
                file_extension = row['file_extension']
                file_data = row['file_data']

                # Create temporary file
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                    temp_file.write(file_data)
                    temp_path = temp_file.name

                # Open with default application (user can print from there)
                self._open_file(temp_path)
                messagebox.showinfo("Print",
                    "The manual has been opened. Please use the application's print function (usually Ctrl+P or File > Print)")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to open manual for printing: {e}")
            print(f"Print error: {e}")

    def download_selected_manual(self):
        """Download the selected manual to a user-specified location"""
        selected = self.manuals_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a manual to download")
            return

        try:
            manual_id = self.manuals_tree.item(selected[0])['values'][0]

            with self.db_pool.get_cursor() as cursor:
                cursor.execute('''
                    SELECT file_name, file_extension, file_data, title
                    FROM equipment_manuals
                    WHERE id = %s
                ''', (manual_id,))

                row = cursor.fetchone()
                if not row:
                    messagebox.showerror("Error", "Manual not found in database")
                    return

                file_name = row['file_name']
                file_extension = row['file_extension']
                file_data = row['file_data']
                title = row['title']

                # Ask user where to save
                save_path = filedialog.asksaveasfilename(
                    defaultextension=file_extension,
                    initialfile=file_name,
                    title="Save Manual As",
                    filetypes=[("All files", "*.*")]
                )

                if save_path:
                    with open(save_path, 'wb') as f:
                        f.write(file_data)
                    messagebox.showinfo("Success", f"Manual saved to:\n{save_path}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to download manual: {e}")
            print(f"Download error: {e}")

    def edit_manual_details(self):
        """Edit details of the selected manual (not the file itself)"""
        selected = self.manuals_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a manual to edit")
            return

        try:
            manual_id = self.manuals_tree.item(selected[0])['values'][0]

            # Fetch current data
            with self.db_pool.get_cursor() as cursor:
                cursor.execute('''
                    SELECT title, description, category, sap_number, bfm_number,
                           equipment_name, tags, notes, status
                    FROM equipment_manuals
                    WHERE id = %s
                ''', (manual_id,))

                row = cursor.fetchone()
                if not row:
                    messagebox.showerror("Error", "Manual not found")
                    return

                title = row['title']
                description = row['description']
                category = row['category']
                sap_num = row['sap_number']
                bfm_num = row['bfm_number']
                equipment = row['equipment_name']
                tags = row['tags']
                notes = row['notes']
                status = row['status']

            # Create edit dialog
            dialog = tk.Toplevel(self.root)
            dialog.title("Edit Manual Details")
            dialog.geometry("600x550")
            dialog.transient(self.root)
            dialog.grab_set()

            main_frame = ttk.Frame(dialog, padding=20)
            main_frame.pack(fill='both', expand=True)

            row = 0

            ttk.Label(main_frame, text="Title:*").grid(row=row, column=0, sticky='w', pady=5)
            title_entry = ttk.Entry(main_frame, width=50)
            title_entry.insert(0, title)
            title_entry.grid(row=row, column=1, sticky='ew', pady=5)
            row += 1

            ttk.Label(main_frame, text="Description:").grid(row=row, column=0, sticky='nw', pady=5)
            description_text = tk.Text(main_frame, width=50, height=4, wrap='word')
            if description:
                description_text.insert('1.0', description)
            description_text.grid(row=row, column=1, sticky='ew', pady=5)
            row += 1

            ttk.Label(main_frame, text="Category:*").grid(row=row, column=0, sticky='w', pady=5)
            category_var = tk.StringVar(value=category)
            category_combo = ttk.Combobox(main_frame, textvariable=category_var,
                                          values=['Equipment Manual', 'Service Manual', 'Parts Catalog',
                                                  'Wiring Diagram', 'Schematic', 'Installation Guide',
                                                  'Safety Procedure', 'Technical Print', 'Other'],
                                          width=47, state='readonly')
            category_combo.grid(row=row, column=1, sticky='ew', pady=5)
            row += 1

            ttk.Label(main_frame, text="SAP Number:").grid(row=row, column=0, sticky='w', pady=5)
            sap_entry = ttk.Entry(main_frame, width=50)
            if sap_num:
                sap_entry.insert(0, sap_num)
            sap_entry.grid(row=row, column=1, sticky='ew', pady=5)
            row += 1

            ttk.Label(main_frame, text="BFM Number:").grid(row=row, column=0, sticky='w', pady=5)
            bfm_entry = ttk.Entry(main_frame, width=50)
            if bfm_num:
                bfm_entry.insert(0, bfm_num)
            bfm_entry.grid(row=row, column=1, sticky='ew', pady=5)
            row += 1

            ttk.Label(main_frame, text="Equipment Name:").grid(row=row, column=0, sticky='w', pady=5)
            equipment_entry = ttk.Entry(main_frame, width=50)
            if equipment:
                equipment_entry.insert(0, equipment)
            equipment_entry.grid(row=row, column=1, sticky='ew', pady=5)
            row += 1

            ttk.Label(main_frame, text="Tags:").grid(row=row, column=0, sticky='w', pady=5)
            tags_entry = ttk.Entry(main_frame, width=50)
            if tags:
                tags_entry.insert(0, tags)
            tags_entry.grid(row=row, column=1, sticky='ew', pady=5)
            row += 1

            ttk.Label(main_frame, text="Notes:").grid(row=row, column=0, sticky='nw', pady=5)
            notes_text = tk.Text(main_frame, width=50, height=3, wrap='word')
            if notes:
                notes_text.insert('1.0', notes)
            notes_text.grid(row=row, column=1, sticky='ew', pady=5)
            row += 1

            ttk.Label(main_frame, text="Status:").grid(row=row, column=0, sticky='w', pady=5)
            status_var = tk.StringVar(value=status)
            status_combo = ttk.Combobox(main_frame, textvariable=status_var,
                                        values=['Active', 'Archived'],
                                        width=47, state='readonly')
            status_combo.grid(row=row, column=1, sticky='ew', pady=5)
            row += 1

            main_frame.columnconfigure(1, weight=1)

            # Buttons
            button_frame = ttk.Frame(dialog)
            button_frame.pack(fill='x', padx=20, pady=(10, 20))

            def save_changes():
                if not title_entry.get().strip():
                    messagebox.showerror("Error", "Title is required")
                    return

                try:
                    with self.db_pool.get_cursor() as cursor:
                        cursor.execute('''
                            UPDATE equipment_manuals
                            SET title = %s, description = %s, category = %s,
                                sap_number = %s, bfm_number = %s, equipment_name = %s,
                                tags = %s, notes = %s, status = %s,
                                last_updated = CURRENT_TIMESTAMP
                            WHERE id = %s
                        ''', (
                            title_entry.get().strip(),
                            description_text.get('1.0', 'end-1c').strip() or None,
                            category_var.get(),
                            sap_entry.get().strip() or None,
                            bfm_entry.get().strip() or None,
                            equipment_entry.get().strip() or None,
                            tags_entry.get().strip() or None,
                            notes_text.get('1.0', 'end-1c').strip() or None,
                            status_var.get(),
                            manual_id
                        ))

                    messagebox.showinfo("Success", "Manual details updated successfully!")
                    dialog.destroy()
                    self.refresh_manuals_list()

                except Exception as e:
                    messagebox.showerror("Error", f"Failed to update manual: {e}")
                    print(f"Update error: {e}")

            ttk.Button(button_frame, text="Save Changes", command=save_changes, width=15).pack(side='right', padx=5)
            ttk.Button(button_frame, text="Cancel", command=dialog.destroy, width=15).pack(side='right')

        except Exception as e:
            messagebox.showerror("Error", f"Failed to open edit dialog: {e}")
            print(f"Edit error: {e}")

    def delete_manual(self):
        """Delete the selected manual"""
        selected = self.manuals_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a manual to delete")
            return

        manual_id = self.manuals_tree.item(selected[0])['values'][0]
        title = self.manuals_tree.item(selected[0])['values'][1]

        confirm = messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to delete the manual:\n\n'{title}'?\n\nThis action cannot be undone."
        )

        if not confirm:
            return

        try:
            with self.db_pool.get_cursor() as cursor:
                cursor.execute('DELETE FROM equipment_manuals WHERE id = %s', (manual_id,))

            messagebox.showinfo("Success", "Manual deleted successfully")
            self.refresh_manuals_list()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete manual: {e}")
            print(f"Delete error: {e}")

    def sort_manuals_column(self, col):
        """Sort manuals tree by column"""
        # This is a simplified version - you can enhance it with proper sorting logic
        self.refresh_manuals_list()

    def _open_file(self, file_path):
        """Open file with default system application"""
        try:
            system = platform.system()
            if system == 'Windows':
                os.startfile(file_path)
            elif system == 'Darwin':  # macOS
                subprocess.run(['open', file_path])
            else:  # Linux
                subprocess.run(['xdg-open', file_path])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open file: {e}")
            print(f"Open file error: {e}")
