"""
Silver layer: classified, validated, enriched job records.

One DB at silver/jobs.db. All companies and boards in one table.
Populated by silver.ipynb — not directly by scrapers.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    company        TEXT    NOT NULL,
    board          TEXT    NOT NULL,
    job_id         TEXT    NOT NULL,
    source_date    TEXT    NOT NULL,
    title          TEXT,
    location       TEXT,
    url            TEXT,
    department_raw TEXT,
    department     TEXT,
    seniority      TEXT,
    work_mode      TEXT,
    salary_text    TEXT,
    currency       TEXT,
    salary_min     INTEGER,
    salary_max     INTEGER,
    salary_unit    TEXT,
    description_md TEXT,
    has_title      INTEGER DEFAULT 0,
    has_salary     INTEGER DEFAULT 0,
    has_location   INTEGER DEFAULT 0,
    completeness   INTEGER DEFAULT 0,
    bronze_id      INTEGER,
    processed_at   TEXT    NOT NULL,
    fetched_at     TEXT,
    UNIQUE(company, board, job_id, source_date)
);

CREATE TABLE IF NOT EXISTS silver_rejected (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    company          TEXT,
    job_id           TEXT,
    source_date      TEXT,
    rejection_reason TEXT,
    raw_content      TEXT,
    rejected_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at         TEXT NOT NULL,
    company        TEXT,
    board          TEXT,
    rows_processed INTEGER DEFAULT 0,
    rows_upserted  INTEGER DEFAULT 0,
    rows_rejected  INTEGER DEFAULT 0
);
"""

_REQUIRED = {"company", "board", "job_id", "source_date"}


def open_db(base_dir: str = "silver") -> sqlite3.Connection:
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(base_dir) / "jobs.db")
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def upsert_job(conn: sqlite3.Connection, record: dict) -> bool:
    """Upsert one job record. Returns True on success, False on rejection."""
    missing = _REQUIRED - set(record)
    if missing:
        conn.execute(
            """INSERT INTO silver_rejected
               (company, job_id, source_date, rejection_reason, rejected_at)
               VALUES (?,?,?,?,?)""",
            (record.get("company"), record.get("job_id"), record.get("source_date"),
             f"missing required fields: {missing}",
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return False

    has_title    = 1 if record.get("title") else 0
    has_salary   = 1 if record.get("salary_min") else 0
    has_location = 1 if record.get("location") else 0
    completeness = has_title + has_salary + has_location
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """INSERT INTO jobs
               (company, board, job_id, source_date, title, location, url,
                department_raw, department, seniority, work_mode, salary_text,
                currency, salary_min, salary_max, salary_unit, description_md,
                has_title, has_salary, has_location, completeness,
                bronze_id, processed_at, fetched_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(company, board, job_id, source_date) DO UPDATE SET
               title=excluded.title,
               location=excluded.location,
               url=excluded.url,
               department_raw=excluded.department_raw,
               department=excluded.department,
               seniority=excluded.seniority,
               work_mode=excluded.work_mode,
               salary_text=excluded.salary_text,
               currency=excluded.currency,
               salary_min=excluded.salary_min,
               salary_max=excluded.salary_max,
               salary_unit=excluded.salary_unit,
               description_md=excluded.description_md,
               has_title=excluded.has_title,
               has_salary=excluded.has_salary,
               has_location=excluded.has_location,
               completeness=excluded.completeness,
               bronze_id=excluded.bronze_id,
               processed_at=excluded.processed_at""",
        (record.get("company"), record.get("board"), record.get("job_id"),
         record.get("source_date"), record.get("title"), record.get("location"),
         record.get("url"), record.get("department_raw"), record.get("department"),
         record.get("seniority"), record.get("work_mode"), record.get("salary_text"),
         record.get("currency"), record.get("salary_min"), record.get("salary_max"),
         record.get("salary_unit"), record.get("description_md"),
         has_title, has_salary, has_location, completeness,
         record.get("bronze_id"), now, record.get("fetched_at")),
    )
    conn.commit()
    return True


def log_run(conn: sqlite3.Connection, company: str, board: str,
            rows_processed: int, rows_upserted: int, rows_rejected: int) -> None:
    conn.execute(
        """INSERT INTO audit_log
           (run_at, company, board, rows_processed, rows_upserted, rows_rejected)
           VALUES (?,?,?,?,?,?)""",
        (datetime.now(timezone.utc).isoformat(), company, board,
         rows_processed, rows_upserted, rows_rejected),
    )
    conn.commit()
