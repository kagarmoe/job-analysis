# Medallion Layer-as-Notebook Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace `copper.py`, `bronze.py`, `silver.py`, `classify.py` with `db.py` (importable DB utilities + salary parsing) and `classify.ipynb` (classification functions), with `copper.ipynb` and `bronze.ipynb` as executable layer notebooks.

**Architecture:** `db.py` becomes the single importable module for DB open/store/derive/upsert/log functions and salary parsing utilities. Classification logic (department, seniority, work mode, yoe) moves to `classify.ipynb`; notebooks use `%run classify.ipynb` to load those functions. `bronze.ipynb` and `silver.ipynb` are the execution entry points for their layers; `run_pipeline.py` invokes them via nbconvert.

**Tech Stack:** Python 3.11, SQLite3, BeautifulSoup4, html2text, nbconvert, Jupyter

---

### Task 1: Create `db.py`

Consolidates copper.py + bronze.py + silver.py into one importable module. Also includes salary parsing utilities (currently in classify.py) since `derive_ashby` needs them. Classification functions (department rules, seniority, etc.) do NOT go here — they stay in classify.ipynb.

**Files:**
- Create: `db.py`
- Test: `tests/test_db.py`

**Step 1: Write failing tests**

```python
# tests/test_db.py
import sqlite3
import json
import pytest
import db


# ── Copper ──────────────────────────────────────────────────────────────────

def test_open_copper_creates_schema(tmp_path):
    conn = db.open_copper("ashby", base_dir=str(tmp_path))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "snapshots" in tables


def test_store_copper_idempotent(tmp_path):
    conn = db.open_copper("ashby", base_dir=str(tmp_path))
    db.store_copper(conn, url="https://example.com", http_status=200,
                    content="hello", source_date="20260101")
    db.store_copper(conn, url="https://example.com", http_status=200,
                    content="hello", source_date="20260101")
    count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    assert count == 1


# ── Bronze ──────────────────────────────────────────────────────────────────

def test_open_bronze_creates_schema(tmp_path):
    conn = db.open_bronze("ashby", base_dir=str(tmp_path))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "snapshots" in tables


def test_store_bronze_idempotent(tmp_path):
    conn = db.open_bronze("ashby", base_dir=str(tmp_path))
    db.store_bronze(conn, company="acme", board="ashby", job_id="abc123",
                    page_type="api_board", source_date="20260101",
                    http_status=200, content="{}", copper_id=None)
    db.store_bronze(conn, company="acme", board="ashby", job_id="abc123",
                    page_type="api_board", source_date="20260101",
                    http_status=200, content="{}", copper_id=None)
    count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    assert count == 1


def test_derive_ashby_board_api(tmp_path):
    copper_conn = db.open_copper("ashby", base_dir=str(tmp_path))
    bronze_conn = db.open_bronze("ashby", base_dir=str(tmp_path))
    jobs_payload = json.dumps({"jobs": [{"id": "aaa-111", "title": "Eng"}]})
    db.store_copper(copper_conn,
                    url="https://api.ashbyhq.com/posting-api/job-board/acme",
                    http_status=200, content=jobs_payload, source_date="20260101")
    count = db.derive_ashby(copper_conn, bronze_conn, "acme")
    assert count == 1
    row = bronze_conn.execute("SELECT * FROM snapshots WHERE job_id='aaa-111'").fetchone()
    assert row is not None
    assert row["page_type"] == "api_board"


# ── Silver ──────────────────────────────────────────────────────────────────

def test_open_silver_creates_schema(tmp_path):
    conn = db.open_silver(base_dir=str(tmp_path))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "jobs" in tables
    assert "silver_rejected" in tables
    assert "audit_log" in tables


def test_open_silver_adds_yoe_column(tmp_path):
    conn = db.open_silver(base_dir=str(tmp_path))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "yoe" in cols


def test_upsert_job_success(tmp_path):
    conn = db.open_silver(base_dir=str(tmp_path))
    ok = db.upsert_job(conn, {
        "company": "acme", "board": "ashby", "job_id": "j1",
        "source_date": "20260101", "title": "Engineer",
    })
    assert ok is True
    row = conn.execute("SELECT title FROM jobs WHERE job_id='j1'").fetchone()
    assert row["title"] == "Engineer"


def test_upsert_job_missing_required(tmp_path):
    conn = db.open_silver(base_dir=str(tmp_path))
    ok = db.upsert_job(conn, {"company": "acme", "job_id": "j2"})  # missing board, source_date
    assert ok is False
    rejected = conn.execute("SELECT * FROM silver_rejected WHERE job_id='j2'").fetchone()
    assert rejected is not None


def test_log_run(tmp_path):
    conn = db.open_silver(base_dir=str(tmp_path))
    db.log_run(conn, "acme", "ashby", rows_processed=10, rows_upserted=9, rows_rejected=1)
    row = conn.execute("SELECT * FROM audit_log WHERE company='acme'").fetchone()
    assert row["rows_processed"] == 10


# ── Salary parsing ──────────────────────────────────────────────────────────

def test_parse_salary_range():
    result = db.parse_salary_text("$120,000 – $180,000 USD annually")
    assert result.salary_min == 120000
    assert result.salary_max == 180000
    assert result.currency == "USD"


def test_extract_salary_block_finds_range():
    html = "<p>Compensation: $150,000–$200,000 per year</p>"
    block = db.extract_salary_block_from_html(html)
    assert block is not None
    assert "150" in block
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/kimberlygarmoe/repos/job-analysis
source .venv/bin/activate
pytest tests/test_db.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'db'`

**Step 3: Create `db.py`**

```python
"""
db.py — single importable module for all DB utilities and salary parsing.

Replaces copper.py, bronze.py, silver.py (layer scripts deleted after this).
Salary parsing utilities live here because derive_ashby() needs them at bronze time.
Classification functions (department, seniority, etc.) live in classify.ipynb.
"""

import html
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup


# ── Copper schema ────────────────────────────────────────────────────────────

_COPPER_SCHEMA = """
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


def open_copper(board: str, base_dir: str = "copper") -> sqlite3.Connection:
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(base_dir) / f"{board}.db")
    conn = sqlite3.connect(path)
    conn.executescript(_COPPER_SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def get_copper(conn: sqlite3.Connection, url: str, source_date: str) -> Optional[str]:
    row = conn.execute(
        "SELECT content FROM snapshots WHERE url=? AND source_date=?",
        (url, source_date),
    ).fetchone()
    return row["content"] if row else None


def store_copper(conn: sqlite3.Connection, *, url: str, http_status: int,
                 content: str, source_date: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO snapshots (url, http_status, content, source_date, fetched_at)
           VALUES (?,?,?,?,?)""",
        (url, http_status, content, source_date,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


# ── Bronze schema ────────────────────────────────────────────────────────────

_BRONZE_SCHEMA = """
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


def open_bronze(board: str, base_dir: str = "bronze") -> sqlite3.Connection:
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(base_dir) / f"{board}.db")
    conn = sqlite3.connect(path)
    conn.executescript(_BRONZE_SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def store_bronze(conn: sqlite3.Connection, *, company: str, board: str, job_id: str,
                 page_type: str, source_date: str, original_url: Optional[str] = None,
                 http_status: int, content: str, copper_id: Optional[int] = None) -> None:
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


# ── Bronze URL patterns ──────────────────────────────────────────────────────

_ASHBY_JOB_URL_RE = re.compile(
    r"jobs\.ashbyhq\.com/([^/]+)"
    r"/([0-9a-zA-Z][0-9a-zA-Z\-]+)"
    r"(/application)?$",
)
_ASHBY_API_BOARD_RE = re.compile(
    r"api\.ashbyhq\.com/posting-api/job-board/([^/]+)$"
)
_ASHBY_INDIVIDUAL_JOB_RE = re.compile(
    r"api\.ashbyhq\.com/posting-api/job-board/[^/]+/job/"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
)
_GH_API_RE = re.compile(r"boards-api\.greenhouse\.io/v1/boards/([^/]+)/jobs")


def derive_ashby(copper_conn: sqlite3.Connection, bronze_conn: sqlite3.Connection,
                 company: str) -> int:
    rows = copper_conn.execute(
        "SELECT id, url, content, source_date FROM snapshots "
        "WHERE url LIKE ? OR url LIKE ? OR url LIKE ?",
        (f"%jobs.ashbyhq.com/{company}/%",
         f"%api.ashbyhq.com/posting-api/job-board/{company}%",
         f"%api.ashbyhq.com/posting-api/job-board/{company}/job/%"),
    ).fetchall()

    count = 0
    for row in rows:
        url = row["url"]
        content = row["content"] or ""

        if _ASHBY_API_BOARD_RE.search(url):
            try:
                jobs = json.loads(content).get("jobs", [])
            except Exception:
                continue
            for job in jobs:
                jid = str(job.get("id", ""))
                if not jid:
                    continue
                store_bronze(bronze_conn, company=company, board="ashby", job_id=jid,
                             page_type="api_board", source_date=row["source_date"],
                             original_url=url, http_status=200,
                             content=json.dumps(job), copper_id=row["id"])
                count += 1
            continue

        m_ind = _ASHBY_INDIVIDUAL_JOB_RE.search(url)
        if m_ind:
            job_id = m_ind.group(1)
            store_bronze(bronze_conn, company=company, board="ashby", job_id=job_id,
                         page_type="api_board", source_date=row["source_date"],
                         original_url=url, http_status=200, content=content,
                         copper_id=row["id"])
            count += 1
            continue

        m = _ASHBY_JOB_URL_RE.search(url)
        if not m:
            continue
        job_id = m.group(2)
        is_application = bool(m.group(3))
        page_type = "application" if is_application else "job_page"

        if is_application and content:
            jld = parse_json_ld_job_posting(content)
            content = json.dumps(jld) if jld else content

        store_bronze(bronze_conn, company=company, board="ashby", job_id=job_id,
                     page_type=page_type, source_date=row["source_date"],
                     original_url=url, http_status=200, content=content,
                     copper_id=row["id"])
        count += 1
    return count


def derive_greenhouse(copper_conn: sqlite3.Connection, bronze_conn: sqlite3.Connection,
                      company: str) -> int:
    rows = copper_conn.execute(
        "SELECT id, url, content, source_date FROM snapshots WHERE url LIKE ?",
        (f"%greenhouse.io%boards/{company}%",),
    ).fetchall()

    count = 0
    for row in rows:
        if not _GH_API_RE.search(row["url"]):
            continue
        try:
            jobs = json.loads(row["content"] or "{}").get("jobs", [])
        except Exception:
            continue
        for job in jobs:
            jid = str(job.get("id", ""))
            if not jid:
                continue
            store_bronze(bronze_conn, company=company, board="greenhouse", job_id=jid,
                         page_type="api_board", source_date=row["source_date"],
                         original_url=row["url"], http_status=200,
                         content=json.dumps(job), copper_id=row["id"])
            count += 1
    return count


def derive_adhoc(copper_conn: sqlite3.Connection, bronze_conn: sqlite3.Connection,
                 company: str, job_id: str, url: str = "") -> int:
    if url:
        rows = copper_conn.execute(
            "SELECT id, url, content, source_date FROM snapshots "
            "WHERE url=? ORDER BY source_date",
            (url,),
        ).fetchall()
    else:
        rows = copper_conn.execute(
            "SELECT id, url, content, source_date FROM snapshots "
            "WHERE url LIKE ? ORDER BY source_date",
            (f"%{job_id}%",),
        ).fetchall()
    count = 0
    for row in rows:
        store_bronze(bronze_conn, company=company, board="adhoc", job_id=job_id,
                     page_type="job_page", source_date=row["source_date"],
                     original_url=row["url"], http_status=200,
                     content=row["content"] or "", copper_id=row["id"])
        count += 1
    return count


# ── Silver schema ────────────────────────────────────────────────────────────

_SILVER_SCHEMA = """
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
    yoe            INTEGER,
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


def open_silver(base_dir: str = "silver") -> sqlite3.Connection:
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(base_dir) / "jobs.db")
    conn = sqlite3.connect(path)
    conn.executescript(_SILVER_SCHEMA)
    # Migrate: add yoe column to existing databases that predate this column
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN yoe INTEGER")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.row_factory = sqlite3.Row
    return conn


def upsert_job(conn: sqlite3.Connection, record: dict) -> bool:
    missing = _REQUIRED - set(record)
    if missing:
        conn.execute(
            """INSERT INTO silver_rejected
               (company, job_id, source_date, rejection_reason, raw_content, rejected_at)
               VALUES (?,?,?,?,?,?)""",
            (record.get("company"), record.get("job_id"), record.get("source_date"),
             f"missing required fields: {missing}",
             json.dumps({k: str(v) for k, v in record.items()}, default=str),
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return False

    has_title    = 1 if record.get("title") else 0
    has_salary   = 1 if record.get("salary_min") is not None else 0
    has_location = 1 if record.get("location") else 0
    completeness = has_title + has_salary + has_location
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """INSERT INTO jobs
               (company, board, job_id, source_date, title, location, url,
                department_raw, department, seniority, work_mode, salary_text,
                currency, salary_min, salary_max, salary_unit, description_md, yoe,
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
               yoe=excluded.yoe,
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
         record.get("salary_unit"), record.get("description_md"), record.get("yoe"),
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


# ── Salary parsing (used by derive_ashby / silver ETL) ───────────────────────

DASH_PATTERN = r"(?:–|—|-|–|—|\s+to\s+|\s+and\s+)"
CURRENCY_SYM_1 = r"(?P<sym1>\$|£|€)"
CURRENCY_SYM_2 = r"(?P<sym2>\$|£|€)"
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
UNIT_SUFFIX = r"(?:/\w+)?"

SALARY_RANGE_RE = re.compile(
    rf"{CURRENCY_SYM_1}\s*(?P<min>{NUMBER}){UNIT_SUFFIX}\s*{DASH_PATTERN}\s*"
    rf"(?:{CURRENCY_SYM_2}\s*)?(?P<max>{NUMBER}){UNIT_SUFFIX}"
)


@dataclass
class SalaryParseResult:
    salary_text: str
    currency: Optional[str]
    salary_min: Optional[int]
    salary_max: Optional[int]
    salary_unit: Optional[str]


def normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def looks_like_salary_text(text: str) -> bool:
    if not text:
        return False
    if SALARY_RANGE_RE.search(text):
        return True
    return bool(re.search(r"\b(USD|EUR|GBP|CAD|AUD)\b", text))


COMPENSATION_SENTENCE_RE = re.compile(
    r"Compensation will be[^.]*\$[^.]+\.",
    re.I,
)


def extract_salary_block_from_html(content_html: str) -> Optional[str]:
    if not content_html:
        return None

    soup = BeautifulSoup(html.unescape(content_html), "html.parser")

    plain = normalize_whitespace(soup.get_text(" ", strip=True))
    m = COMPENSATION_SENTENCE_RE.search(plain)
    if m:
        return m.group(0)

    heading_patterns = [
        re.compile(r"\bAnnual Salary\b", re.I),
        re.compile(r"\bSalary\b", re.I),
        re.compile(r"\bCompensation\b", re.I),
        re.compile(r"\bPay\b", re.I),
    ]

    candidates = []
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "strong", "b", "p", "span", "div", "li"]):
        txt = normalize_whitespace(tag.get_text(" ", strip=True))
        if not txt:
            continue
        if any(p.search(txt) for p in heading_patterns):
            candidates.append(tag)

    for tag in candidates:
        parent = tag.parent if tag.parent else tag
        parent_txt = normalize_whitespace(parent.get_text(" ", strip=True)) if parent else ""
        if looks_like_salary_text(parent_txt):
            return parent_txt
        collected = []
        sib = parent
        for _ in range(8):
            sib = sib.find_next_sibling()
            if sib is None:
                break
            t = normalize_whitespace(sib.get_text(" ", strip=True))
            if t:
                collected.append(t)
                joined = " ".join(collected)
                if looks_like_salary_text(joined):
                    return joined

    all_text = normalize_whitespace(soup.get_text(" ", strip=True))
    m = re.search(r"(Annual Salary|Salary|Compensation).{0,400}", all_text, flags=re.I)
    if m:
        window = all_text[m.start() : min(len(all_text), m.start() + 500)]
        if looks_like_salary_text(window):
            return window

    mm = SALARY_RANGE_RE.search(all_text)
    if mm:
        s = max(0, mm.start() - 80)
        e = min(len(all_text), mm.end() + 80)
        return all_text[s:e]

    return None


def parse_salary_text(block: str) -> SalaryParseResult:
    block = normalize_whitespace(html.unescape(block))

    unit = None
    if re.search(r"\bAnnual\b|\bper year\b|\byearly\b", block, re.I):
        unit = "annual"
    elif re.search(r"\bhour\b|\bhourly\b|\bper hour\b|/hr\b", block, re.I):
        unit = "hourly"
    elif re.search(r"\bmonth\b|\bmonthly\b|\bper month\b", block, re.I):
        unit = "monthly"
    elif re.search(r"\bweek\b|\bweekly\b|\bper week\b", block, re.I):
        unit = "weekly"

    currency = None
    m_code = re.search(r"\b(USD|EUR|GBP|CAD|AUD)\b", block)
    if m_code:
        currency = m_code.group(1)

    m = SALARY_RANGE_RE.search(block)
    if m:
        sym = m.group("sym1")
        min_val = int(m.group("min").replace(",", ""))
        max_val = int(m.group("max").replace(",", ""))
        if not currency:
            currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(sym)
        return SalaryParseResult(block, currency, min_val, max_val, unit)

    m2 = re.search(rf"(\d{{1,3}}(?:,\d{{3}})+|\d+)\s*{DASH_PATTERN}\s*(\d{{1,3}}(?:,\d{{3}})+|\d+)\s*(USD|EUR|GBP|CAD|AUD)?",
                   block)
    if m2:
        min_val = int(m2.group(1).replace(",", ""))
        max_val = int(m2.group(2).replace(",", ""))
        if not currency and m2.group(3):
            currency = m2.group(3)
        return SalaryParseResult(block, currency, min_val, max_val, unit)

    m3 = re.search(r"(?P<sym>\$|£|€)\s*(?P<val>\d{1,3}(?:,\d{3})+|\d+)", block)
    if m3:
        val = int(m3.group("val").replace(",", ""))
        if not currency:
            currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(m3.group("sym"))
        return SalaryParseResult(block, currency, val, val, unit)

    return SalaryParseResult(block, currency, None, None, unit)


def parse_json_ld_job_posting(html_content: str) -> Optional[dict]:
    """Extract salary and metadata from an Ashby /application page."""
    soup = BeautifulSoup(html_content, "html.parser")
    result: dict = {}

    description_html: str = ""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                continue
            result["title"] = item.get("title", "")
            loc = item.get("jobLocation")
            if isinstance(loc, dict):
                addr = loc.get("address", {})
                result["location"] = (
                    addr.get("addressLocality") or addr.get("addressRegion") or ""
                    if isinstance(addr, dict) else ""
                )
            base = item.get("baseSalary", {})
            if isinstance(base, dict):
                val = base.get("value", {})
                if isinstance(val, dict):
                    mn = val.get("minValue")
                    mx = val.get("maxValue")
                    if mn is not None:
                        result["salary_min"] = float(mn)
                        result["salary_max"] = float(mx) if mx is not None else float(mn)
                        result["salary_unit"] = val.get("unitText", "").lower()
                        result["salary_text"] = (
                            f"${result['salary_min']:,.0f}–${result['salary_max']:,.0f} "
                            f"{base.get('currency', '')}"
                        )
                if base.get("currency"):
                    result["currency"] = base["currency"]
            description_html = item.get("description", "")
            break

    if not result.get("salary_min"):
        for html_fragment in [description_html, html_content]:
            if not html_fragment:
                continue
            sal_block = extract_salary_block_from_html(html_fragment)
            if sal_block:
                parsed = parse_salary_text(sal_block)
                if parsed.salary_min:
                    result["salary_min"] = parsed.salary_min
                    result["salary_max"] = parsed.salary_max
                    result["currency"] = parsed.currency or ""
                    result["salary_unit"] = parsed.salary_unit or ""
                    result["salary_text"] = parsed.salary_text or ""
                    break

    return result if (result.get("title") or result.get("salary_min")) else None
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_db.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: add db.py — consolidated DB utilities and salary parsing"
```

---

### Task 2: Update scraper imports from `copper`/`classify` to `db`

Both `scrape_ashby.py` and `scrape_greenhouse.py` import from `classify` (unused dead code) and from `copper` (inline). `scrape_wayback.py` imports `copper` at the top level. All three need to import from `db` instead.

**Files:**
- Modify: `scrape_ashby.py`
- Modify: `scrape_greenhouse.py`
- Modify: `scrape_wayback.py`

**Step 1: Update `scrape_ashby.py`**

Remove the `from classify import ...` block entirely (those functions are unused in this file). Replace the inline `import copper as _copper` with `import db as _db`. Change `_copper.open_db("ashby")` → `_db.open_copper("ashby")` and `_copper.store(...)` → `_db.store_copper(...)`.

Also remove unused imports: `html`, `re`, `sqlite3`, `from typing import Any, Dict, List`, `SalaryParseResult`, `html2text` (unused in main path).

Result — the only imports needed:
```python
import argparse
import logging
import db
import requests
from datetime import date
```

And `scrape_all_jobs`:
```python
def scrape_all_jobs(company: str) -> tuple[list[dict], str]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
    log.info("Fetching all jobs from Ashby API for %s ...", company)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    source_date = date.today().strftime("%Y%m%d")
    copper_db = db.open_copper("ashby")
    db.store_copper(copper_db, url=url, http_status=resp.status_code,
                    content=resp.text, source_date=source_date)
    jobs = resp.json().get("jobs", [])
    log.info("Fetched %d jobs", len(jobs))
    return jobs, source_date
```

**Step 2: Update `scrape_greenhouse.py`**

Same pattern: remove `from classify import ...` block (unused). Replace inline `import copper as _copper` with `import db as _db`. Remove unused imports.

Result — only imports needed:
```python
import argparse
import logging
import db
import requests
from datetime import date
```

And `scrape_all_jobs`:
```python
def scrape_all_jobs(company: str) -> tuple[list[dict], str]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
    log.info("Fetching all jobs from Greenhouse API for %s ...", company)
    resp = requests.get(url, params={"content": "true"}, timeout=30)
    resp.raise_for_status()
    source_date = date.today().strftime("%Y%m%d")
    copper_db = db.open_copper("greenhouse")
    db.store_copper(copper_db, url=url, http_status=resp.status_code,
                    content=resp.text, source_date=source_date)
    jobs = resp.json().get("jobs", [])
    log.info("Fetched %d jobs", len(jobs))
    return jobs, source_date
```

**Step 3: Update `scrape_wayback.py`**

Replace `import copper` with `import db`. Then replace all `copper.open_db(board)` → `db.open_copper(board)` and `copper.store(...)` → `db.store_copper(...)` throughout the file.

**Step 4: Verify scrapers import correctly**

```bash
python -c "import scrape_ashby; import scrape_greenhouse; import scrape_wayback; print('OK')"
```

Expected: `OK` (no import errors)

**Step 5: Commit**

```bash
git add scrape_ashby.py scrape_greenhouse.py scrape_wayback.py
git commit -m "refactor: update scrapers to import from db instead of copper/classify"
```

---

### Task 3: Create `classify.ipynb`

Move all classification functions from `classify.py` into a notebook. Add `extract_yoe()`. This notebook has no imports of copper/bronze/silver — it is standalone. Other notebooks load it with `%run classify.ipynb`.

**Files:**
- Create: `classify.ipynb`
- Modify: `tests/conftest.py` (new file — generates classify.py from notebook so existing tests keep working)
- Modify: `.gitignore` (add `classify.py`)

**Step 1: Create `tests/conftest.py`**

This generates `classify.py` from the notebook before pytest runs, so `tests/test_classify.py` can `from classify import ...` as normal. The generated file is a build artifact, not source.

```python
# tests/conftest.py
import subprocess
import sys
from pathlib import Path

def pytest_configure(config):
    """Generate classify.py from classify.ipynb before running tests."""
    root = Path(__file__).parent.parent
    nb = root / "classify.ipynb"
    out = root / "classify.py"
    if nb.exists():
        subprocess.run(
            [sys.executable, "-m", "nbconvert", "--to", "script",
             str(nb), "--output", str(out.stem), "--output-dir", str(root)],
            check=True,
            capture_output=True,
        )
```

**Step 2: Add `classify.py` to `.gitignore`**

Open `.gitignore` and add `classify.py` on a new line after the existing entries.

**Step 3: Create `classify.ipynb`**

Create a new notebook with these cells (use `jupyter nbconvert --to notebook` or create JSON directly):

Cell 1 — markdown header:
```markdown
# Classification Utilities

Helper functions for department, seniority, work mode, and experience classification.
Load into any notebook with `%run classify.ipynb`.
```

Cell 2 — imports and constants:
```python
import re
from typing import Optional

# Approximate exchange rates as of Feb 2026
TO_USD = {
    "USD": 1.0,
    "EUR": 1.05,
    "GBP": 1.27,
    "CAD": 0.72,
    "AUD": 0.64,
}

# Anthropic's 16 departments — ordered most-specific-first, first match wins
DEPARTMENT_RULES = [
    ("Technical Program Management",
     r"technical program manage|TPM\b"),
    ("Safeguards (Trust & Safety)",
     r"threat (investigat|collect)|account abuse|CBRN"
     r"|safeguards analyst|safeguards.{0,15}(infrastructure|data infra)"
     r"|biological safety|red team engineer.{0,10}safeguards"
     r"|product policy manager|policy manager.{0,20}(harm|cyber|frontier)"
     r"|offensive security research.{0,10}safeguards|scaled abuse"),
    ("AI Public Policy & Societal Impacts",
     r"policy|external affairs|geopolitics|national security"
     r"|societal impacts?|research economist"),
    ("Communications",
     r"communications (manager|lead|director)|head of.{0,15}communications"),
    ("Compute",
     r"data center|compute (capacity|efficiency|platform)"
     r"|transaction manager|research compute|capacity.{0,10}(delivery|efficiency)"),
    ("Data Science & Analytics",
     r"analytics data|data (science|analytics)|analytics.{0,5}engineering"),
    ("Finance",
     r"finance|accounti?n?g|(?<!\w)tax(?!onom)|payroll|revenue (account|system)"
     r"|deal desk|order management|corporate (development|finance)"
     r"|FP&A|treasury|SOX|billing|government incentive|transfer pricing"),
    ("Legal",
     r"counsel|(?<!\w)legal|ediscovery|contracts manager"
     r"|compliance (oversight|lead)|trade compliance|IP legal"),
    ("People",
     r"recruit|immigration|administrative business partner"
     r"|internal mobility|people (program|senior)|(?<!\w)HR(?!\w)"
     r"|human resources|onboarding.{0,10}lead"),
    ("Marketing & Brand",
     r"marketing|(?<!\w)brand(?!\w)|video (director|producer)"
     r"|social media|event designer|presentation design"
     r"|copy and content|developer community|community lead|GTM narrative"),
    ("Sales",
     r"account (executive|coordinator)|solutions? architect"
     r"|customer success|business development|(?<!\w)[BS]DR(?!\w)"
     r"|forward deployed|applied AI|partner (sales|solutions|operations)"
     r"|evangelist|incentive compensation|reseller|cosell"
     r"|GTM (strategy|systems|onboarding)|nonprofit account"
     r"|partner.{0,5}(lead|manager).{0,15}(cloud|system|global|reseller)"
     r"|head of.{0,15}(GTM|solution)"),
    ("Security",
     r"application security|IT (support|systems|engineering|audiovisual)"
     r"|platform.{0,10}security|security (engineer|software|GRC|risk|technology)"
     r"|cloud security|detection.{0,5}response|insider risk"
     r"|offensive security(?!.*safeguards)|protective intelligence"
     r"|campus security|access management|customer trust|GRC"
     r"|audiovisual|security development|vulnerability"),
    ("Product Management, Support, & Operations",
     r"product (manager|lead|support|operations|management)"
     r"|developer relations|support operations|research product manager"),
    ("AI Research & Engineering",
     r"research (engineer|scientist|manager)|machine learning|(?<!\w)ML(?!\w)"
     r"|alignment|interpretability|pre-?training|post.?training"
     r"|reinforcement learning|frontier red team|kernel engineer"
     r"|performance engineer|discovery|safety fellow|security fellow"
     r"|reward model|data operations manager|AI observability"
     r"|developer education|education (labs|platform)|certification content"
     r"|training content|human data|encoding librar"),
    ("Software Engineering - Infrastructure",
     r"inference|(?<!\w)systems(?!\w)|sandboxing|networking"
     r"|continuous integration|observability|developer productivity"
     r"|data infrastructure|database|AI reliability|autonomous agent infra"
     r"|accelerator platform"),
    ("Engineering & Design - Product",
     r"software engineer|engineering manager|design engineer"
     r"|prompt engineer|model quality|full.?stack"),
]

SENIORITY_RULES = [
    ("Intern / Fellow",   r"\b(intern|fellow|apprentice)\b"),
    ("Junior",            r"\b(junior|jr\.?|entry[ -]level|associate)\b"),
    ("Senior",            r"\b(senior|sr\.?)\b"),
    ("Staff / Principal", r"\b(staff|principal)\b"),
    ("Lead",              r"\b(lead\b|tech lead)\b"),
    ("Manager",           r"\b(manager|management)\b"),
    ("Director+",         r"\b(director|head of|VP|vice president|chief|president|C-suite)\b"),
]

SENIORITY_ORDER = [
    "Intern / Fellow", "Junior", "Mid-Level", "Senior",
    "Staff / Principal", "Lead", "Manager", "Director+",
]

NORMALIZED_DEPARTMENT_RULES = [
    ("Research",              r"\bresearch\b"),
    ("Manufacturing",         r"\bmanufactur"),
    ("Design",                r"\bdesign\b"),
    ("Engineering",           r"\bengineering\b|\bsoftware\b|\bhardware\b|\binfrastructure\b"),
    ("Product",               r"\bproduct\b"),
    ("People",                r"\bpeople\b|\brecruit|\bHR\b|\bhuman resources\b"),
    ("Finance",               r"\bfinance\b|\baccounting\b"),
    ("Legal",                 r"\blegal\b|\bcounsel\b"),
    ("Sales & BD",            r"\bsales\b|\bbusiness development\b|\b[BS]DR\b|\bBD\b|\bGTM\b|\bgo.to.market\b"),
    ("Marketing & Comms",     r"\bmarketing\b|\bbrand\b|\bcommunication"),
    ("Public Policy",         r"\bpolicy\b|\bpublic affairs\b|\bsocietal impacts?\b|\bgeopolitics\b"),
    ("Security & Compliance", r"\bsecurity\b|\bsafeguard|\bcompliance\b"),
    ("IT",                    r"\bIT\b|\binformation technology\b"),
    ("Operations",            r"\boperation|\bcompute\b|\bdata center\b|\bprocurement\b|\breal estate\b|\bsupply chain\b"),
    ("Other",                 r".*"),
]
```

Cell 3 — classification functions:
```python
def normalize_department(department_raw: str) -> str:
    if not isinstance(department_raw, str) or not department_raw:
        return "Other"
    for bucket, pattern in NORMALIZED_DEPARTMENT_RULES:
        if re.search(pattern, department_raw, re.I):
            return bucket
    return "Other"


def classify_department(title: str) -> str:
    if not isinstance(title, str):
        return "Other"
    for dept, pattern in DEPARTMENT_RULES:
        if re.search(pattern, title, re.I):
            return dept
    return "Other"


def classify_seniority(title: str) -> str:
    if not isinstance(title, str):
        return "Mid-Level"
    for level, pattern in SENIORITY_RULES:
        if re.search(pattern, title, re.I):
            return level
    return "Mid-Level"


def classify_work_mode(location: str) -> str:
    if not isinstance(location, str):
        return "Unknown"
    if "remote" in location.lower():
        return "Remote-Friendly"
    return "Office-Only"


def add_classifications(df):
    df["department"] = df["title"].apply(classify_department)
    df["seniority"] = df["title"].apply(classify_seniority)
    df["work_mode"] = df["location"].apply(classify_work_mode)
    return df


def add_usd_salary(df):
    df["rate"] = df["currency"].map(TO_USD)
    df["min_usd"] = df["salary_min"] * df["rate"]
    df["max_usd"] = df["salary_max"] * df["rate"]
    df["mid_usd"] = (df["min_usd"] + df["max_usd"]) / 2
    return df
```

Cell 4 — `extract_yoe` (new function):
```python
_YOE_RE = re.compile(
    r"(\d+)\+?\s*(?:–|-|to)\s*(\d+)\s+years?"   # "3-5 years" or "3–5 years"
    r"|(\d+)\+\s*years?"                          # "5+ years"
    r"|(\d+)\s+years?\s+of\s+experience",          # "5 years of experience"
    re.I,
)

def extract_yoe(text: str) -> Optional[int]:
    """Return minimum years of experience mentioned in text, or None."""
    if not text:
        return None
    m = _YOE_RE.search(text)
    if not m:
        return None
    # Return the smallest number in the match (minimum of range or single value)
    groups = [int(g) for g in m.groups() if g is not None]
    return min(groups) if groups else None
```

**Step 4: Run existing classify tests to verify they still pass**

```bash
pytest tests/test_classify.py -v
```

Expected: All tests PASS (conftest.py generates classify.py from the notebook before the suite runs).

**Step 5: Commit**

```bash
git add classify.ipynb tests/conftest.py .gitignore
git commit -m "feat: add classify.ipynb with all classification functions and extract_yoe"
```

---

### Task 4: Update `silver.ipynb`

Replace `import bronze, silver` with `import db`. Replace `from classify import ...` with `%run classify.ipynb`. Add `yoe` extraction using `extract_yoe()`. Keep `merge_to_silver` logic intact.

**Files:**
- Modify: `silver.ipynb`

**Step 1: Edit cell `374f7517` (imports + bronze/silver open)**

Replace:
```python
import json, bronze, silver
from collections import defaultdict

bronze_db = bronze.open_db(BOARD)
silver_db = silver.open_db()
```

With:
```python
import json, db
from collections import defaultdict

bronze_db = db.open_bronze(BOARD)
silver_db = db.open_silver()
```

**Step 2: Edit cell `0168b576` (classify imports + merge_to_silver)**

Replace the `from classify import ...` block with `%run classify.ipynb`. The `extract_salary_block_from_html`, `parse_salary_text`, `SalaryParseResult` imports should come from `db` instead.

New cell top:
```python
%run classify.ipynb

import html2text
import re
import db as _db

def _md(html_text): ...   # unchanged

def _title_from_html(html_text): ...  # unchanged
```

In `merge_to_silver`, replace:
```python
sal_block = extract_salary_block_from_html(content_html)
parsed = parse_salary_text(sal_block)
```
With:
```python
sal_block = _db.extract_salary_block_from_html(content_html)
parsed = _db.parse_salary_text(sal_block)
```

Do the same for all other `extract_salary_block_from_html` and `parse_salary_text` call sites in `merge_to_silver`. Replace `SalaryParseResult("", None, None, None, None)` with `_db.SalaryParseResult("", None, None, None, None)`.

Also add `yoe` extraction at the end of `merge_to_silver`, before `return record`:
```python
record["yoe"] = extract_yoe(record.get("description_md", "") or "")
```

**Step 3: Edit cell `9fe63d3d` (ETL loop)**

Replace `silver.upsert_job` and `silver.log_run` with `db.upsert_job` and `db.log_run`:
```python
ok = db.upsert_job(silver_db, record)
...
db.log_run(silver_db, COMPANY, BOARD, processed, upserted, rejected)
```

**Step 4: Clear all outputs (the notebook should be committed clean)**

```bash
jupyter nbconvert --ClearOutputPreprocessor.enabled=True --to notebook \
  --inplace silver.ipynb
```

**Step 5: Run silver.ipynb to verify it executes**

```bash
jupyter nbconvert --to notebook --execute \
  --ExecutePreprocessor.kernel_name=job-analysis \
  silver.ipynb --output /tmp/silver_test.ipynb
```

Expected: Exits 0, no errors. Check `/tmp/silver_test.ipynb` for `Processed: N  Upserted: N  Rejected: 0`.

**Step 6: Commit**

```bash
git add silver.ipynb
git commit -m "refactor: silver.ipynb uses db and classify.ipynb; adds yoe column"
```

---

### Task 5: Create `bronze.ipynb`

An execution notebook that calls `db.derive_ashby()` and `db.derive_greenhouse()` for any company/board. Called by `run_pipeline.py` via nbconvert.

**Files:**
- Create: `bronze.ipynb`

**Step 1: Create the notebook with these cells**

Cell 1 — config (injected by run_pipeline.py):
```python
COMPANY = "pinecone"
BOARD = "ashby"
```

Cell 2 — derive:
```python
import db

copper_db = db.open_copper(BOARD)
bronze_db = db.open_bronze(BOARD)

if BOARD == "ashby":
    count = db.derive_ashby(copper_db, bronze_db, COMPANY)
elif BOARD == "greenhouse":
    count = db.derive_greenhouse(copper_db, bronze_db, COMPANY)
else:
    count = 0
    print(f"Unsupported board: {BOARD}")

print(f"Bronze derivation complete: {count} records for {COMPANY}/{BOARD}")
```

Cell 3 — audit summary:
```python
rows = bronze_db.execute(
    "SELECT page_type, COUNT(*) as n FROM snapshots WHERE company=? GROUP BY page_type",
    (COMPANY,)
).fetchall()
for row in rows:
    print(f"  {row['page_type']}: {row['n']} records")
```

**Step 2: Clear outputs**

```bash
jupyter nbconvert --ClearOutputPreprocessor.enabled=True --to notebook \
  --inplace bronze.ipynb
```

**Step 3: Run bronze.ipynb to verify it executes**

```bash
jupyter nbconvert --to notebook --execute \
  --ExecutePreprocessor.kernel_name=job-analysis \
  bronze.ipynb --output /tmp/bronze_test.ipynb
```

Expected: Exits 0. Output shows bronze derivation count.

**Step 4: Commit**

```bash
git add bronze.ipynb
git commit -m "feat: add bronze.ipynb execution notebook"
```

---

### Task 6: Create `copper.ipynb`

A documentation notebook that shows the copper schema and how scrapers write to it. Does not run scrapers — it's a reference and verification tool.

**Files:**
- Create: `copper.ipynb`

**Step 1: Create the notebook with these cells**

Cell 1 — markdown:
```markdown
# Copper Layer

Immutable raw HTTP storage. Scrapers write here; nothing else does.
Schema: `url`, `http_status`, `content`, `source_date`, `fetched_at`.
```

Cell 2 — inspect existing copper DBs:
```python
import db
from pathlib import Path

for board in ["ashby", "greenhouse", "adhoc"]:
    path = Path(f"copper/{board}.db")
    if not path.exists():
        print(f"{board}: no DB yet")
        continue
    conn = db.open_copper(board)
    count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    latest = conn.execute(
        "SELECT source_date FROM snapshots ORDER BY source_date DESC LIMIT 1"
    ).fetchone()
    print(f"{board}: {count} rows, latest source_date={latest[0] if latest else 'N/A'}")
```

**Step 2: Clear outputs and commit**

```bash
jupyter nbconvert --ClearOutputPreprocessor.enabled=True --to notebook \
  --inplace copper.ipynb
git add copper.ipynb
git commit -m "feat: add copper.ipynb documentation notebook"
```

---

### Task 7: Update `run_pipeline.py`

Replace `import copper`/`import bronze` with `import db`. Replace the `run_bronze_derivation()` function with a call to `bronze.ipynb` via nbconvert. Update `scrape_adhoc` to use db. Remove the inline `import bronze as _bronze` for historical check.

**Files:**
- Modify: `run_pipeline.py`

**Step 1: Update `scrape_adhoc`**

Replace:
```python
import copper as _copper, requests
db = _copper.open_db("adhoc")
_copper.store(db, url=url, ...)
```

With:
```python
import db as _db, requests
copper_db = _db.open_copper("adhoc")
_db.store_copper(copper_db, url=url, http_status=resp.status_code,
                 content=resp.text, source_date=source_date)
```

**Step 2: Replace `run_bronze_derivation()` with a notebook invocation**

Delete the entire `run_bronze_derivation()` function. In `main()`, replace the call to `run_bronze_derivation(board, company, job_id)` with a notebook call:

```python
# Bronze derivation via notebook
nb_config = {"COMPANY": company, "BOARD": board}
tmp_bronze = inject_notebook_config("bronze.ipynb", nb_config)
results_pre = [("Bronze ETL", run_notebook(tmp_bronze, "Bronze ETL"))]
```

Add this block immediately after the scraper step and before the silver step.

**Step 3: Remove inline `import bronze as _bronze` from `main()`**

The historical check (lines 233–241) uses `_bronze.open_db(board)`. Replace with:

```python
import db as _db
_bronze_db = _db.open_bronze(board)
has_historical = bool(_bronze_db.execute(
    "SELECT 1 FROM snapshots WHERE company=? LIMIT 1", (company,)
).fetchone())
```

**Step 4: Run pipeline end-to-end to verify**

```bash
python run_pipeline.py https://jobs.ashbyhq.com/Crusoe/2689707b-7314-4246-ac95-1e6466970ba3
```

Expected: Bronze ETL, Silver ETL, and all four gold notebooks complete without error. Pipeline summary shows the target job with salary.

**Step 5: Commit**

```bash
git add run_pipeline.py
git commit -m "refactor: run_pipeline uses db and invokes bronze.ipynb via nbconvert"
```

---

### Task 8: Delete old layer scripts and update `.gitignore`

Only after verifying the full pipeline runs cleanly.

**Files:**
- Delete: `copper.py`, `bronze.py`, `silver.py`, `classify.py`
- Modify: `.gitignore`

**Step 1: Verify nothing imports the old files**

```bash
grep -r "import copper\b\|import bronze\b\|import silver\b\|from classify\b" \
  --include="*.py" --include="*.ipynb" . \
  | grep -v ".gitignore" | grep -v "test_classify" | grep -v conftest
```

Expected: No output (or only false positives in docs/plans). If anything appears, fix it before deleting.

**Step 2: Delete old layer scripts**

```bash
rm copper.py bronze.py silver.py classify.py
```

**Step 3: Update `.gitignore`**

Add `classify.py` to `.gitignore` (it is now a generated test artifact, not source). The current `.gitignore` already has `*.csv`, `copper/`, `bronze/`, `silver/`. Add:

```
classify.py
```

**Step 4: Verify tests still pass after deletion**

```bash
pytest tests/ -v
```

Expected: All tests pass. `conftest.py` regenerates `classify.py` from the notebook before the suite.

**Step 5: Commit**

```bash
git add -u  # stages deletions
git add .gitignore
git commit -m "refactor: delete layer scripts; classify.py is now a generated test artifact"
```

---

### Task 9: End-to-end verification

Run the full pipeline for a real company to confirm everything works together.

**Step 1: Run pipeline**

```bash
python run_pipeline.py https://jobs.ashbyhq.com/Crusoe/2689707b-7314-4246-ac95-1e6466970ba3
```

Expected output:
- `Bronze ETL: ✓`
- `Silver ETL: ✓`
- `Salary Analysis: ✓`
- `NLP Analysis: ✓`
- `Historical Analysis: ✓`
- `Role Gap Analysis: ✓`
- Pipeline summary shows `$216,150 – $262,000` salary for the target Crusoe job

**Step 2: Verify `yoe` column populated**

```bash
python -c "
import db
conn = db.open_silver()
rows = conn.execute('SELECT job_id, title, yoe FROM jobs WHERE company=\"crusoe\" AND yoe IS NOT NULL LIMIT 5').fetchall()
for r in rows:
    print(dict(r))
"
```

Expected: Some rows with integer `yoe` values.

**Step 3: Verify tests**

```bash
pytest tests/ -v
```

Expected: All tests pass.
