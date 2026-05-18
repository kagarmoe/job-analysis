"""
Copper layer: raw HTTP response storage — one DB per board.

copper/ashby.db, copper/greenhouse.db, copper/adhoc.db

Immutable. Never modified after insert. Only layer that touches the network.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT    NOT NULL,
    http_status INTEGER,
    content     TEXT,
    source_date TEXT    NOT NULL,
    fetched_at  TEXT    NOT NULL,
    UNIQUE(url, source_date)
);
CREATE INDEX IF NOT EXISTS idx_url ON snapshots(url);
"""


def open_db(board: str, base_dir: str = "copper") -> sqlite3.Connection:
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(base_dir) / f"{board}.db")
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def get_content(conn: sqlite3.Connection, url: str, source_date: str) -> str | None:
    row = conn.execute(
        "SELECT content FROM snapshots WHERE url=? AND source_date=?",
        (url, source_date),
    ).fetchone()
    return row["content"] if row else None


def store(conn: sqlite3.Connection, *, url: str, http_status: int,
          content: str, source_date: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO snapshots (url, http_status, content, source_date, fetched_at)
           VALUES (?,?,?,?,?)""",
        (url, http_status, content, source_date,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
