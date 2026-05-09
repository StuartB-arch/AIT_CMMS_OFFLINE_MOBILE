"""
Password Change Interface for All Users
Allows users to change their own passwords
"""

import tkinter as tk
from tkinter import ttk, messagebox
from database_utils import db_pool, UserManager, AuditLogger


class PasswordChangeDialog:
    """Dialog for users to change their own password"""

    def __init__(self, parent, current_user, username):
        """
        Initialize the password change dialog

        Args:
            parent: Parent window
            current_user: Current user's full name (for audit logging)
            username: Current user's username
        """
        self.parent = parent
        self.current_user = current_user
        self.username = username
        self.dialog = None

    def show(self):
        """Show the password change dialog"""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("Change Password")
        self.dialog.geometry("450x300")
        self.dialog.transient(self.parent)
        self.dialog.grab_set()  # Make dialog modal

        # Center the dialog on parent window
        self.dialog.update_idletasks()
        x = (self.parent.winfo_width() // 2) - (450 // 2) + self.parent.winfo_x()
        y = (self.parent.winfo_height() // 2) - (300 // 2) + self.parent.winfo_y()
        self.dialog.geometry(f"450x300+{x}+{y}")

        # Header
        header_frame = ttk.Frame(self.dialog)
        header_frame.pack(fill='x', padx=20, pady=20)

        ttk.Label(header_frame, text="Change Your Password",
                  font=('Arial', 14, 'bold')).pack()

        ttk.Label(header_frame, text=f"User: {self.username}",
                  font=('Arial', 10)).pack(pady=(5, 0))

        # Form frame
        form_frame = ttk.Frame(self.dialog)
        form_frame.pack(fill='both', expand=True, padx=20, pady=10)

        # Current Password
        ttk.Label(form_frame, text="Current Password:").grid(row=0, column=0, sticky='w', pady=10)
        self.current_password_entry = ttk.Entry(form_frame, show='*', width=30)
        self.current_password_entry.grid(row=0, column=1, pady=10, padx=(10, 0))

        # New Password
        ttk.Label(form_frame, text="New Password:").grid(row=1, column=0, sticky='w', pady=10)
        self.new_password_entry = ttk.Entry(form_frame, show='*', width=30)
        self.new_password_entry.grid(row=1, column=1, pady=10, padx=(10, 0))

        # Confirm New Password
        ttk.Label(form_frame, text="Confirm New Password:").grid(row=2, column=0, sticky='w', pady=10)
        self.confirm_password_entry = ttk.Entry(form_frame, show='*', width=30)
        self.confirm_password_entry.grid(row=2, column=1, pady=10, padx=(10, 0))

        # Password requirements label
        requirements_frame = ttk.Frame(self.dialog)
        requirements_frame.pack(fill='x', padx=20, pady=5)

        ttk.Label(requirements_frame, text="Password Requirements:",
                  font=('Arial', 9, 'bold')).pack(anchor='w')
        ttk.Label(requirements_frame, text="• Minimum 4 characters",
                  font=('Arial', 8), foreground='gray').pack(anchor='w')
        ttk.Label(requirements_frame, text="• Avoid using common passwords",
                  font=('Arial', 8), foreground='gray').pack(anchor='w')

        # Buttons
        button_frame = ttk.Frame(self.dialog)
        button_frame.pack(fill='x', padx=20, pady=20)

        ttk.Button(button_frame, text="Change Password",
                   command=self.change_password).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Cancel",
                   command=self.dialog.destroy).pack(side='left', padx=5)

        # Focus on current password field
        self.current_password_entry.focus()

        # Bind Enter key to change password
        self.dialog.bind('<Return>', lambda e: self.change_password())
        self.dialog.bind('<Escape>', lambda e: self.dialog.destroy())

    def change_password(self):
        """Handle password change"""
        current_password = self.current_password_entry.get().strip()
        new_password = self.new_password_entry.get().strip()
        confirm_password = self.confirm_password_entry.get().strip()

        # Validate inputs
        if not current_password:
            messagebox.showerror("Validation Error", "Please enter your current password",
                                 parent=self.dialog)
            self.current_password_entry.focus()
            return

        if not new_password:
            messagebox.showerror("Validation Error", "Please enter a new password",
                                 parent=self.dialog)
            self.new_password_entry.focus()
            return

        if len(new_password) < 4:
            messagebox.showerror("Validation Error", "New password must be at least 4 characters long",
                                 parent=self.dialog)
            self.new_password_entry.focus()
            return

        if new_password != confirm_password:
            messagebox.showerror("Validation Error", "New passwords do not match",
                                 parent=self.dialog)
            self.confirm_password_entry.delete(0, tk.END)
            self.confirm_password_entry.focus()
            return

        if current_password == new_password:
            messagebox.showwarning("Validation Warning",
                                   "New password must be different from current password",
                                   parent=self.dialog)
            self.new_password_entry.focus()
            return

        # Attempt to change password
        try:
            with db_pool.get_cursor(commit=True) as cursor:
                success, message = UserManager.change_password(
                    cursor, self.username, current_password, new_password
                )

                if success:
                    # Log the password change to audit log
                    AuditLogger.log(
                        cursor,
                        self.current_user,
                        'UPDATE',
                        'users',
                        self.username,
                        notes="User changed their own password"
                    )

                    messagebox.showinfo("Success", message, parent=self.dialog)
                    self.dialog.destroy()
                else:
                    messagebox.showerror("Error", message, parent=self.dialog)
                    # Clear password fields if current password was wrong
                    if "incorrect" in message.lower():
                        self.current_password_entry.delete(0, tk.END)
                        self.current_password_entry.focus()

        except Exception as e:
            messagebox.showerror("Database Error",
                                 f"Failed to change password: {str(e)}",
                                 parent=self.dialog)
            print(f"Password change error: {e}")


def show_password_change_dialog(parent, current_user, username):
    """
    Convenience function to show the password change dialog

    Args:
        parent: Parent window
        current_user: Current user's full name (for audit logging)
        username: Current user's username
    """
    dialog = PasswordChangeDialog(parent, current_user, username)
    dialog.show()
