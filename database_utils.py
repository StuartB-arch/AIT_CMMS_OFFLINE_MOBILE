"""
Database Utilities for AIT CMMS — SQLite Edition
Replaces the cloud PostgreSQL version with a local SQLite database.
Keeps the same public API so all other modules work without changes.
"""

import hashlib
import threading
from contextlib import contextmanager
from pathlib import Path

from sqlite_compat import SqliteConnection, get_db_connection, DB_PATH


class DatabaseConnectionPool:
    """
    SQLite 'pool' — single shared connection.
    SQLite in WAL mode handles concurrent reads safely.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_conn'):
            self._conn: SqliteConnection | None = None
            self._conn_lock = threading.Lock()

    def initialize(self, db_config=None, min_conn=1, max_conn=10):
        """Open the SQLite database. db_config and pool-size args are ignored."""
        with self._conn_lock:
            if self._conn is None or self._conn.closed:
                self._conn = get_db_connection()
                print(f"SQLite database opened: {DB_PATH}")

    def get_connection(self, max_retries=3):
        """Return the shared SQLite connection, initialising if necessary."""
        if self._conn is None or self._conn.closed:
            self.initialize()
        return self._conn

    def return_connection(self, conn):
        """No-op — the shared connection stays open."""
        pass

    def close_all(self):
        """Close the database connection."""
        with self._conn_lock:
            if self._conn and not self._conn.closed:
                self._conn.close()
                self._conn = None
                print("SQLite database connection closed")

    @contextmanager
    def get_cursor(self, commit=True):
        """Context manager that yields a cursor from the shared connection."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            if commit:
                conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            raise exc
        finally:
            try:
                cursor.close()
            except Exception:
                pass


class OptimisticConcurrencyControl:
    """Optimistic locking for concurrent updates."""

    @staticmethod
    def check_version(cursor, table, record_id, expected_version, id_column='id'):
        cursor.execute(
            f"SELECT version FROM {table} WHERE {id_column} = %s",
            (record_id,)
        )
        result = cursor.fetchone()
        if not result:
            return False, None, f"Record not found in {table}"

        current_version = result[0] if isinstance(result, (tuple, list)) else result['version']
        if current_version != expected_version:
            return False, current_version, (
                f"Conflict detected: Record was modified by another user. "
                f"Expected version {expected_version}, found {current_version}."
            )
        return True, current_version, "Version check passed"

    @staticmethod
    def increment_version(cursor, table, record_id, id_column='id'):
        cursor.execute(
            f"""
            UPDATE {table}
            SET version = version + 1,
                updated_date = CURRENT_TIMESTAMP
            WHERE {id_column} = %s
            """,
            (record_id,)
        )


class AuditLogger:
    """Logs all database changes for audit trail."""

    @staticmethod
    def log(cursor, user_name, action, table_name, record_id,
            old_values=None, new_values=None, notes=None):
        cursor.execute(
            """
            INSERT INTO audit_log
            (user_name, action, table_name, record_id, old_values, new_values,
             notes, action_timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """,
            (user_name, action, table_name, record_id,
             str(old_values), str(new_values), notes)
        )


class UserManager:
    """Manages user authentication and sessions."""

    @staticmethod
    def hash_password(password):
        return hashlib.sha256(password.encode()).hexdigest()

    @staticmethod
    def verify_password(password, hashed_password):
        return UserManager.hash_password(password) == hashed_password

    @staticmethod
    def authenticate(cursor, username, password):
        cursor.execute(
            """
            SELECT id, username, full_name, role, password_hash, is_active
            FROM users
            WHERE username = %s
            """,
            (username,)
        )
        user = cursor.fetchone()
        if not user:
            return None

        if isinstance(user, (tuple, list)):
            user = {
                'id': user[0], 'username': user[1], 'full_name': user[2],
                'role': user[3], 'password_hash': user[4], 'is_active': user[5]
            }
        elif not isinstance(user, dict):
            user = dict(user)

        if not user['is_active']:
            return None
        if not UserManager.verify_password(password, user['password_hash']):
            return None

        del user['password_hash']
        return user

    @staticmethod
    def change_password(cursor, username, current_password, new_password):
        cursor.execute(
            """
            SELECT id, password_hash, is_active
            FROM users WHERE username = %s
            """,
            (username,)
        )
        user = cursor.fetchone()
        if not user:
            return False, "User not found"

        if isinstance(user, (tuple, list)):
            user = {'id': user[0], 'password_hash': user[1], 'is_active': user[2]}
        elif not isinstance(user, dict):
            user = dict(user)

        if not user['is_active']:
            return False, "Account is not active"
        if not UserManager.verify_password(current_password, user['password_hash']):
            return False, "Current password is incorrect"

        cursor.execute(
            """
            UPDATE users
            SET password_hash = %s, updated_date = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (UserManager.hash_password(new_password), user['id'])
        )
        return True, "Password changed successfully"

    @staticmethod
    def create_session(cursor, user_id, username):
        cursor.execute(
            """
            INSERT INTO user_sessions
            (user_id, username, login_time, last_activity, is_active)
            VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)
            """,
            (user_id, username)
        )
        return cursor.lastrowid

    @staticmethod
    def update_session_activity(cursor, session_id):
        cursor.execute(
            """
            UPDATE user_sessions SET last_activity = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (session_id,)
        )

    @staticmethod
    def end_session(cursor, session_id):
        cursor.execute(
            """
            UPDATE user_sessions
            SET logout_time = CURRENT_TIMESTAMP, is_active = 0
            WHERE id = %s
            """,
            (session_id,)
        )

    @staticmethod
    def get_active_sessions(cursor):
        cursor.execute(
            """
            SELECT s.id, s.user_id, s.username, u.full_name, u.role,
                   s.login_time, s.last_activity
            FROM user_sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.is_active = 1
            ORDER BY s.login_time DESC
            """
        )
        return cursor.fetchall()


class TransactionManager:
    """Manages database transactions."""

    @staticmethod
    @contextmanager
    def transaction(pool, max_retries=3):
        conn = pool.get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            raise exc
        finally:
            try:
                cursor.close()
            except Exception:
                pass


# Global pool instance
db_pool = DatabaseConnectionPool()
