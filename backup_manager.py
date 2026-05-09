"""
Backup Manager Module
Handles automated database backups including:
- Scheduled backups (daily, weekly, monthly)
- Backup retention and cleanup
- Backup verification
- Restore capabilities
- Compression support

Uses psycopg2 directly to connect to the NEON cloud database.
No local PostgreSQL installation (pg_dump / pg_restore) is required.
"""

import os
import gzip
import shutil
import threading
import time
from datetime import datetime, timedelta, date
from decimal import Decimal
import uuid
from typing import List, Dict, Optional, Tuple
import json
from pathlib import Path
import hashlib


# Backup file extension for the Python-native format
BACKUP_FILE_EXTENSION = ".cmmsbackup"


# ---------------------------------------------------------------------------
# Value serialisation helpers
# Psycopg2 returns rich Python types (datetime, Decimal, UUID, …) that are
# not directly JSON-serialisable.  We tag them so we can round-trip them
# faithfully on restore.
# ---------------------------------------------------------------------------

def _serialize_value(v):
    """Convert a value fetched from psycopg2 into a JSON-serialisable form."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, datetime):
        return {'_t': 'dt', 'v': v.isoformat()}
    if isinstance(v, date):
        return {'_t': 'd', 'v': v.isoformat()}
    if isinstance(v, Decimal):
        return {'_t': 'dec', 'v': str(v)}
    if isinstance(v, uuid.UUID):
        return {'_t': 'uuid', 'v': str(v)}
    if isinstance(v, memoryview):
        return {'_t': 'bytes', 'v': bytes(v).hex()}
    if isinstance(v, bytes):
        return {'_t': 'bytes', 'v': v.hex()}
    # Lists / dicts (e.g. JSONB columns) are already JSON-compatible
    if isinstance(v, (list, dict)):
        return v
    # Fallback – convert to string so we never crash the backup
    return str(v)


def _deserialize_value(v):
    """Restore a tagged JSON value back to the Python type psycopg2 expects."""
    if isinstance(v, dict) and '_t' in v:
        t, val = v['_t'], v['v']
        if t == 'dt':
            return datetime.fromisoformat(val)
        if t == 'd':
            return date.fromisoformat(val)
        if t == 'dec':
            return Decimal(val)
        if t == 'uuid':
            return uuid.UUID(val)
        if t == 'bytes':
            return bytes.fromhex(val)
    return v


# ---------------------------------------------------------------------------
# Table-ordering helper (topological sort on FK dependencies)
# Used to ensure parent tables are inserted before child tables on restore.
# ---------------------------------------------------------------------------

def _get_table_insert_order(conn, tables: List[str]) -> List[str]:
    """
    Return *tables* sorted so that FK parent tables come before child tables.
    Falls back to the original order if the query fails.
    """
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT tc.table_name   AS child,
                   ccu.table_name  AS parent
            FROM   information_schema.table_constraints  tc
            JOIN   information_schema.referential_constraints rc
                   ON tc.constraint_name = rc.constraint_name
                   AND tc.constraint_schema = rc.constraint_schema
            JOIN   information_schema.constraint_column_usage ccu
                   ON rc.unique_constraint_name = ccu.constraint_name
                   AND rc.unique_constraint_schema = ccu.constraint_schema
            WHERE  tc.constraint_type = 'FOREIGN KEY'
            AND    tc.table_schema    = 'public'
        """)
        deps = cur.fetchall()
        cur.close()
    except Exception:
        return tables

    # Build dependency map
    depends_on: Dict[str, set] = {t: set() for t in tables}
    for child, parent in deps:
        if child in depends_on and parent in depends_on and child != parent:
            depends_on[child].add(parent)

    # Kahn's topological sort
    ordered: List[str] = []
    visited: set = set()

    def _visit(table: str):
        if table in visited:
            return
        visited.add(table)
        for dep in depends_on.get(table, set()):
            _visit(dep)
        ordered.append(table)

    for t in tables:
        _visit(t)

    return ordered


# ---------------------------------------------------------------------------
# Backup directory helper (unchanged from original)
# ---------------------------------------------------------------------------

def get_safe_backup_directory(preferred_dir: str = None) -> Path:
    """
    Determine a safe, writable directory for backups.

    Args:
        preferred_dir: Preferred backup directory path (optional)

    Returns:
        Path object for a writable backup directory
    """
    if preferred_dir:
        try:
            test_path = Path(preferred_dir)
            test_path.mkdir(parents=True, exist_ok=True)
            test_file = test_path / ".write_test"
            test_file.touch()
            test_file.unlink()
            return test_path
        except (PermissionError, OSError):
            pass

    for candidate in [
        Path.home() / "Documents" / "AIT_CMMS_Backups",
        Path.home() / "AIT_CMMS_Backups",
    ]:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            test_file = candidate / ".write_test"
            test_file.touch()
            test_file.unlink()
            return candidate
        except (PermissionError, OSError):
            pass

    try:
        import tempfile
        temp_backup = Path(tempfile.gettempdir()) / "AIT_CMMS_Backups"
        temp_backup.mkdir(parents=True, exist_ok=True)
        return temp_backup
    except (PermissionError, OSError):
        pass

    raise PermissionError(
        "Unable to find a writable directory for backups.\n\n"
        "Tried locations:\n"
        f"1. {preferred_dir if preferred_dir else 'Not specified'}\n"
        f"2. {Path.home() / 'Documents' / 'AIT_CMMS_Backups'}\n"
        f"3. {Path.home() / 'AIT_CMMS_Backups'}\n"
        f"4. (system temp directory)\n\n"
        "Please run the application as Administrator or check folder permissions."
    )


# ---------------------------------------------------------------------------
# BackupManager
# ---------------------------------------------------------------------------

class BackupManager:
    """Manages automated database backups via a direct psycopg2 connection."""

    def __init__(self, db_config: Dict, backup_dir: str = None):
        """
        Initialise the backup manager.

        Args:
            db_config: Database configuration dictionary (host, port, database,
                       user, password, sslmode …)
            backup_dir: Directory to store backups (optional; auto-detected).
        """
        self.db_config = db_config

        self.backup_dir = get_safe_backup_directory(backup_dir)
        self.config_file = self.backup_dir / "backup_config.json"
        self.backup_log_file = self.backup_dir / "backup_log.json"

        print(f"Backup directory: {self.backup_dir}")

        self.using_fallback_location = (
            backup_dir is None or
            str(self.backup_dir) != str(Path(backup_dir).resolve())
        )

        self.config = {
            'enabled': True,
            'schedule': 'daily',
            'backup_time': '02:00',
            'retention_days': 30,
            'max_backups': 50,
            'compress': True,
            'verify_after_backup': True,
        }

        self._load_config()

        self.backup_thread = None
        self.stop_event = threading.Event()
        self.last_backup_time = None

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    def _load_config(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    self.config.update(json.load(f))
            except Exception as e:
                print(f"Error loading backup config: {e}")

    def _save_config(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Error saving backup config: {e}")

    def _log_backup(self, backup_file: str, status: str,
                    message: str = "", file_size: int = 0):
        log_entry = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'backup_file': backup_file,
            'status': status,
            'message': message,
            'file_size': file_size,
        }
        log = []
        if self.backup_log_file.exists():
            try:
                with open(self.backup_log_file, 'r') as f:
                    log = json.load(f)
            except Exception:
                pass
        log.append(log_entry)
        log = log[-1000:]
        try:
            with open(self.backup_log_file, 'w') as f:
                json.dump(log, f, indent=2)
        except Exception as e:
            print(f"Error saving backup log: {e}")

    # ------------------------------------------------------------------
    # psycopg2 connection helper
    # ------------------------------------------------------------------

    def _connect(self):
        """Open a fresh psycopg2 connection to the NEON database."""
        import psycopg2
        # Build connection kwargs; only pass keys psycopg2 understands
        conn_kwargs = {k: v for k, v in self.db_config.items()
                       if k in ('host', 'port', 'database', 'user',
                                'password', 'sslmode')}
        return psycopg2.connect(**conn_kwargs)

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def create_backup(self, backup_name: Optional[str] = None
                      ) -> Tuple[bool, str, str]:
        """
        Create a compressed database backup using psycopg2.

        Connects directly to the NEON database and exports every public table
        to a gzip-compressed JSON file.  No local PostgreSQL installation is
        required.

        Returns:
            Tuple of (success, backup_file_path, message)
        """
        filename = None
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            base = backup_name if backup_name else 'cmms_backup'
            filename = f"{base}_{timestamp}{BACKUP_FILE_EXTENSION}"
            backup_path = self.backup_dir / filename

            print(f"Creating backup: {backup_path}")

            conn = self._connect()
            cur = conn.cursor()

            # ---- Collect table names ----------------------------------------
            cur.execute("""
                SELECT table_name
                FROM   information_schema.tables
                WHERE  table_schema = 'public'
                AND    table_type   = 'BASE TABLE'
                ORDER  BY table_name
            """)
            tables = [row[0] for row in cur.fetchall()]

            if not tables:
                cur.close()
                conn.close()
                error_msg = "No tables found in the database."
                self._log_backup(filename, 'failed', error_msg)
                return False, "", error_msg

            # ---- Dump each table --------------------------------------------
            backup_data = {
                'version': '2.0',
                'app': 'AIT_CMMS',
                'created_at': datetime.now().isoformat(),
                'database': self.db_config.get('database', 'unknown'),
                'host': self.db_config.get('host', 'unknown'),
                'tables': {},
            }

            total_rows = 0
            for table in tables:
                # Column names
                cur.execute("""
                    SELECT column_name
                    FROM   information_schema.columns
                    WHERE  table_schema = 'public'
                    AND    table_name   = %s
                    ORDER  BY ordinal_position
                """, (table,))
                columns = [row[0] for row in cur.fetchall()]

                # Row data
                cur.execute(f'SELECT * FROM "{table}"')
                raw_rows = cur.fetchall()
                serialised_rows = [
                    [_serialize_value(cell) for cell in row]
                    for row in raw_rows
                ]

                backup_data['tables'][table] = {
                    'columns': columns,
                    'rows': serialised_rows,
                }
                total_rows += len(raw_rows)
                print(f"  Backed up table '{table}': {len(raw_rows)} rows")

            # ---- Collect sequence current values ----------------------------
            cur.execute("""
                SELECT sequence_name
                FROM   information_schema.sequences
                WHERE  sequence_schema = 'public'
            """)
            seq_names = [row[0] for row in cur.fetchall()]
            sequences = {}
            for seq in seq_names:
                try:
                    cur.execute(f'SELECT last_value FROM "{seq}"')
                    row = cur.fetchone()
                    if row:
                        sequences[seq] = row[0]
                except Exception:
                    pass  # Some sequences may not be readable; skip them
            backup_data['sequences'] = sequences

            cur.close()
            conn.close()

            # ---- Write compressed backup ------------------------------------
            json_bytes = json.dumps(backup_data, ensure_ascii=False).encode('utf-8')
            with gzip.open(str(backup_path), 'wb') as gz:
                gz.write(json_bytes)

            file_size = backup_path.stat().st_size
            file_size_mb = file_size / (1024 * 1024)

            # ---- Optional verification --------------------------------------
            if self.config['verify_after_backup']:
                print("Verifying backup…")
                verified, verify_msg = self._verify_backup(str(backup_path))
                if not verified:
                    self._log_backup(filename, 'failed',
                                     f"Verification failed: {verify_msg}", file_size)
                    return False, str(backup_path), \
                        f"Backup created but verification failed: {verify_msg}"

            self._log_backup(filename, 'success',
                             f"Tables: {len(tables)}, Rows: {total_rows}, "
                             f"Size: {file_size_mb:.2f} MB", file_size)
            self.last_backup_time = datetime.now()

            print(f"Backup created successfully: {backup_path} "
                  f"({len(tables)} tables, {total_rows} rows, "
                  f"{file_size_mb:.2f} MB)")
            return True, str(backup_path), \
                f"Backup created: {len(tables)} tables, {total_rows} rows, {file_size_mb:.2f} MB"

        except Exception as e:
            error_msg = f"Error creating backup: {str(e)}"
            print(error_msg)
            self._log_backup(
                filename if filename else 'unknown', 'failed', error_msg)
            return False, "", error_msg

    # ------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------

    def _verify_backup(self, backup_path: str) -> Tuple[bool, str]:
        """
        Verify a backup file by reading and parsing its contents.

        Returns:
            Tuple of (is_valid, message)
        """
        try:
            if not os.path.exists(backup_path):
                return False, "Backup file not found"

            file_size = os.path.getsize(backup_path)
            if file_size < 100:
                return False, f"Backup file too small: {file_size} bytes"

            with gzip.open(backup_path, 'rb') as gz:
                data = json.loads(gz.read().decode('utf-8'))

            if 'tables' not in data:
                return False, "Backup file missing 'tables' key"

            table_count = len(data['tables'])
            if table_count == 0:
                return False, "Backup contains no tables"

            total_rows = sum(
                len(t['rows']) for t in data['tables'].values()
                if isinstance(t, dict) and 'rows' in t
            )

            return True, (f"Verified: {table_count} tables, "
                          f"{total_rows} rows, format v{data.get('version', '?')}")

        except Exception as e:
            return False, f"Verification error: {str(e)}"

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore_backup(self, backup_path: str,
                       confirm: bool = False) -> Tuple[bool, str]:
        """
        Restore database from a .cmmsbackup file.

        Clears all public tables then re-inserts the backed-up data using
        psycopg2.  No local PostgreSQL installation is required.

        Args:
            backup_path: Path to the .cmmsbackup file
            confirm: Must be True to actually perform the restore

        Returns:
            Tuple of (success, message)
        """
        if not confirm:
            return False, "Restore not confirmed. Set confirm=True to proceed."

        conn = None
        try:
            if not os.path.exists(backup_path):
                return False, f"Backup file not found: {backup_path}"

            print(f"Loading backup: {backup_path}")
            with gzip.open(backup_path, 'rb') as gz:
                data = json.loads(gz.read().decode('utf-8'))

            if 'tables' not in data:
                return False, "Invalid backup file: missing 'tables' key"

            tables_data: Dict = data['tables']
            if not tables_data:
                return False, "Backup contains no tables to restore"

            print("Restoring from backup — this will overwrite the current database!")

            conn = self._connect()
            conn.autocommit = False
            cur = conn.cursor()

            table_names = list(tables_data.keys())

            # ---- Determine safe insert order (parents before children) ------
            ordered_tables = _get_table_insert_order(conn, table_names)

            # ---- Truncate all tables at once (CASCADE handles FK order) -----
            # Build the comma-separated quoted list
            quoted = ', '.join(f'"{t}"' for t in table_names)
            print(f"Truncating {len(table_names)} tables…")
            cur.execute(f'TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE')

            # ---- Re-insert data in FK-safe order ----------------------------
            total_inserted = 0
            for table in ordered_tables:
                tdata = tables_data.get(table)
                if not tdata:
                    continue
                columns = tdata.get('columns', [])
                rows = tdata.get('rows', [])
                if not columns or not rows:
                    continue

                col_list = ', '.join(f'"{c}"' for c in columns)
                placeholders = ', '.join(['%s'] * len(columns))
                insert_sql = (f'INSERT INTO "{table}" ({col_list}) '
                              f'VALUES ({placeholders})')

                decoded_rows = [
                    tuple(_deserialize_value(cell) for cell in row)
                    for row in rows
                ]
                cur.executemany(insert_sql, decoded_rows)
                total_inserted += len(decoded_rows)
                print(f"  Restored table '{table}': {len(decoded_rows)} rows")

            # ---- Reset sequences to backed-up values ------------------------
            sequences = data.get('sequences', {})
            for seq_name, last_value in sequences.items():
                try:
                    cur.execute(
                        f"SELECT setval(%s, %s, true)",
                        (seq_name, last_value)
                    )
                except Exception as seq_err:
                    print(f"  Warning: could not reset sequence '{seq_name}': {seq_err}")

            conn.commit()
            cur.close()

            print(f"Restore completed: {len(ordered_tables)} tables, "
                  f"{total_inserted} rows")
            return True, (f"Database restored successfully: "
                          f"{len(ordered_tables)} tables, {total_inserted} rows")

        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            return False, f"Error restoring backup: {str(e)}"
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Cleanup / listing
    # ------------------------------------------------------------------

    def cleanup_old_backups(self) -> int:
        """Remove old backups based on the configured retention policy."""
        removed_count = 0
        try:
            backup_files = sorted(
                self.backup_dir.glob(f"*{BACKUP_FILE_EXTENSION}"))

            cutoff_date = datetime.now() - timedelta(
                days=self.config['retention_days'])

            for bf in backup_files:
                file_time = datetime.fromtimestamp(bf.stat().st_mtime)
                if file_time < cutoff_date:
                    print(f"Removing old backup: {bf.name}")
                    bf.unlink()
                    removed_count += 1

            backup_files = sorted(
                self.backup_dir.glob(f"*{BACKUP_FILE_EXTENSION}"))
            if len(backup_files) > self.config['max_backups']:
                excess = len(backup_files) - self.config['max_backups']
                for bf in backup_files[:excess]:
                    print(f"Removing excess backup: {bf.name}")
                    bf.unlink()
                    removed_count += 1

        except Exception as e:
            print(f"Error cleaning up backups: {e}")

        return removed_count

    def list_backups(self) -> List[Dict]:
        """List all available backups."""
        backups = []
        try:
            backup_files = sorted(
                self.backup_dir.glob(f"*{BACKUP_FILE_EXTENSION}"),
                reverse=True)
            for bf in backup_files:
                stat = bf.stat()
                backups.append({
                    'filename': bf.name,
                    'path': str(bf),
                    'size': stat.st_size,
                    'size_mb': stat.st_size / (1024 * 1024),
                    'created': datetime.fromtimestamp(
                        stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'age_days': (
                        datetime.now() -
                        datetime.fromtimestamp(stat.st_mtime)).days,
                })
        except Exception as e:
            print(f"Error listing backups: {e}")
        return backups

    def get_backup_log(self, limit: int = 50) -> List[Dict]:
        """Get the most recent backup log entries."""
        if not self.backup_log_file.exists():
            return []
        try:
            with open(self.backup_log_file, 'r') as f:
                return json.load(f)[-limit:]
        except Exception as e:
            print(f"Error reading backup log: {e}")
            return []

    # ------------------------------------------------------------------
    # Automatic backup scheduling
    # ------------------------------------------------------------------

    def start_automatic_backups(self):
        """Start the background automatic-backup thread."""
        if self.backup_thread and self.backup_thread.is_alive():
            print("Automatic backups already running")
            return
        if not self.config['enabled']:
            print("Automatic backups disabled in configuration")
            return
        self.stop_event.clear()
        self.backup_thread = threading.Thread(
            target=self._backup_loop, daemon=True)
        self.backup_thread.start()
        print("Automatic backups started")

    def stop_automatic_backups(self):
        """Stop the background automatic-backup thread."""
        if self.backup_thread and self.backup_thread.is_alive():
            self.stop_event.set()
            self.backup_thread.join(timeout=5)
            print("Automatic backups stopped")

    def _backup_loop(self):
        print("Backup loop started")
        while not self.stop_event.is_set():
            try:
                if self._should_run_backup():
                    print("Running scheduled backup…")
                    success, path, msg = self.create_backup()
                    if success:
                        print(f"Scheduled backup successful: {msg}")
                        removed = self.cleanup_old_backups()
                        if removed:
                            print(f"Removed {removed} old backup(s)")
                    else:
                        print(f"Scheduled backup failed: {msg}")
                self.stop_event.wait(300)
            except Exception as e:
                print(f"Error in backup loop: {e}")
                self.stop_event.wait(60)

    def _should_run_backup(self) -> bool:
        """Return True if a scheduled backup is due right now."""
        now = datetime.now()
        if self.last_backup_time is None:
            return True
        try:
            backup_hour, backup_minute = map(
                int, self.config['backup_time'].split(':'))
        except Exception:
            backup_hour, backup_minute = 2, 0

        backup_time_today = now.replace(
            hour=backup_hour, minute=backup_minute,
            second=0, microsecond=0)
        time_since_last = now - self.last_backup_time

        schedule = self.config['schedule']
        if schedule == 'daily':
            return (now >= backup_time_today and
                    self.last_backup_time < backup_time_today)
        if schedule == 'weekly':
            return (now.weekday() == 0 and
                    time_since_last.days >= 7 and
                    now >= backup_time_today and
                    self.last_backup_time < backup_time_today)
        if schedule == 'monthly':
            return (now.day == 1 and
                    time_since_last.days >= 28 and
                    now >= backup_time_today and
                    self.last_backup_time < backup_time_today)
        return False

    # ------------------------------------------------------------------
    # Config / status
    # ------------------------------------------------------------------

    def update_config(self, new_config: Dict):
        self.config.update(new_config)
        self._save_config()
        print("Backup configuration updated")

    def get_config(self) -> Dict:
        return self.config.copy()

    def get_status(self) -> Dict:
        backups = self.list_backups()
        status = {
            'enabled': self.config['enabled'],
            'automatic_running': (self.backup_thread and
                                  self.backup_thread.is_alive()),
            'last_backup': None,
            'next_backup_estimate': None,
            'total_backups': len(backups),
            'total_size_mb': sum(b['size_mb'] for b in backups),
            'oldest_backup': backups[-1]['created'] if backups else None,
            'newest_backup': backups[0]['created'] if backups else None,
        }
        if self.last_backup_time:
            status['last_backup'] = self.last_backup_time.strftime(
                '%Y-%m-%d %H:%M:%S')
        return status
