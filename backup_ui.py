"""
Database Backup UI Module
Provides Tkinter interface for managers to backup and manage NEON database backups
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import threading
from datetime import datetime
from pathlib import Path
import shutil
from backup_manager import BackupManager


class BackupUI:
    """Tkinter UI for database backup management"""

    def __init__(self, root, db_config, user_name="Unknown"):
        """
        Initialize Backup UI

        Args:
            root: Parent Tkinter window
            db_config: Database configuration dictionary
            user_name: Current logged-in user name
        """
        self.root = root
        self.db_config = db_config
        self.user_name = user_name
        # Let BackupManager auto-detect a safe backup directory
        self.backup_manager = BackupManager(db_config)
        self.backup_window = None
        self.backup_thread = None
        self.backup_in_progress = False

    def open_backup_window(self):
        """Open the database backup management window"""
        if self.backup_window is not None and self.backup_window.winfo_exists():
            self.backup_window.lift()
            self.backup_window.focus()
            return

        self.backup_window = tk.Toplevel(self.root)
        self.backup_window.title("Database Backup Manager")
        self.backup_window.geometry("1000x700")
        self.backup_window.resizable(True, True)

        # Configure style
        style = ttk.Style()
        style.theme_use('clam')

        # Create main container
        main_frame = ttk.Frame(self.backup_window)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # ===== TITLE SECTION =====
        title_frame = ttk.Frame(main_frame)
        title_frame.pack(fill='x', pady=(0, 10))

        ttk.Label(title_frame, text="🗄️ Database Backup Manager",
                 font=('Arial', 14, 'bold')).pack(side='left')

        ttk.Label(title_frame, text=f"User: {self.user_name}",
                 font=('Arial', 10)).pack(side='right', padx=(5, 0))

        # ===== BACKUP LOCATION INFO =====
        location_frame = ttk.Frame(main_frame)
        location_frame.pack(fill='x', pady=(0, 10))

        ttk.Label(location_frame, text="📁 Backup Location:",
                 font=('Arial', 10, 'bold')).pack(side='left', padx=(0, 5))

        backup_path_text = str(self.backup_manager.backup_dir)
        ttk.Label(location_frame, text=backup_path_text,
                 font=('Arial', 9), foreground='#0066cc').pack(side='left')

        # Show a warning if using fallback location
        if self.backup_manager.using_fallback_location:
            ttk.Label(location_frame, text="⚠️ Using alternate location due to permissions",
                     font=('Arial', 9), foreground='orange').pack(side='left', padx=(10, 0))

        # ===== ACTION BUTTONS SECTION =====
        action_frame = ttk.LabelFrame(main_frame, text="Backup Actions", padding=10)
        action_frame.pack(fill='x', pady=(0, 10))

        button_subframe = ttk.Frame(action_frame)
        button_subframe.pack(fill='x')

        # Create Backup Button
        self.create_backup_btn = ttk.Button(
            button_subframe,
            text="📥 Create Backup Now",
            command=self.create_backup_handler,
            width=25
        )
        self.create_backup_btn.pack(side='left', padx=5)

        # Refresh Button
        ttk.Button(
            button_subframe,
            text="🔄 Refresh List",
            command=self.refresh_backup_list,
            width=20
        ).pack(side='left', padx=5)

        # Cleanup Old Backups Button
        ttk.Button(
            button_subframe,
            text="🗑️ Cleanup Old Backups",
            command=self.cleanup_backups_handler,
            width=25
        ).pack(side='left', padx=5)

        # Second row of buttons for restore
        button_subframe2 = ttk.Frame(action_frame)
        button_subframe2.pack(fill='x', pady=(10, 0))

        # Restore Backup Button
        self.restore_backup_btn = ttk.Button(
            button_subframe2,
            text="📤 Restore/Upload Backup",
            command=self.restore_backup_handler,
            width=25
        )
        self.restore_backup_btn.pack(side='left', padx=5)

        ttk.Label(
            button_subframe2,
            text="⚠️ Restore will overwrite the current database!",
            foreground='red',
            font=('Arial', 9, 'bold')
        ).pack(side='left', padx=10)

        # ===== BACKUP LIST SECTION =====
        list_frame = ttk.LabelFrame(main_frame, text="Available Backups", padding=10)
        list_frame.pack(fill='both', expand=True, pady=(0, 10))

        # Create tree columns
        columns = ('Filename', 'Size (MB)', 'Created', 'Age (Days)')
        self.backup_tree = ttk.Treeview(list_frame, columns=columns, height=12, show='headings')

        # Define column headings and widths
        self.backup_tree.column('#0', width=0, stretch=tk.NO)
        self.backup_tree.column('Filename', anchor=tk.W, width=350)
        self.backup_tree.column('Size (MB)', anchor=tk.CENTER, width=120)
        self.backup_tree.column('Created', anchor=tk.CENTER, width=180)
        self.backup_tree.column('Age (Days)', anchor=tk.CENTER, width=100)

        self.backup_tree.heading('#0', text='', anchor=tk.W)
        self.backup_tree.heading('Filename', text='Filename', anchor=tk.W)
        self.backup_tree.heading('Size (MB)', text='Size (MB)', anchor=tk.CENTER)
        self.backup_tree.heading('Created', text='Created', anchor=tk.CENTER)
        self.backup_tree.heading('Age (Days)', text='Age (Days)', anchor=tk.CENTER)

        # Add scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=self.backup_tree.yview)
        self.backup_tree.configure(yscroll=scrollbar.set)

        # Pack tree and scrollbar
        self.backup_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # Bind right-click context menu
        self.backup_tree.bind("<Button-3>", self.show_backup_context_menu)

        # ===== BACKUP LIST ACTIONS =====
        actions_frame = ttk.Frame(action_frame)
        actions_frame.pack(fill='x', pady=(10, 0))

        ttk.Button(
            actions_frame,
            text="📂 Export Selected Backup",
            command=self.export_backup_handler,
            width=25
        ).pack(side='left', padx=5)

        ttk.Button(
            actions_frame,
            text="📋 View Backup Details",
            command=self.view_backup_details,
            width=25
        ).pack(side='left', padx=5)

        ttk.Button(
            actions_frame,
            text="🗑️ Delete Selected",
            command=self.delete_backup_handler,
            width=20
        ).pack(side='left', padx=5)

        # ===== STATUS SECTION =====
        status_frame = ttk.LabelFrame(main_frame, text="Status & Logs", padding=10)
        status_frame.pack(fill='both', expand=True, pady=(0, 10))

        # Create text widget for status
        self.status_text = scrolledtext.ScrolledText(
            status_frame,
            height=8,
            width=100,
            font=('Courier', 9),
            state='disabled'
        )
        self.status_text.pack(fill='both', expand=True)

        # ===== CONFIGURATION SECTION =====
        config_frame = ttk.LabelFrame(main_frame, text="Backup Configuration", padding=10)
        config_frame.pack(fill='x')

        config_subframe = ttk.Frame(config_frame)
        config_subframe.pack(fill='x')

        ttk.Label(config_subframe, text="Schedule:").pack(side='left', padx=(0, 5))
        self.schedule_var = tk.StringVar(value=self.backup_manager.config.get('schedule', 'daily'))
        ttk.Combobox(config_subframe, textvariable=self.schedule_var,
                    values=['daily', 'weekly', 'monthly'], state='readonly', width=15).pack(side='left', padx=5)

        ttk.Label(config_subframe, text="Retention (Days):").pack(side='left', padx=(20, 5))
        self.retention_var = tk.StringVar(value=str(self.backup_manager.config.get('retention_days', 30)))
        ttk.Spinbox(config_subframe, from_=1, to=365, textvariable=self.retention_var, width=10).pack(side='left', padx=5)

        ttk.Button(config_subframe, text="Save Config",
                  command=self.save_config).pack(side='left', padx=(20, 5))

        # Initial load
        self.refresh_backup_list()
        self.log_status(f"Backup Manager initialized for user: {self.user_name}")
        self.log_status(f"📁 Backup directory: {self.backup_manager.backup_dir}")

    def log_status(self, message):
        """Log a message to the status text widget"""
        if self.status_text:
            self.status_text.config(state='normal')
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.status_text.insert('end', f"[{timestamp}] {message}\n")
            self.status_text.see('end')
            self.status_text.config(state='disabled')
            self.backup_window.update_idletasks()

    def create_backup_handler(self):
        """Handle backup creation in a separate thread"""
        if self.backup_in_progress:
            messagebox.showwarning("Backup In Progress",
                                  "A backup operation is already in progress. Please wait.")
            return

        # Disable button
        self.create_backup_btn.config(state='disabled')
        self.backup_in_progress = True

        # Run backup in separate thread
        self.backup_thread = threading.Thread(target=self._create_backup_thread, daemon=True)
        self.backup_thread.start()

    def _create_backup_thread(self):
        """Thread function to create backup"""
        try:
            self.log_status("Starting database backup...")
            self.log_status("⏳ This may take several minutes depending on database size...")

            success, backup_path, message = self.backup_manager.create_backup()

            if success:
                self.log_status(f"✅ Backup successful!")
                self.log_status(f"📁 Location: {backup_path}")
                self.log_status(f"💾 {message}")

                # Show success dialog
                self.root.after(0, lambda: messagebox.showinfo(
                    "Backup Successful",
                    f"Database backup created successfully!\n\n"
                    f"File: {Path(backup_path).name}\n"
                    f"{message}\n\n"
                    f"You can now export this file to SharePoint."
                ))
            else:
                self.log_status(f"❌ Backup failed: {message}")
                self.root.after(0, lambda: messagebox.showerror(
                    "Backup Failed",
                    f"Failed to create backup:\n\n{message}"
                ))

            # Refresh the list
            self.root.after(0, self.refresh_backup_list)

        except Exception as e:
            self.log_status(f"❌ Error during backup: {str(e)}")
            self.root.after(0, lambda: messagebox.showerror(
                "Backup Error",
                f"Error creating backup:\n\n{str(e)}"
            ))
        finally:
            self.backup_in_progress = False
            self.root.after(0, lambda: self.create_backup_btn.config(state='normal'))

    def restore_backup_handler(self):
        """Handle backup restore - upload and restore a backup file"""
        if self.backup_in_progress:
            messagebox.showwarning("Operation In Progress",
                                  "A backup operation is already in progress. Please wait.")
            return

        # Show warning dialog first
        warning_result = messagebox.askokcancel(
            "⚠️ WARNING: Database Restore",
            "CRITICAL WARNING:\n\n"
            "Restoring a backup will COMPLETELY OVERWRITE the current database!\n\n"
            "All current data will be REPLACED with the backup data.\n\n"
            "This operation CANNOT BE UNDONE.\n\n"
            "It is HIGHLY RECOMMENDED to create a backup of the current database\n"
            "before proceeding with restore.\n\n"
            "Do you want to continue?",
            icon='warning'
        )

        if not warning_result:
            self.log_status("Restore operation cancelled by user.")
            return

        # Ask user to select backup file
        backup_file = filedialog.askopenfilename(
            title="Select Backup File to Restore",
            filetypes=[
                ("CMMS Backup Files", "*.cmmsbackup"),
                ("All Files", "*.*")
            ],
            initialdir=str(self.backup_manager.backup_dir)
        )

        if not backup_file:
            self.log_status("Restore cancelled - no file selected.")
            return

        # Final confirmation with filename
        final_confirm = messagebox.askyesno(
            "Final Confirmation",
            f"You are about to restore from:\n\n{Path(backup_file).name}\n\n"
            f"This will OVERWRITE the current database.\n\n"
            f"Are you absolutely sure you want to proceed?",
            icon='warning'
        )

        if not final_confirm:
            self.log_status("Restore operation cancelled by user.")
            return

        # Disable button
        self.restore_backup_btn.config(state='disabled')
        self.backup_in_progress = True

        # Run restore in separate thread
        self.backup_thread = threading.Thread(
            target=self._restore_backup_thread,
            args=(backup_file,),
            daemon=True
        )
        self.backup_thread.start()

    def _restore_backup_thread(self, backup_file):
        """Thread function to restore backup"""
        try:
            self.log_status("=" * 60)
            self.log_status("🔄 Starting database restore operation...")
            self.log_status(f"📁 Source file: {Path(backup_file).name}")
            self.log_status("=" * 60)
            self.log_status("⏳ This may take several minutes depending on database size...")
            self.log_status("⚠️  DO NOT close the application during restore!")

            # Call the restore method with confirm=True
            success, message = self.backup_manager.restore_backup(backup_file, confirm=True)

            if success:
                self.log_status("=" * 60)
                self.log_status("✅ Database restored successfully!")
                self.log_status(f"💾 {message}")
                self.log_status("=" * 60)
                self.log_status("⚠️  Please restart the application to ensure all connections are refreshed.")

                # Show success dialog
                self.root.after(0, lambda: messagebox.showinfo(
                    "Restore Successful",
                    f"Database restored successfully!\n\n"
                    f"Source: {Path(backup_file).name}\n\n"
                    f"{message}\n\n"
                    f"IMPORTANT: Please restart the application\n"
                    f"to ensure all connections are properly refreshed."
                ))
            else:
                self.log_status("=" * 60)
                self.log_status(f"❌ Restore failed: {message}")
                self.log_status("=" * 60)

                self.root.after(0, lambda: messagebox.showerror(
                    "Restore Failed",
                    f"Failed to restore database:\n\n{message}\n\n"
                    f"Please check the backup file is valid and try again.\n"
                    f"If the problem persists, contact your system administrator."
                ))

            # Refresh the list
            self.root.after(0, self.refresh_backup_list)

        except Exception as e:
            self.log_status("=" * 60)
            self.log_status(f"❌ Error during restore: {str(e)}")
            self.log_status("=" * 60)

            self.root.after(0, lambda: messagebox.showerror(
                "Restore Error",
                f"Error restoring backup:\n\n{str(e)}\n\n"
                f"Please check the log for details."
            ))
        finally:
            self.backup_in_progress = False
            self.root.after(0, lambda: self.restore_backup_btn.config(state='normal'))

    def refresh_backup_list(self):
        """Refresh the list of available backups"""
        # Clear existing items
        for item in self.backup_tree.get_children():
            self.backup_tree.delete(item)

        # Get list of backups
        backups = self.backup_manager.list_backups()

        if not backups:
            self.log_status("No backups found. Create your first backup by clicking 'Create Backup Now'.")
            return

        # Add backup entries to tree
        for backup in backups:
            values = (
                backup['filename'],
                f"{backup['size_mb']:.2f}",
                backup['created'],
                str(backup['age_days'])
            )
            self.backup_tree.insert('', 'end', values=values)

        self.log_status(f"Found {len(backups)} backup(s)")

    def cleanup_backups_handler(self):
        """Handle cleanup of old backups"""
        if messagebox.askyesno(
            "Cleanup Old Backups",
            "This will delete backups older than the retention period.\n\n"
            "Backups to be removed will be based on the configured retention days.\n\n"
            "Continue?"
        ):
            try:
                self.log_status("Starting cleanup of old backups...")
                removed = self.backup_manager.cleanup_old_backups()
                self.log_status(f"✅ Cleanup complete! Removed {removed} old backup(s).")
                self.refresh_backup_list()
                messagebox.showinfo("Cleanup Complete",
                                   f"Removed {removed} old backup(s)")
            except Exception as e:
                self.log_status(f"❌ Cleanup failed: {str(e)}")
                messagebox.showerror("Cleanup Failed", f"Error during cleanup:\n\n{str(e)}")

    def export_backup_handler(self):
        """Export selected backup to user-specified location"""
        selection = self.backup_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a backup to export.")
            return

        item = selection[0]
        values = self.backup_tree.item(item, 'values')
        filename = values[0]
        source_path = self.backup_manager.backup_dir / filename

        if not source_path.exists():
            messagebox.showerror("File Not Found", f"Backup file not found: {source_path}")
            return

        # Ask user where to save
        save_path = filedialog.asksaveasfilename(
            defaultextension=".cmmsbackup",
            filetypes=[("CMMS Backup Files", "*.cmmsbackup"), ("All Files", "*.*")],
            initialfile=filename,
            title="Export Backup File"
        )

        if not save_path:
            return

        try:
            self.log_status(f"Exporting backup to: {save_path}")
            shutil.copy2(source_path, save_path)
            self.log_status(f"✅ Backup exported successfully!")
            self.log_status(f"📁 Saved to: {save_path}")

            messagebox.showinfo(
                "Export Successful",
                f"Backup file exported successfully!\n\n"
                f"Location: {save_path}\n\n"
                f"You can now upload this file to SharePoint."
            )
        except Exception as e:
            self.log_status(f"❌ Export failed: {str(e)}")
            messagebox.showerror("Export Failed", f"Error exporting backup:\n\n{str(e)}")

    def delete_backup_handler(self):
        """Delete selected backup"""
        selection = self.backup_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a backup to delete.")
            return

        item = selection[0]
        values = self.backup_tree.item(item, 'values')
        filename = values[0]
        backup_path = self.backup_manager.backup_dir / filename

        if messagebox.askyesno("Confirm Delete",
                              f"Are you sure you want to delete:\n\n{filename}?\n\nThis cannot be undone."):
            try:
                backup_path.unlink()
                self.log_status(f"✅ Backup deleted: {filename}")
                self.refresh_backup_list()
                messagebox.showinfo("Deleted", "Backup file deleted successfully.")
            except Exception as e:
                self.log_status(f"❌ Delete failed: {str(e)}")
                messagebox.showerror("Delete Failed", f"Error deleting backup:\n\n{str(e)}")

    def view_backup_details(self):
        """View details of selected backup"""
        selection = self.backup_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a backup to view.")
            return

        item = selection[0]
        values = self.backup_tree.item(item, 'values')
        filename, size_mb, created, age = values

        # Get backup log info
        log_entries = self.backup_manager.get_backup_log()
        backup_log_info = "No log information available"

        for entry in reversed(log_entries):
            if entry['backup_file'] == filename:
                backup_log_info = f"""
Status: {entry['status'].upper()}
Message: {entry['message']}
File Size: {entry['file_size']:,} bytes
Timestamp: {entry['timestamp']}
"""
                break

        details = f"""
BACKUP DETAILS
{'=' * 60}

Filename:       {filename}
Size:           {size_mb} MB
Created:        {created}
Age:            {age} days

Verification Log:
{backup_log_info}

EXPORT INSTRUCTIONS:
1. Click 'Export Selected Backup' to save this file
2. Upload the exported file to SharePoint
3. Keep a copy as your disaster recovery backup
"""

        messagebox.showinfo("Backup Details", details)

    def show_backup_context_menu(self, event):
        """Show context menu on right-click"""
        item = self.backup_tree.selection()
        if not item:
            return

        menu = tk.Menu(self.backup_window, tearoff=0)
        menu.add_command(label="Export Backup", command=self.export_backup_handler)
        menu.add_command(label="View Details", command=self.view_backup_details)
        menu.add_separator()
        menu.add_command(label="Delete Backup", command=self.delete_backup_handler)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def save_config(self):
        """Save backup configuration"""
        try:
            new_config = {
                'schedule': self.schedule_var.get(),
                'retention_days': int(self.retention_var.get())
            }
            self.backup_manager.update_config(new_config)
            self.log_status("✅ Configuration saved successfully!")
            messagebox.showinfo("Configuration Saved",
                              "Backup configuration updated successfully.")
        except ValueError:
            messagebox.showerror("Invalid Input",
                                "Retention days must be a number.")
        except Exception as e:
            self.log_status(f"❌ Error saving configuration: {str(e)}")
            messagebox.showerror("Save Error", f"Error saving configuration:\n\n{str(e)}")


def show_backup_window(root, db_config, user_name="Unknown"):
    """Convenience function to show backup window"""
    backup_ui = BackupUI(root, db_config, user_name)
    backup_ui.open_backup_window()
    return backup_ui
