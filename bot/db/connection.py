
import sqlite3
import contextlib
from bot.config import DB_PATH
from bot.db.migrations import run_migrations

@contextlib.contextmanager
def get_connection(db_path=None) -> sqlite3.Connection:
    """Establishes a connection to the SQLite database."""
    path_to_use = db_path if db_path else DB_PATH
    conn = sqlite3.connect(path_to_use, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    run_migrations(conn)
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
