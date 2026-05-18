# Medallion Architecture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor the job analysis pipeline into four layers — Copper (raw fetch), Bronze (schema), Silver (classify), Gold (analyze) — so that parsing bugs can be fixed by reprocessing existing data without re-scraping.

**Architecture:** Scrapers write raw HTTP responses to Copper only. Bronze derives structured per-job records from Copper. Silver applies `classify.py` and validates, writing to a unified `silver/jobs.db`. Gold notebooks query Silver via `pd.read_sql`. Each layer is independently re-runnable.

**Tech Stack:** Python 3.11, SQLite (via stdlib `sqlite3`), pandas `pd.read_sql`, Jupyter `nbformat`, pytest

**Design doc:** `docs/plans/2026-05-18-medallion-architecture-design.md`

---

## Task 1: Create `copper.py`

**Files:**
- Create: `copper.py`
- Create: `tests/test_copper.py`

**Step 1: Write the failing tests**

```python
# tests/test_copper.py
import pytest
import copper

@pytest.fixture
def db(tmp_path):
    return copper.open_db("ashby", base_dir=str(tmp_path))

def test_store_and_retrieve(db):
    copper.store(db, url="https://example.com/job/123",
                 http_status=200, content="<html>job</html>",
                 source_date="20250101120000")
    assert copper.get_content(db, "https://example.com/job/123", "20250101120000") == "<html>job</html>"

def test_duplicate_insert_ignored(db):
    copper.store(db, url="https://x.com/1", http_status=200,
                 content="original", source_date="20250101")
    copper.store(db, url="https://x.com/1", http_status=200,
                 content="duplicate", source_date="20250101")
    assert copper.get_content(db, "https://x.com/1", "20250101") == "original"

def test_same_url_different_date(db):
    copper.store(db, url="https://x.com/1", http_status=200,
                 content="v1", source_date="20250101")
    copper.store(db, url="https://x.com/1", http_status=200,
                 content="v2", source_date="20250201")
    assert copper.get_content(db, "https://x.com/1", "20250101") == "v1"
    assert copper.get_content(db, "https://x.com/1", "20250201") == "v2"

def test_missing_returns_none(db):
    assert copper.get_content(db, "https://x.com/missing", "20250101") is None

def test_db_created_in_board_subdir(tmp_path):
    copper.open_db("greenhouse", base_dir=str(tmp_path))
    assert (tmp_path / "greenhouse.db").exists()
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_copper.py -v
```
Expected: `ModuleNotFoundError: No module named 'copper'`

**Step 3: Implement `copper.py`**

```python
"""
Copper layer: raw HTTP response storage — one DB per board.

copper/ashby.db, copper/greenhouse.db, copper/adhoc.db

Immutable. Never modified after insert. Only layer that touches the network.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT    NOT NULL,
    http_status INTEGER,
    content     TEXT,
    source_date TEXT    NOT NULL,
    fetched_at  TEXT    NOT NULL,
    UNIQUE(url, source_date)
);
CREATE INDEX IF NOT EXISTS idx_url ON responses(url);
"""


def open_db(board: str, base_dir: str = "copper") -> sqlite3.Connection:
    Path(base_dir).mkdir(exist_ok=True)
    path = str(Path(base_dir) / f"{board}.db")
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def get_content(conn: sqlite3.Connection, url: str, source_date: str) -> str | None:
    row = conn.execute(
        "SELECT content FROM responses WHERE url=? AND source_date=?",
        (url, source_date),
    ).fetchone()
    return row["content"] if row else None


def store(conn: sqlite3.Connection, *, url: str, http_status: int,
          content: str, source_date: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO responses (url, http_status, content, source_date, fetched_at)
           VALUES (?,?,?,?,?)""",
        (url, http_status, content, source_date,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_copper.py -v
```
Expected: 5 passed

**Step 5: Commit**

```bash
git add copper.py tests/test_copper.py
git commit -m "feat: add copper layer — raw HTTP response storage"
```

---

## Task 2: Update `bronze.py` schema

Rename `wayback_ts` → `source_date`, add `copper_id`. Delete existing `bronze/` directory so the DB is recreated with the new schema.

**Files:**
- Modify: `bronze.py`
- Modify: `tests/test_bronze.py` (create if not exists)

**Step 1: Write failing tests for updated schema**

```python
# tests/test_bronze.py
import pytest
import bronze

@pytest.fixture
def db(tmp_path):
    return bronze.open_db("ashby", base_dir=str(tmp_path))

def test_store_and_retrieve(db):
    bronze.store(db, company="pinecone", board="ashby", job_id="abc-123",
                 source_date="20250101", page_type="job_page",
                 original_url="https://jobs.ashbyhq.com/pinecone/abc-123",
                 wayback_url="", http_status=200,
                 content="<html>job</html>", copper_id=1)
    content = bronze.get_content(db, "pinecone", "abc-123", "20250101", "job_page")
    assert content == "<html>job</html>"

def test_copper_id_stored(db):
    bronze.store(db, company="pinecone", board="ashby", job_id="abc-123",
                 source_date="20250101", page_type="job_page",
                 original_url="https://jobs.ashbyhq.com/pinecone/abc-123",
                 wayback_url="", http_status=200,
                 content="<html/>", copper_id=42)
    row = db.execute("SELECT copper_id FROM snapshots WHERE job_id='abc-123'").fetchone()
    assert row["copper_id"] == 42
```

**Step 2: Run to verify fails**

```bash
pytest tests/test_bronze.py -v
```
Expected: FAIL — `store()` doesn't accept `copper_id`, `get_content` signature mismatch

**Step 3: Update `bronze.py`**

Replace `wayback_ts` with `source_date` and add `copper_id` in `_SCHEMA` and `store()`:

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company      TEXT    NOT NULL,
    board        TEXT    NOT NULL,
    job_id       TEXT    NOT NULL,
    page_type    TEXT    NOT NULL,
    source_date  TEXT    NOT NULL,
    fetched_at   TEXT    NOT NULL,
    original_url TEXT    NOT NULL,
    wayback_url  TEXT    NOT NULL,
    http_status  INTEGER,
    content      TEXT,
    copper_id    INTEGER,
    UNIQUE(company, job_id, source_date, page_type)
);
CREATE INDEX IF NOT EXISTS idx_company_job ON snapshots(company, job_id);
"""
```

Update `store()` to accept `copper_id: int | None = None` and include it in the INSERT.
Update `get_content()` to match the parameter names in the test.

**Step 4: Delete stale bronze DB and run tests**

```bash
rm -rf bronze/
pytest tests/test_bronze.py -v
```
Expected: 2 passed

**Step 5: Commit**

```bash
git add bronze.py tests/test_bronze.py
git commit -m "refactor: update bronze schema — source_date + copper_id"
```

---

## Task 3: Update `scrape_wayback.py` — write to copper

Replace `_fetch_snapshot`'s bronze write with a copper write. `source_date` for Wayback = CDX timestamp (e.g. `"20250315123456"`).

**Files:**
- Modify: `scrape_wayback.py`

**Step 1: Update imports at top of file**

Add `import copper` (already has `import bronze`). Remove the `bronze` import — wayback now writes only to copper.

**Step 2: Replace `_fetch_snapshot`**

```python
def _fetch_snapshot(
    copper_db: "sqlite3.Connection",
    company: str,
    board: str,
    job_id: str,
    ts: str,          # Wayback CDX timestamp — this IS the source_date
    page_type: str,
    orig_url: str,
) -> tuple[str | None, str]:
    """Return (content, wayback_url), reading from copper cache when available."""
    cached = copper.get_content(copper_db, orig_url, ts)
    if cached is not None:
        log.info("    [cached] %s", page_type)
        return cached, f"{WEB_URL}/{ts}id_/{orig_url}"

    for mode in ["id_/", ""]:
        wayback_url = f"{WEB_URL}/{ts}{mode}{orig_url}"
        try:
            resp = SESSION.get(wayback_url, timeout=60)
            log.info("    HTTP %d (%d bytes) [%s]", resp.status_code, len(resp.content), mode or "plain")
            if resp.status_code == 200:
                copper.store(
                    copper_db,
                    url=orig_url,
                    http_status=resp.status_code,
                    content=resp.text,
                    source_date=ts,
                )
                return resp.text, wayback_url
        except Exception as e:
            log.warning("    fetch error: %s", e)
        time.sleep(REQUEST_DELAY)
    return None, ""
```

**Step 3: Update `_scrape_ashby_individual_fallback`**

Replace `db = bronze.open_db("ashby")` with `copper_db = copper.open_db("ashby")`. Pass `copper_db` to `_fetch_snapshot` instead of `db`. Remove all `bronze.store(...)` calls — bronze derivation happens separately.

**Step 4: Update `scrape_api_snapshots`**

In the board-level API fetch loop, store each raw API response to copper:
```python
copper_db = copper.open_db(board)
# after fetching the snapshot successfully:
copper.store(copper_db, url=url, http_status=resp.status_code,
             content=resp.text, source_date=ts)
```

**Step 5: Run smoke test**

```bash
python scrape_wayback.py --board ashby --company pinecone --out /tmp/test_hist.csv
```
Expected: runs without error, `copper/ashby.db` grows, output CSV still written (bronze derivation not wired yet — CSV path from existing code still works for now).

**Step 6: Commit**

```bash
git add scrape_wayback.py
git commit -m "refactor: wayback scraper writes to copper only"
```

---

## Task 4: Update `scrape_ashby.py` — write to copper

Live scrapes: store the board API JSON response and each `/application` page HTML to copper. `source_date` = `publishedAt` from job JSON where present, else today's date.

**Files:**
- Modify: `scrape_ashby.py`

**Step 1: Add copper writes to `scrape_all_jobs`**

```python
def scrape_all_jobs(company: str) -> tuple[list[dict], str]:
    """Returns (jobs, source_date). source_date = today in YYYYMMDD."""
    import copper as _copper
    from datetime import date
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
    log.info("Fetching all jobs from Ashby API for %s ...", company)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    source_date = date.today().strftime("%Y%m%d")
    db = _copper.open_db("ashby")
    _copper.store(db, url=url, http_status=resp.status_code,
                  content=resp.text, source_date=source_date)
    jobs = resp.json().get("jobs", [])
    log.info("Fetched %d jobs", len(jobs))
    return jobs, source_date
```

**Step 2: Store `/application` page HTML to copper**

In the `/application` fallback block in `main()`, after `app_resp = requests.get(...)`:
```python
_copper.store(db, url=job["applyUrl"], http_status=app_resp.status_code,
              content=app_resp.text,
              source_date=job.get("publishedAt", source_date)[:8].replace("-",""))
```

**Step 3: Smoke test**

```bash
python scrape_ashby.py --company pinecone --out /tmp/test_live.csv
```
Expected: runs, `copper/ashby.db` has rows, CSV written as before.

**Step 4: Commit**

```bash
git add scrape_ashby.py
git commit -m "refactor: ashby live scraper writes raw responses to copper"
```

---

## Task 5: Update `scrape_greenhouse.py` — write to copper

**Files:**
- Modify: `scrape_greenhouse.py`

**Step 1: Add copper write in the board API fetch**

Same pattern as Task 4: after `resp = requests.get(url)`, store to `copper.open_db("greenhouse")` with `source_date = date.today().strftime("%Y%m%d")`.

**Step 2: Smoke test**

```bash
python scrape_greenhouse.py --company anthropic --out /tmp/test_gh.csv
```
Expected: `copper/greenhouse.db` has rows, CSV written as before.

**Step 3: Commit**

```bash
git add scrape_greenhouse.py
git commit -m "refactor: greenhouse scraper writes raw responses to copper"
```

---

## Task 6: Add bronze derivation from copper — Ashby

Add `derive_ashby(copper_conn, bronze_conn, company)` to `bronze.py`. This function reads copper, classifies page type from URL, extracts JSON-LD from `/application` pages, and upserts to bronze.

**Files:**
- Modify: `bronze.py`
- Modify: `tests/test_bronze.py`

**Step 1: Write failing tests**

```python
# append to tests/test_bronze.py
import copper as _copper
import json
from classify import parse_json_ld_job_posting

@pytest.fixture
def copper_db(tmp_path):
    return _copper.open_db("ashby", base_dir=str(tmp_path / "copper"))

@pytest.fixture
def bronze_db(tmp_path):
    return bronze.open_db("ashby", base_dir=str(tmp_path / "bronze"))

def test_derive_ashby_job_page(copper_db, bronze_db):
    _copper.store(copper_db,
                  url="https://jobs.ashbyhq.com/pinecone/abc-123",
                  http_status=200, content="<html>job page</html>",
                  source_date="20250101")
    bronze.derive_ashby(copper_db, bronze_db, company="pinecone")
    content = bronze.get_content(bronze_db, "pinecone", "abc-123", "20250101", "job_page")
    assert content == "<html>job page</html>"

def test_derive_ashby_application_extracts_json_ld(copper_db, bronze_db):
    html = '<html><script type="application/ld+json">{"@type":"JobPosting","title":"ML Eng","baseSalary":{"@type":"MonetaryAmount","currency":"USD","value":{"@type":"QuantitativeValue","minValue":150000,"maxValue":200000,"unitText":"YEAR"}}}</script></html>'
    _copper.store(copper_db,
                  url="https://jobs.ashbyhq.com/pinecone/abc-123/application",
                  http_status=200, content=html, source_date="20250101")
    bronze.derive_ashby(copper_db, bronze_db, company="pinecone")
    raw = bronze.get_content(bronze_db, "pinecone", "abc-123", "20250101", "application")
    parsed = json.loads(raw)
    assert parsed["salary_min"] == 150000
    assert parsed["title"] == "ML Eng"
```

**Step 2: Run to verify fails**

```bash
pytest tests/test_bronze.py::test_derive_ashby_job_page -v
```
Expected: FAIL — `bronze has no attribute 'derive_ashby'`

**Step 3: Implement `derive_ashby` in `bronze.py`**

```python
import re as _re
from classify import parse_json_ld_job_posting as _parse_jld
import json as _json

_ASHBY_UUID_RE = _re.compile(
    r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(/application)?",
)

def derive_ashby(copper_conn: sqlite3.Connection, bronze_conn: sqlite3.Connection,
                 company: str) -> int:
    """Derive per-job bronze records from copper for an Ashby company.
    Returns number of bronze records upserted.
    """
    rows = copper_conn.execute(
        "SELECT id, url, content, source_date FROM responses WHERE url LIKE ?",
        (f"%ashbyhq.com/{company}/%",),
    ).fetchall()

    count = 0
    for row in rows:
        m = _ASHBY_UUID_RE.search(row["url"])
        if not m:
            continue
        job_id = m.group(2)
        is_application = bool(m.group(3))
        page_type = "application" if is_application else "job_page"

        content = row["content"] or ""
        if is_application and content:
            jld = _parse_jld(content)
            content = _json.dumps(jld) if jld else content

        store(bronze_conn,
              company=company, board="ashby", job_id=job_id,
              page_type=page_type, source_date=row["source_date"],
              original_url=row["url"], wayback_url="",
              http_status=200, content=content,
              copper_id=row["id"])
        count += 1
    return count
```

**Step 4: Run tests**

```bash
pytest tests/test_bronze.py -v
```
Expected: all pass

**Step 5: Commit**

```bash
git add bronze.py tests/test_bronze.py
git commit -m "feat: add bronze derivation from copper for Ashby"
```

---

## Task 7: Create `silver.py`

**Files:**
- Create: `silver.py`
- Create: `tests/test_silver.py`

**Step 1: Write failing tests**

```python
# tests/test_silver.py
import pytest
import silver

@pytest.fixture
def db(tmp_path):
    return silver.open_db(base_dir=str(tmp_path))

def test_tables_created(db):
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    assert "jobs" in tables
    assert "silver_rejected" in tables
    assert "audit_log" in tables

def test_upsert_job(db):
    silver.upsert_job(db, {
        "company": "pinecone", "board": "ashby", "job_id": "abc-123",
        "source_date": "20250101", "title": "ML Engineer",
        "salary_min": 150000, "salary_max": 200000, "bronze_id": 1,
    })
    row = db.execute("SELECT title, salary_min FROM jobs WHERE job_id='abc-123'").fetchone()
    assert row["title"] == "ML Engineer"
    assert row["salary_min"] == 150000

def test_reject_missing_job_id(db):
    silver.upsert_job(db, {"company": "x", "board": "ashby", "source_date": "20250101"})
    count = db.execute("SELECT count(*) FROM silver_rejected").fetchone()[0]
    assert count == 1

def test_completeness_score(db):
    silver.upsert_job(db, {
        "company": "pinecone", "board": "ashby", "job_id": "abc-456",
        "source_date": "20250101", "title": "Engineer",
        "salary_min": 100000, "location": "Remote", "bronze_id": 2,
    })
    row = db.execute("SELECT completeness FROM jobs WHERE job_id='abc-456'").fetchone()
    assert row["completeness"] == 3
```

**Step 2: Run to verify fails**

```bash
pytest tests/test_silver.py -v
```
Expected: `ModuleNotFoundError: No module named 'silver'`

**Step 3: Implement `silver.py`**

```python
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
    Path(base_dir).mkdir(exist_ok=True)
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
            """INSERT INTO silver_rejected (company, job_id, source_date, rejection_reason, rejected_at)
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

    conn.execute(
        """INSERT INTO jobs
               (company, board, job_id, source_date, title, location, url,
                department_raw, department, seniority, work_mode, salary_text,
                currency, salary_min, salary_max, salary_unit, description_md,
                has_title, has_salary, has_location, completeness,
                bronze_id, processed_at, fetched_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(company, board, job_id, source_date) DO UPDATE SET
               title=excluded.title, salary_min=excluded.salary_min,
               salary_max=excluded.salary_max, completeness=excluded.completeness,
               processed_at=excluded.processed_at""",
        (record.get("company"), record.get("board"), record.get("job_id"),
         record.get("source_date"), record.get("title"), record.get("location"),
         record.get("url"), record.get("department_raw"), record.get("department"),
         record.get("seniority"), record.get("work_mode"), record.get("salary_text"),
         record.get("currency"), record.get("salary_min"), record.get("salary_max"),
         record.get("salary_unit"), record.get("description_md"),
         has_title, has_salary, has_location, completeness,
         record.get("bronze_id"), datetime.now(timezone.utc).isoformat(),
         record.get("fetched_at")),
    )
    conn.commit()
    return True


def log_run(conn: sqlite3.Connection, company: str, board: str,
            rows_processed: int, rows_upserted: int, rows_rejected: int) -> None:
    conn.execute(
        """INSERT INTO audit_log (run_at, company, board, rows_processed, rows_upserted, rows_rejected)
           VALUES (?,?,?,?,?,?)""",
        (datetime.now(timezone.utc).isoformat(), company, board,
         rows_processed, rows_upserted, rows_rejected),
    )
    conn.commit()
```

**Step 4: Run tests**

```bash
pytest tests/test_silver.py -v
```
Expected: 4 passed

**Step 5: Commit**

```bash
git add silver.py tests/test_silver.py
git commit -m "feat: add silver layer — validated job records with audit log"
```

---

## Task 8: Create `silver.ipynb`

The silver notebook reads bronze → applies `classify.py` → validates → writes `silver/jobs.db`. This is the ETL driver.

**Files:**
- Create: `silver.ipynb`

**Step 1: Create notebook with config cell**

First code cell (config — injectable by `run_pipeline.py`):
```python
COMPANY = "pinecone"
BOARD = "ashby"
```

**Step 2: Add bronze read cell**

```python
import sqlite3, json, bronze, silver

bronze_db = bronze.open_db(BOARD)
silver_db = silver.open_db()

rows = bronze_db.execute(
    "SELECT * FROM snapshots WHERE company=? ORDER BY source_date",
    (COMPANY,)
).fetchall()
print(f"Bronze records for {COMPANY}: {len(rows)}")
```

**Step 3: Add classification cell**

```python
from classify import (
    extract_salary_block_from_html, parse_salary_text,
    classify_seniority, classify_work_mode, normalize_department,
    parse_json_ld_job_posting, SalaryParseResult,
)
import html2text

def bronze_to_silver_record(row) -> dict:
    """Convert a bronze snapshot row into a silver job record dict."""
    record = {
        "company": row["company"],
        "board": row["board"],
        "job_id": row["job_id"],
        "source_date": row["source_date"],
        "bronze_id": row["id"],
    }

    content = row["content"] or ""
    page_type = row["page_type"]

    if page_type == "application":
        # content is already extracted JSON-LD (from bronze derivation)
        try:
            jld = json.loads(content)
        except Exception:
            jld = {}
        record.update({
            "title": jld.get("title", ""),
            "location": jld.get("location", ""),
            "url": jld.get("url", ""),
            "salary_min": int(jld["salary_min"]) if jld.get("salary_min") else None,
            "salary_max": int(jld["salary_max"]) if jld.get("salary_max") else None,
            "currency": jld.get("currency", ""),
            "salary_unit": jld.get("salary_unit", ""),
            "salary_text": jld.get("salary_text", ""),
        })
    elif page_type == "job_page":
        salary_block = extract_salary_block_from_html(content)
        parsed = parse_salary_text(salary_block) if salary_block else SalaryParseResult("", None, None, None, None)
        h = html2text.HTML2Text(); h.body_width = 0; h.ignore_images = True; h.ignore_links = True
        record.update({
            "salary_text": parsed.salary_text or "",
            "salary_min": parsed.salary_min,
            "salary_max": parsed.salary_max,
            "currency": parsed.currency or "",
            "salary_unit": parsed.salary_unit or "",
            "description_md": h.handle(content).strip() if content else "",
        })

    title = record.get("title", "")
    record["seniority"] = classify_seniority(title)
    record["department"] = normalize_department(record.get("department_raw", ""))
    record["work_mode"] = classify_work_mode(record.get("location", ""))
    return record
```

**Step 4: Add upsert + audit cell**

```python
processed = upserted = rejected = 0

# Group by job_id, prefer 'application' over 'job_page'
from collections import defaultdict
by_job: dict[str, list] = defaultdict(list)
for row in rows:
    by_job[row["job_id"]].append(row)

for job_id, job_rows in by_job.items():
    # prefer application page; fall back to job_page
    row = next((r for r in job_rows if r["page_type"] == "application"), job_rows[0])
    record = bronze_to_silver_record(row)
    processed += 1
    ok = silver.upsert_job(silver_db, record)
    if ok:
        upserted += 1
    else:
        rejected += 1

silver.log_run(silver_db, COMPANY, BOARD, processed, upserted, rejected)
print(f"Processed: {processed}  Upserted: {upserted}  Rejected: {rejected}")
```

**Step 5: Test the notebook runs**

```bash
jupyter nbconvert --to notebook --execute silver.ipynb \
  --ExecutePreprocessor.kernel_name=job-analysis \
  --output /tmp/silver_test.ipynb
```
Expected: runs without error, `silver/jobs.db` created with rows

**Step 6: Commit**

```bash
git add silver.ipynb
git commit -m "feat: add silver.ipynb — bronze to silver ETL with validation"
```

---

## Task 9: Update gold notebooks to read from silver

All four notebooks replace `pd.read_csv(CSV_PATH)` with `pd.read_sql` from `silver/jobs.db`.

**Files:**
- Modify: `analyze_salaries.ipynb` (config cell)
- Modify: `analyze_historical.ipynb` (config cell)
- Modify: `analyze_nlp.ipynb` (config cell)
- Modify: `analyze_role_gap.ipynb` (config cell)

**Step 1: For each notebook, update the config cell**

Replace:
```python
CSV_PATH = "pinecone_salaries.csv"
```
With:
```python
COMPANY = "pinecone"
BOARD = "ashby"
```

**Step 2: Update the data load cell in each notebook**

Replace:
```python
df = pd.read_csv(CSV_PATH)
```
With:
```python
import sqlite3, pandas as pd
conn = sqlite3.connect("silver/jobs.db")
df = pd.read_sql("SELECT * FROM jobs WHERE company=? AND board=?",
                 conn, params=[COMPANY, BOARD])
conn.close()
```

**Step 3: For `analyze_role_gap.ipynb`, also update `JOB_ID` config**

Config cell becomes:
```python
COMPANY = "pinecone"
BOARD = "ashby"
JOB_ID = "f83ba7a6-da11-421a-ae9e-909d375e2e93"
```

**Step 4: Smoke-test one notebook**

```bash
jupyter nbconvert --to notebook --execute analyze_salaries.ipynb \
  --ExecutePreprocessor.kernel_name=job-analysis \
  --output /tmp/test_salaries.ipynb
```
Expected: runs without error, charts generated

**Step 5: Commit**

```bash
git add analyze_salaries.ipynb analyze_historical.ipynb analyze_nlp.ipynb analyze_role_gap.ipynb
git commit -m "refactor: gold notebooks read from silver/jobs.db instead of CSV"
```

---

## Task 10: Update `run_pipeline.py`

Orchestrate: copper (scrape) → bronze (derive) → silver (classify) → gold (notebooks).

**Files:**
- Modify: `run_pipeline.py`

**Step 1: Add `run_bronze_derivation` function**

```python
def run_bronze_derivation(board: str, company: str) -> None:
    import copper as _copper, bronze as _bronze
    copper_db = _copper.open_db(board)
    bronze_db = _bronze.open_db(board)
    if board == "ashby":
        count = _bronze.derive_ashby(copper_db, bronze_db, company)
    else:
        count = _bronze.derive_greenhouse(copper_db, bronze_db, company)
    log.info("Bronze derivation: %d records for %s/%s", count, board, company)
```

**Step 2: Update `main()` pipeline steps**

```python
# Step 1: Scrape → copper
csv_path = run_scraper(board, company)   # still writes CSV for now

# Step 2: Historical → copper
hist_path = run_wayback(board, company)

# Step 3: Bronze derivation
run_bronze_derivation(board, company)

# Step 4: Silver ETL
tmp = inject_notebook_config("silver.ipynb", {"COMPANY": company, "BOARD": board})
run_notebook(tmp, "Silver ETL")

# Steps 5+: Gold notebooks (update config injection to use COMPANY/BOARD not CSV_PATH)
```

**Step 3: Update `inject_notebook_config` calls for gold notebooks**

Replace `"CSV_PATH": str(csv_path)` with `{"COMPANY": company, "BOARD": board}` for all gold notebook injections.

**Step 4: Smoke test end-to-end**

```bash
python run_pipeline.py https://jobs.ashbyhq.com/pinecone/f83ba7a6-da11-421a-ae9e-909d375e2e93
```
Expected: all layers complete, summary printed

**Step 5: Commit**

```bash
git add run_pipeline.py
git commit -m "refactor: run_pipeline orchestrates copper → bronze → silver → gold"
```

---

## Task 11: Remove CSV outputs from scrapers

Once the full pipeline passes end-to-end, remove `*_salaries.csv` writes from scrapers. Scrapers become fetch-only.

**Files:**
- Modify: `scrape_ashby.py`
- Modify: `scrape_greenhouse.py`
- Modify: `scrape_wayback.py`
- Modify: `run_pipeline.py`
- Modify: `CLAUDE.md`

**Step 1: Remove `--out` arg and CSV write from `scrape_ashby.py` and `scrape_greenhouse.py`**

Delete the `csv.DictWriter` block and `--out` argument from both scrapers. Scrapers exit after writing to copper.

**Step 2: Remove `run_scraper` return value usage from `run_pipeline.py`**

`run_scraper()` no longer needs to return a CSV path. Remove `csv_path` references from `main()`.

**Step 3: Update `CLAUDE.md`**

Update usage docs to reflect new pipeline: scrapers write to copper, `silver.ipynb` produces `silver/jobs.db`, notebooks read from there.

**Step 4: Run full test suite**

```bash
pytest tests/ -v
```
Expected: all pass

**Step 5: Final commit**

```bash
git add scrape_ashby.py scrape_greenhouse.py scrape_wayback.py run_pipeline.py CLAUDE.md
git commit -m "refactor: remove CSV output from scrapers — copper-only fetch"
```
