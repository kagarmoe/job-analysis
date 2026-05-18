"""
Bronze layer: raw snapshot storage.

One database per board type, stored under bronze/:
  bronze/ashby.db, bronze/greenhouse.db, bronze/adhoc.db

Stores fetched HTML/JSON verbatim so parsing can be re-run without re-scraping.
Key: (company, job_id, source_date, page_type). Duplicate inserts are silently ignored.
copper_id is a FK reference to the copper layer record for this job.
"""

import sqlite3
import re as _re
import json as _json
from datetime import datetime, timezone
from pathlib import Path
from classify import parse_json_ld_job_posting as _parse_jld

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
          page_type: str, source_date: str, original_url: str | None = None,
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


_ASHBY_JOB_URL_RE = _re.compile(
    r"jobs\.ashbyhq\.com/([^/]+)"
    r"/([0-9a-zA-Z][0-9a-zA-Z\-]+)"
    r"(/application)?$",
)
_ASHBY_API_BOARD_RE = _re.compile(
    r"api\.ashbyhq\.com/posting-api/job-board/([^/]+)$"
)


def derive_ashby(copper_conn: sqlite3.Connection, bronze_conn: sqlite3.Connection,
                 company: str) -> int:
    """Derive per-job bronze records from copper for an Ashby company."""
    rows = copper_conn.execute(
        "SELECT id, url, content, source_date FROM snapshots "
        "WHERE url LIKE ? OR url LIKE ?",
        (f"%jobs.ashbyhq.com/{company}/%",
         f"%api.ashbyhq.com/posting-api/job-board/{company}%"),
    ).fetchall()

    count = 0
    for row in rows:
        url = row["url"]
        content = row["content"] or ""

        # Board-level API response: split into per-job api_board records
        if _ASHBY_API_BOARD_RE.search(url):
            try:
                jobs = _json.loads(content).get("jobs", [])
            except Exception:
                continue
            for job in jobs:
                jid = str(job.get("id", ""))
                if not jid:
                    continue
                store(bronze_conn, company=company, board="ashby", job_id=jid,
                      page_type="api_board", source_date=row["source_date"],
                      original_url=url, http_status=200,
                      content=_json.dumps(job), copper_id=row["id"])
                count += 1
            continue

        # Individual job page or /application page
        m = _ASHBY_JOB_URL_RE.search(url)
        if not m:
            continue
        job_id = m.group(2)
        is_application = bool(m.group(3))
        page_type = "application" if is_application else "job_page"

        if is_application and content:
            jld = _parse_jld(content)
            content = _json.dumps(jld) if jld else content

        store(bronze_conn, company=company, board="ashby", job_id=job_id,
              page_type=page_type, source_date=row["source_date"],
              original_url=url, http_status=200, content=content,
              copper_id=row["id"])
        count += 1
    return count


_GH_API_RE = _re.compile(r"boards-api\.greenhouse\.io/v1/boards/([^/]+)/jobs")


def derive_greenhouse(copper_conn: sqlite3.Connection, bronze_conn: sqlite3.Connection,
                      company: str) -> int:
    """Derive per-job bronze records from copper for a Greenhouse company."""
    rows = copper_conn.execute(
        "SELECT id, url, content, source_date FROM snapshots WHERE url LIKE ?",
        (f"%greenhouse.io%boards/{company}%",),
    ).fetchall()

    count = 0
    for row in rows:
        if not _GH_API_RE.search(row["url"]):
            continue
        try:
            jobs = _json.loads(row["content"] or "{}").get("jobs", [])
        except Exception:
            continue
        for job in jobs:
            jid = str(job.get("id", ""))
            if not jid:
                continue
            store(bronze_conn, company=company, board="greenhouse", job_id=jid,
                  page_type="api_board", source_date=row["source_date"],
                  original_url=row["url"], http_status=200,
                  content=_json.dumps(job), copper_id=row["id"])
            count += 1
    return count
