"""
Bronze layer: raw snapshot storage.

One database per board type, stored under bronze/:
  bronze/ashby.db, bronze/greenhouse.db, bronze/adhoc.db

Stores fetched HTML/JSON verbatim so parsing can be re-run without re-scraping.
Key: (company, job_id, source_date, page_type). Duplicate inserts are silently ignored.
copper_id is a FK reference to the copper layer record for this job.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company      TEXT    NOT NULL,
    board        TEXT    NOT NULL,
    job_id       TEXT    NOT NULL,
    page_type    TEXT    NOT NULL,
    source_date  TEXT    NOT NULL,
    fetched_at   TEXT    NOT NULL,
    original_url TEXT,
    http_status  INTEGER,
    content      TEXT,
    copper_id    INTEGER,
    UNIQUE(company, job_id, source_date, page_type)
);
CREATE INDEX IF NOT EXISTS idx_company_job ON snapshots(company, job_id);
"""


def open_db(board: str, base_dir: str = "bronze") -> sqlite3.Connection:
    """Open (or create) the bronze DB for a given board.

    board must be one of: ashby, greenhouse, adhoc.
    DB is created at {base_dir}/{board}.db.
    """
    Path(base_dir).mkdir(exist_ok=True)
    path = str(Path(base_dir) / f"{board}.db")
    return _open_path(path)


def _open_path(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def get_content(conn: sqlite3.Connection, company: str, job_id: str,
                source_date: str, page_type: str) -> str | None:
    """Return cached content, or None if not yet fetched."""
    row = conn.execute(
        "SELECT content FROM snapshots"
        " WHERE company=? AND job_id=? AND source_date=? AND page_type=?",
        (company, job_id, source_date, page_type),
    ).fetchone()
    return row["content"] if row else None


def store(conn: sqlite3.Connection, *, company: str, board: str, job_id: str,
          page_type: str, source_date: str, original_url: str = "",
          http_status: int, content: str, copper_id: int | None = None) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO snapshots
           (company, board, job_id, page_type, source_date, fetched_at,
            original_url, http_status, content, copper_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (company, board, job_id, page_type, source_date,
         datetime.now(timezone.utc).isoformat(),
         original_url, http_status, content, copper_id),
    )
    conn.commit()
