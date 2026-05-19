"""
db.py — Consolidated DB utilities and salary parsing for the job analysis pipeline.

Replaces copper.py, bronze.py, silver.py as a single importable module.
Includes salary parsing moved from classify.py (needed by derive_ashby).

Sections:
  1. Salary parsing (SalaryParseResult, parse_salary_text, etc.)
  2. Copper layer  (open_copper, get_copper, store_copper)
  3. Bronze layer  (open_bronze, store_bronze, derive_ashby, derive_greenhouse, derive_adhoc)
  4. Silver layer  (open_silver, upsert_job, log_run)
"""

import html
import json as _json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

# ===========================================================================
# 1. Salary parsing
# ===========================================================================

# Compile once at import time.
DASH_PATTERN = r"(?:–|—|-|\s+to\s+|\s+and\s+)"
CURRENCY_SYM_1 = r"(?P<sym1>\$|£|€)"
CURRENCY_SYM_2 = r"(?P<sym2>\$|£|€)"
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
UNIT_SUFFIX = r"(?:/\w+)?"  # optional e.g. /hr, /yr

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
    salary_unit: Optional[str]  # annual, hourly, monthly, etc.


def normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def looks_like_salary_text(text: str) -> bool:
    if not text:
        return False
    if SALARY_RANGE_RE.search(text):
        return True
    # Some posts mention currency code even if the range is formatted differently
    return bool(re.search(r"\b(USD|EUR|GBP|CAD|AUD)\b", text))


COMPENSATION_SENTENCE_RE = re.compile(
    r"Compensation will be[^.]*\$[^.]+\.",
    re.I,
)


def extract_salary_block_from_html(content_html: str) -> Optional[str]:
    """
    Find a salary-ish block from the job HTML content. Returns normalized text or None.
    """
    if not content_html:
        return None

    soup = BeautifulSoup(html.unescape(content_html), "html.parser")

    # Fast path: match "Compensation will be paid in the range of $X - $Y" directly
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

        # look at a few next siblings
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

    # fallback: scan whole text
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
    if not block:
        return SalaryParseResult("", None, None, None, None)
    block = normalize_whitespace(html.unescape(block))

    # unit
    unit = None
    if re.search(r"\bAnnual\b|\bper year\b|\byearly\b", block, re.I):
        unit = "annual"
    elif re.search(r"\bhour\b|\bhourly\b|\bper hour\b|/hr\b", block, re.I):
        unit = "hourly"
    elif re.search(r"\bmonth\b|\bmonthly\b|\bper month\b", block, re.I):
        unit = "monthly"
    elif re.search(r"\bweek\b|\bweekly\b|\bper week\b", block, re.I):
        unit = "weekly"

    # currency code
    currency = None
    m_code = re.search(r"\b(USD|EUR|GBP|CAD|AUD)\b", block)
    if m_code:
        currency = m_code.group(1)

    # numeric range
    m = SALARY_RANGE_RE.search(block)
    if m:
        sym = m.group("sym1")
        min_val = int(m.group("min").replace(",", ""))
        max_val = int(m.group("max").replace(",", ""))
        if not currency:
            currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(sym)
        if min_val > max_val:
            min_val, max_val = max_val, min_val
        return SalaryParseResult(block, currency, min_val, max_val, unit)

    # secondary pattern: "131,040–165,000 USD"
    m2 = re.search(rf"(\d{{1,3}}(?:,\d{{3}})+|\d+)\s*{DASH_PATTERN}\s*(\d{{1,3}}(?:,\d{{3}})+|\d+)\s*(USD|EUR|GBP|CAD|AUD)?",
                   block)
    if m2:
        min_val = int(m2.group(1).replace(",", ""))
        max_val = int(m2.group(2).replace(",", ""))
        if not currency and m2.group(3):
            currency = m2.group(3)
        if min_val > max_val:
            min_val, max_val = max_val, min_val
        return SalaryParseResult(block, currency, min_val, max_val, unit)

    # single amount fallback: "$1,415/per week"
    m3 = re.search(r"(?P<sym>\$|£|€)\s*(?P<val>\d{1,3}(?:,\d{3})+|\d+)", block)
    if m3:
        val = int(m3.group("val").replace(",", ""))
        if not currency:
            currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(m3.group("sym"))
        return SalaryParseResult(block, currency, val, val, unit)

    return SalaryParseResult(block, currency, None, None, unit)


def parse_json_ld_job_posting(html_content: str) -> Optional[dict]:
    """Extract salary and metadata from an Ashby /application page.

    Tries JSON-LD baseSalary first; falls back to HTML salary block extraction.
    Returns a dict with salary_min, salary_max, currency, salary_unit, salary_text,
    title, and location — or None if nothing useful is found.
    """
    if not html_content:
        return None
    soup = BeautifulSoup(html_content, "html.parser")
    result: dict = {}

    description_html: str = ""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = _json.loads(script.string or "")
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
            # Capture description HTML for salary fallback (Ashby embeds HTML here)
            description_html = item.get("description", "")
            break  # first JobPosting wins

    # Fallback: salary is in the JSON-LD description field (Ashby embeds HTML there)
    # or in the visible HTML body. description_html is tried first because get_text()
    # on the full page won't see content inside <script> tags.
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


# ===========================================================================
# 2. Copper layer
# ===========================================================================

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
    """Open (or create) the copper DB for a given board."""
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(base_dir) / f"{board}.db")
    conn = sqlite3.connect(path)
    conn.executescript(_COPPER_SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def get_copper(conn: sqlite3.Connection, url: str, source_date: str) -> Optional[str]:
    """Return cached content from copper, or None if not present."""
    row = conn.execute(
        "SELECT content FROM snapshots WHERE url=? AND source_date=?",
        (url, source_date),
    ).fetchone()
    return row["content"] if row else None


def store_copper(conn: sqlite3.Connection, *, url: str, http_status: int,
                 content: str, source_date: str) -> None:
    """Insert a copper snapshot. Silently ignored if (url, source_date) already exists."""
    conn.execute(
        """INSERT OR IGNORE INTO snapshots (url, http_status, content, source_date, fetched_at)
           VALUES (?,?,?,?,?)""",
        (url, http_status, content, source_date,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


# ===========================================================================
# 3. Bronze layer
# ===========================================================================

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
    """Open (or create) the bronze DB for a given board.

    board must be one of: ashby, greenhouse, adhoc.
    DB is created at {base_dir}/{board}.db.
    """
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(base_dir) / f"{board}.db")
    conn = sqlite3.connect(path)
    conn.executescript(_BRONZE_SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def store_bronze(conn: sqlite3.Connection, *, company: str, board: str, job_id: str,
                 page_type: str, source_date: str, original_url: Optional[str] = None,
                 http_status: int, content: str, copper_id: Optional[int] = None) -> None:
    """Insert a bronze record. Silently ignored if (company, job_id, source_date, page_type) already exists."""
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


def derive_ashby(copper_conn: sqlite3.Connection, bronze_conn: sqlite3.Connection,
                 company: str) -> int:
    """Derive per-job bronze records from copper for an Ashby company."""
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
                store_bronze(bronze_conn, company=company, board="ashby", job_id=jid,
                             page_type="api_board", source_date=row["source_date"],
                             original_url=url, http_status=200,
                             content=_json.dumps(job), copper_id=row["id"])
                count += 1
            continue

        # Individual job API response (wayback fallback path)
        m_ind = _ASHBY_INDIVIDUAL_JOB_RE.search(url)
        if m_ind:
            job_id = m_ind.group(1)
            store_bronze(bronze_conn, company=company, board="ashby", job_id=job_id,
                         page_type="api_board", source_date=row["source_date"],
                         original_url=url, http_status=200, content=content,
                         copper_id=row["id"])
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
            jld = parse_json_ld_job_posting(content)
            content = _json.dumps(jld) if jld else content

        store_bronze(bronze_conn, company=company, board="ashby", job_id=job_id,
                     page_type=page_type, source_date=row["source_date"],
                     original_url=url, http_status=200, content=content,
                     copper_id=row["id"])
        count += 1
    return count


_GH_API_RE = re.compile(r"boards-api\.greenhouse\.io/v1/boards/([^/]+)/jobs")


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
            store_bronze(bronze_conn, company=company, board="greenhouse", job_id=jid,
                         page_type="api_board", source_date=row["source_date"],
                         original_url=row["url"], http_status=200,
                         content=_json.dumps(job), copper_id=row["id"])
            count += 1
    return count


def derive_adhoc(copper_conn: sqlite3.Connection, bronze_conn: sqlite3.Connection,
                 company: str, job_id: str, url: str = "") -> int:
    """Derive bronze records for an adhoc job. If url is provided, matches exactly; otherwise falls back to job_id substring match."""
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


# ===========================================================================
# 4. Silver layer
# ===========================================================================

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
    has_title      INTEGER DEFAULT 0,
    has_salary     INTEGER DEFAULT 0,
    has_location   INTEGER DEFAULT 0,
    completeness   INTEGER DEFAULT 0,
    bronze_id      INTEGER,
    processed_at   TEXT    NOT NULL,
    fetched_at     TEXT,
    yoe            INTEGER,
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
    """Open (or create) the silver jobs DB."""
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(base_dir) / "jobs.db")
    conn = sqlite3.connect(path)
    conn.executescript(_SILVER_SCHEMA)
    conn.row_factory = sqlite3.Row
    # Add yoe column to existing DBs that predate the column
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN yoe INTEGER")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
    return conn


def upsert_job(conn: sqlite3.Connection, record: dict) -> bool:
    """Upsert one job record. Returns True on success, False on rejection."""
    missing = _REQUIRED - set(record)
    if missing:
        conn.execute(
            """INSERT INTO silver_rejected
               (company, job_id, source_date, rejection_reason, raw_content, rejected_at)
               VALUES (?,?,?,?,?,?)""",
            (record.get("company"), record.get("job_id"), record.get("source_date"),
             f"missing required fields: {missing}",
             _json.dumps({k: str(v) for k, v in record.items()}, default=str),
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
                currency, salary_min, salary_max, salary_unit, description_md,
                has_title, has_salary, has_location, completeness,
                bronze_id, processed_at, fetched_at, yoe)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
               processed_at=excluded.processed_at,
               yoe=excluded.yoe""",
        (record.get("company"), record.get("board"), record.get("job_id"),
         record.get("source_date"), record.get("title"), record.get("location"),
         record.get("url"), record.get("department_raw"), record.get("department"),
         record.get("seniority"), record.get("work_mode"), record.get("salary_text"),
         record.get("currency"), record.get("salary_min"), record.get("salary_max"),
         record.get("salary_unit"), record.get("description_md"),
         has_title, has_salary, has_location, completeness,
         record.get("bronze_id"), now, record.get("fetched_at"),
         record.get("yoe")),
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
