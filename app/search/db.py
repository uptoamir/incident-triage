"""SQLite connections and schema setup."""

import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA_VERSION = 1
_SCHEMA_SQL = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
_TABLES = ("incidents_fts", "incident_tags", "incidents")


class Database:
    """Hands out short-lived connections. One unit of work = one connection."""

    def __init__(self, path: str):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        # isolation_level=None: we issue BEGIN/COMMIT ourselves. Python's implicit transactions
        # and an explicit BEGIN IMMEDIATE don't mix ("cannot start a transaction within a transaction").
        # check_same_thread=False: FastAPI may run a sync dependency and the endpoint on different
        # threadpool threads; each connection is still used by one request at a time.
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_schema(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn:
            _check_fts5(conn)
            conn.execute("PRAGMA journal_mode = WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                # the DB is only a derived index of the dataset: rebuild it empty, then re-run POST /ingest
                for table in _TABLES:
                    conn.execute(f"DROP TABLE IF EXISTS {table}")  # fixed names, not user input
            conn.executescript(_SCHEMA_SQL)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def fts5_available(self) -> bool:
        try:
            with closing(self.connect()) as conn:
                _check_fts5(conn)
            return True
        except RuntimeError:
            return False


def _check_fts5(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp._fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS temp._fts5_probe")
    except sqlite3.OperationalError as exc:
        raise RuntimeError(
            "This Python's SQLite has no FTS5. Run with `uv run` (Python 3.12 from uv or Homebrew)."
        ) from exc
