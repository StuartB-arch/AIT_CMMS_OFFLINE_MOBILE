#!/usr/bin/env python3
"""
Debug startup script to capture error messages
Run this instead of the main application to see detailed error output
"""

import sys
import traceback
from datetime import datetime
import io

# Configure console to handle Unicode on Windows
if sys.platform == 'win32':
    # Ensure console can display Unicode characters
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass  # If reconfiguration fails, continue with defaults

# Redirect all output to a log file
log_file = f"startup_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Save original stdout/stderr for error reporting
original_stdout = sys.stdout
original_stderr = sys.stderr

try:
    print(f"Starting application... (logging to {log_file})")

    with open(log_file, 'w', encoding='utf-8') as f:
        # Redirect stdout and stderr
        sys.stdout = f
        sys.stderr = f

        print("=" * 80)
        print(f"Application Startup Debug Log - {datetime.now()}")
        print("=" * 80)
        print()

        # Import and run the main application
        print("Importing main application module...")
        import AIT_CMMS_REV3
        import tkinter as tk

        print("Main module imported successfully")
        print("Starting main application...")

        # Create the Tkinter root and application instance
        print("Creating Tkinter root window...")
        root = tk.Tk()
        print("Tk root window created")

        print("Initializing AIT CMMS System...")
        app = AIT_CMMS_REV3.AITCMMSSystem(root)

        print("=" * 80)
        print("Application initialized successfully!")
        print("Starting Tkinter mainloop...")
        print("=" * 80)

        # Start the application main loop
        root.mainloop()

        print("Application closed normally")

except Exception as e:
    # Write error to log file
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write("\n" + "=" * 80 + "\n")
        f.write("FATAL ERROR DURING STARTUP\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Error Type: {type(e).__name__}\n")
        f.write(f"Error Message: {str(e)}\n\n")
        f.write("Full Traceback:\n")
        f.write(traceback.format_exc())
        f.write("\n" + "=" * 80 + "\n")

    # Restore original stdout/stderr to print to console
    sys.stdout = original_stdout
    sys.stderr = original_stderr

    print(f"\n\nERROR: Application crashed during startup!")
    print(f"Error details have been saved to: {log_file}")
    print(f"\nError: {type(e).__name__}: {str(e)}")
    print(f"\nPlease share the contents of {log_file} for debugging.")
    sys.exit(1)
