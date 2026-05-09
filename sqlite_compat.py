"""
sqlite_compat.py — SQLite compatibility shim for AIT CMMS

Provides a psycopg2-compatible interface over SQLite with automatic
conversion of common PostgreSQL SQL patterns to SQLite equivalents.
"""

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "ait_cmms.db"


# ── SQL auto-conversion ────────────────────────────────────────────────────────

def _pg_to_sqlite(sql: str) -> str:
    """Convert PostgreSQL SQL patterns to SQLite-compatible equivalents."""

    # DDL type compatibility (CREATE TABLE / ALTER TABLE)
    sql = re.sub(r'\bSERIAL\s+PRIMARY\s+KEY\b', 'INTEGER PRIMARY KEY', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bBIGSERIAL\b', 'INTEGER', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bSERIAL\b', 'INTEGER', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bBOOLEAN\b', 'INTEGER', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bBYTEA\b', 'BLOB', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bDEFAULT\s+TRUE\b', 'DEFAULT 1', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bDEFAULT\s+FALSE\b', 'DEFAULT 0', sql, flags=re.IGNORECASE)

    # ADD COLUMN IF NOT EXISTS → ADD COLUMN (duplicate handled in execute())
    sql = re.sub(r'\bADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\b', 'ADD COLUMN', sql, flags=re.IGNORECASE)

    # INTERVAL arithmetic: %s::date + INTERVAL 'N days' → date(%s, '+N days')
    sql = re.sub(
        r'%s::(?:date|DATE|timestamp|TIMESTAMP)\s*\+\s*INTERVAL\s*\'(\d+)\s*days?\'',
        r"date(%s, '+\1 days')", sql
    )
    # col::date + INTERVAL 'N days' → date(col, '+N days')
    sql = re.sub(
        r'(\w+)::(?:date|DATE|timestamp|TIMESTAMP)\s*\+\s*INTERVAL\s*\'(\d+)\s*days?\'',
        r"date(\1, '+\2 days')", sql
    )
    # %s::date - INTERVAL 'N days' → date(%s, '-N days')
    sql = re.sub(
        r'%s::(?:date|DATE|timestamp|TIMESTAMP)\s*-\s*INTERVAL\s*\'(\d+)\s*days?\'',
        r"date(%s, '-\1 days')", sql
    )
    # col::date - INTERVAL 'N days' → date(col, '-N days')
    sql = re.sub(
        r'(\w+)::(?:date|DATE|timestamp|TIMESTAMP)\s*-\s*INTERVAL\s*\'(\d+)\s*days?\'',
        r"date(\1, '-\2 days')", sql
    )
    # CURRENT_DATE - INTERVAL 'N days' → date('now', '-N days')
    sql = re.sub(
        r'CURRENT_DATE\s*-\s*INTERVAL\s*\'(\d+)\s*days?\'',
        r"date('now', '-\1 days')", sql, flags=re.IGNORECASE
    )

    # Date difference: CURRENT_DATE - col::date > N → julianday('now') - julianday(col) > N
    sql = re.sub(
        r'CURRENT_DATE\s*-\s*(\w+)::(?:date|DATE)\s*(>|<|>=|<=|!=|=)\s*(\d+)',
        r"julianday('now') - julianday(\1) \2 \3", sql, flags=re.IGNORECASE
    )
    # Date difference as alias: CURRENT_DATE - col::date as alias
    sql = re.sub(
        r'CURRENT_DATE\s*-\s*(\w+)::(?:date|DATE)\s+(?:as|AS)\s+(\w+)',
        r"CAST(julianday('now') - julianday(\1) AS INTEGER) as \2", sql, flags=re.IGNORECASE
    )
    # ABS(col::date - %s::date) → ABS(julianday(col) - julianday(%s))
    sql = re.sub(
        r'ABS\s*\(\s*(\w+)::(?:date|DATE)\s*-\s*%s::(?:date|DATE)\s*\)',
        r'ABS(julianday(\1) - julianday(%s))', sql
    )

    # Strip remaining ::TYPE castings
    sql = re.sub(
        r'::(?:text|TEXT|integer|INTEGER|date|DATE|timestamp|TIMESTAMP'
        r'|boolean|BOOLEAN|real|REAL|numeric|NUMERIC)',
        '', sql
    )

    # EXTRACT(field FROM col) → SQLite strftime — must run after ::TYPE stripping
    sql = re.sub(r'\bEXTRACT\s*\(\s*YEAR\s+FROM\s+([\w.]+)\s*\)',
                 r"CAST(strftime('%Y', \1) AS INTEGER)", sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bEXTRACT\s*\(\s*MONTH\s+FROM\s+([\w.]+)\s*\)',
                 r"CAST(strftime('%m', \1) AS INTEGER)", sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bEXTRACT\s*\(\s*DAY\s+FROM\s+([\w.]+)\s*\)',
                 r"CAST(strftime('%d', \1) AS INTEGER)", sql, flags=re.IGNORECASE)

    # GREATEST(a, b) → max(a, b)  – only where both args are non-NULL
    sql = re.sub(r'\bGREATEST\b', 'max', sql, flags=re.IGNORECASE)

    # ILIKE → LIKE  (SQLite LIKE is case-insensitive for ASCII by default)
    sql = re.sub(r'\bILIKE\b', 'LIKE', sql, flags=re.IGNORECASE)

    # Remove FOR UPDATE (no row-level locking in SQLite)
    sql = re.sub(r'\bFOR\s+UPDATE\b', '', sql, flags=re.IGNORECASE)

    # information_schema table existence: SELECT EXISTS (SELECT FROM info_schema.tables ...)
    # SELECT EXISTS (SELECT FROM information_schema.tables ... table_name = 'X' ...)
    # → SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='X'
    sql = re.sub(
        r"SELECT\s+EXISTS\s*\([^)]*information_schema\.tables[^)]*table_name\s*=\s*'(\w+)'[^)]*\)",
        r"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='\1'",
        sql, flags=re.IGNORECASE | re.DOTALL
    )
    # information_schema.columns column existence check
    sql = re.sub(
        r"SELECT\s+column_name\s+FROM\s+information_schema\.columns\s+"
        r"[^;]*?table_name\s*=\s*'(\w+)'[^;]*?column_name\s*=\s*'(\w+)'",
        r"SELECT name FROM pragma_table_info('\1') WHERE name='\2'",
        sql, flags=re.IGNORECASE | re.DOTALL
    )

    # %s → ?  (avoid converting %% which is a literal %)
    sql = re.sub(r'(?<!%)%s', '?', sql)
    sql = sql.replace('%%', '%')

    return sql


# ── DictRow ────────────────────────────────────────────────────────────────────

class DictRow:
    """Dict-like row, compatible with psycopg2 DictRow / RealDictRow."""

    __slots__ = ('_data', '_vals')

    def __init__(self, data: dict):
        object.__setattr__(self, '_data', data)
        object.__setattr__(self, '_vals', list(data.values()))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __contains__(self, key):
        return key in self._data

    def __iter__(self):
        return iter(self._vals)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._vals

    def items(self):
        return self._data.items()

    def __repr__(self):
        return repr(self._data)

    def __bool__(self):
        return bool(self._data)

    def __len__(self):
        return len(self._data)


def _row_to_dict(row, description) -> Optional[DictRow]:
    if row is None:
        return None
    if description:
        return DictRow({col[0]: row[i] for i, col in enumerate(description)})
    return DictRow({str(i): v for i, v in enumerate(row)})


# ── SqliteCursor ──────────────────────────────────────────────────────────────

class SqliteCursor:
    """Cursor wrapper: auto-converts PG SQL → SQLite and returns dict-like rows."""

    def __init__(self, raw: sqlite3.Cursor):
        self._cur = raw
        self._returning_col: Optional[str] = None
        self._returning_id: Optional[int] = None

    def execute(self, sql: str, params=None):
        # Detect and strip RETURNING clause
        m = re.search(r'\bRETURNING\s+(\w+)\b', sql, re.IGNORECASE)
        if m:
            self._returning_col = m.group(1)
            sql = re.sub(r'\s*\bRETURNING\s+\w+\b', '', sql, flags=re.IGNORECASE).strip()
        else:
            self._returning_col = None
            self._returning_id = None

        sql = _pg_to_sqlite(sql)
        try:
            if params is not None:
                self._cur.execute(sql, params)
            else:
                self._cur.execute(sql)
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if 'duplicate column name' in msg:
                # Emulate ADD COLUMN IF NOT EXISTS — silently skip
                return self
            raise

        if self._returning_col is not None:
            self._returning_id = self._cur.lastrowid

        return self

    def executemany(self, sql: str, seq):
        sql = _pg_to_sqlite(sql)
        self._cur.executemany(sql, seq)
        return self

    def fetchone(self):
        if self._returning_col is not None:
            result = DictRow({self._returning_col: self._returning_id})
            self._returning_col = None
            self._returning_id = None
            return result
        row = self._cur.fetchone()
        return _row_to_dict(row, self._cur.description)

    def fetchall(self):
        desc = self._cur.description
        return [_row_to_dict(r, desc) for r in self._cur.fetchall()]

    def close(self):
        self._cur.close()

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def __iter__(self):
        desc = self._cur.description
        for row in self._cur:
            yield _row_to_dict(row, desc)


# ── Custom SQLite functions ────────────────────────────────────────────────────

def _split_part(string: Optional[str], delimiter: str, field_index: int) -> str:
    """PostgreSQL SPLIT_PART equivalent for SQLite. Field index is 1-based."""
    if string is None:
        return ''
    parts = string.split(delimiter)
    idx = int(field_index)
    if idx < 1 or idx > len(parts):
        return ''
    return parts[idx - 1]


# ── SqliteConnection ───────────────────────────────────────────────────────────

class SqliteConnection:
    """Connection wrapper providing psycopg2-compatible interface over sqlite3."""

    def __init__(self, db_path: Optional[Path] = None):
        path = str(db_path or DB_PATH)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.create_function('SPLIT_PART', 3, _split_part)
        self._closed = False

    def cursor(self, cursor_factory=None):
        return SqliteCursor(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        if not self._closed:
            self._conn.close()
            self._closed = True

    @property
    def closed(self):
        return self._closed

    @property
    def autocommit(self):
        return False

    @autocommit.setter
    def autocommit(self, value):
        pass  # SQLite always uses manual transaction control

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        return False


# ── execute_values ─────────────────────────────────────────────────────────────

def execute_values(cursor, sql: str, rows, page_size: int = 500):
    """
    Drop-in replacement for psycopg2.extras.execute_values.
    Converts VALUES %s template to per-row (?,?,...) and uses executemany.
    """
    if not rows:
        return

    n = len(rows[0])
    placeholders = "(" + ", ".join(["?"] * n) + ")"

    # Replace VALUES %s with VALUES (?,?,...)
    sql_fixed = re.sub(r'VALUES\s+%s\b', f'VALUES {placeholders}', sql, flags=re.IGNORECASE)
    sql_fixed = _pg_to_sqlite(sql_fixed)

    raw = cursor._cur if hasattr(cursor, '_cur') else cursor
    for i in range(0, len(rows), page_size):
        raw.executemany(sql_fixed, rows[i:i + page_size])


# ── factory ───────────────────────────────────────────────────────────────────

def get_db_connection(db_path: Optional[Path] = None) -> SqliteConnection:
    """Open a new SQLite connection wrapped in the compatibility layer."""
    return SqliteConnection(db_path)
