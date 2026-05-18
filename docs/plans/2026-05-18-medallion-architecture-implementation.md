# Medallion Architecture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor the job analysis pipeline into four layers — Copper (raw fetch), Bronze (schema), Silver (classify), Gold (analyze) — so that parsing bugs can be fixed by reprocessing existing data without re-scraping.

**Architecture:** Scrapers write raw HTTP responses to Copper only. Bronze derives structured per-job records from Copper. Silver applies `classify.py` and validates, writing to a unified `silver/jobs.db`. Gold notebooks query Silver via `pd.read_sql`. Each layer is independently re-runnable. Three board types are supported: `ashby`, `greenhouse`, and `adhoc` (any other board — fetch HTML, no structured API).

**Tech Stack:** Python 3.11, SQLite (via stdlib `sqlite3`), pandas `pd.read_sql`, Jupyter `nbformat`, pytest

**Design doc:** `docs/plans/2026-05-18-medallion-architecture-design.md`

**Review fixes applied:**
- C1: Added Task 6b (`derive_greenhouse`)
- C2: Expanded Task 3 with explicit `scrape_api_snapshots` guidance
- C3: Removed `wayback_url` from bronze schema — not board-agnostic
- I1: Copper table name unified to `snapshots` (matches design doc)
- I2: Fixed `publishedAt` date extraction bug (`[:10].replace("-","")` not `[:8]`)
- I3: Silver merge strategy reads `department_raw` from `api_board` page type, not `application`
- I4: Fixed TDD failure assertion wording in Task 2
- I5: Task 10 shows explicit `inject_notebook_config` replacement code
- I6: Task 11 includes `print_summary` update to query silver DB
- M3: Silver ON CONFLICT updates all mutable fields, not a subset
- Adhoc: Added Task 6c (`derive_adhoc`) and adhoc routing in Task 10

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

def test_adhoc_db_supported(tmp_path):
    db = copper.open_db("adhoc", base_dir=str(tmp_path))
    copper.store(db, url="https://jobs.lever.co/acme/abc",
                 http_status=200, content="<html/>", source_date="20250101")
    assert copper.get_content(db, "https://jobs.lever.co/acme/abc", "20250101") == "<html/>"
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_copper.py -v
```
Expected: `ModuleNotFoundError: No module named 'copper'`

**Step 3: Implement `copper.py`**

Note: table is named `snapshots` (not `responses`) to match the design doc.

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
    Path(base_dir).mkdir(exist_ok=True)
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
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_copper.py -v
```
Expected: 6 passed

**Step 5: Commit**

```bash
git add copper.py tests/test_copper.py
git commit -m "feat: add copper layer — raw HTTP response storage"
```

---

## Task 2: Update `bronze.py` schema

Rename `wayback_ts` → `source_date`, drop `wayback_url` (Wayback-specific, not board-agnostic), make `original_url` nullable, add `copper_id`. Delete existing `bronze/` directory so DB is recreated.

**Files:**
- Modify: `bronze.py`
- Create: `tests/test_bronze.py`

**Step 1: Write failing tests**

```python
# tests/test_bronze.py
import pytest
import bronze

@pytest.fixture
def db(tmp_path):
    return bronze.open_db("ashby", base_dir=str(tmp_path))

def test_store_requires_copper_id(db):
    # store() must accept copper_id — this fails before the change
    bronze.store(db, company="pinecone", board="ashby", job_id="abc-123",
                 source_date="20250101", page_type="job_page",
                 original_url="https://jobs.ashbyhq.com/pinecone/abc-123",
                 http_status=200, content="<html>job</html>", copper_id=1)
    content = bronze.get_content(db, "pinecone", "abc-123", "20250101", "job_page")
    assert content == "<html>job</html>"

def test_copper_id_stored(db):
    bronze.store(db, company="pinecone", board="ashby", job_id="abc-123",
                 source_date="20250101", page_type="job_page",
                 original_url="https://jobs.ashbyhq.com/pinecone/abc-123",
                 http_status=200, content="<html/>", copper_id=42)
    row = db.execute("SELECT copper_id FROM snapshots WHERE job_id='abc-123'").fetchone()
    assert row["copper_id"] == 42

def test_no_wayback_url_column(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(snapshots)").fetchall()]
    assert "wayback_url" not in cols

def test_adhoc_board_supported(tmp_path):
    db = bronze.open_db("adhoc", base_dir=str(tmp_path))
    bronze.store(db, company="acme", board="adhoc", job_id="role-eng",
                 source_date="20250101", page_type="job_page",
                 original_url="https://jobs.lever.co/acme/role-eng",
                 http_status=200, content="<html/>", copper_id=1)
    assert bronze.get_content(db, "acme", "role-eng", "20250101", "job_page") == "<html/>"
```

**Step 2: Run to verify fails**

```bash
pytest tests/test_bronze.py -v
```
Expected: FAIL — `store()` doesn't accept `copper_id` keyword argument

**Step 3: Update `bronze.py` schema and `store()`**

Replace `_SCHEMA` in `bronze.py`:

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
    original_url TEXT,
    http_status  INTEGER,
    content      TEXT,
    copper_id    INTEGER,
    UNIQUE(company, job_id, source_date, page_type)
);
CREATE INDEX IF NOT EXISTS idx_company_job ON snapshots(company, job_id);
"""
```

Update `store()` to remove `wayback_url` parameter and add `copper_id: int | None = None`:

```python
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
```

**Step 4: Delete stale bronze DB and run tests**

```bash
rm -rf bronze/
pytest tests/test_bronze.py -v
```
Expected: 4 passed

**Step 5: Commit**

```bash
git add bronze.py tests/test_bronze.py
git commit -m "refactor: update bronze schema — source_date, copper_id, drop wayback_url"
```

---

## Task 3: Update `scrape_wayback.py` — write to copper

Replace all bronze writes with copper writes. `source_date` for Wayback = CDX timestamp (e.g. `"20250315123456"`).

**Files:**
- Modify: `scrape_wayback.py`

**Step 1: Update imports**

Replace `import bronze` with `import copper`. Remove any remaining `bronze` references in this file.

**Step 2: Replace `_fetch_snapshot`**

```python
def _fetch_snapshot(
    copper_db: "sqlite3.Connection",
    job_id: str,
    ts: str,          # CDX timestamp — this IS the source_date
    page_type: str,
    orig_url: str,
) -> tuple[str | None, str]:
    """Return (content, wayback_url), reading copper cache first."""
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
                copper.store(copper_db, url=orig_url, http_status=resp.status_code,
                             content=resp.text, source_date=ts)
                return resp.text, wayback_url
        except Exception as e:
            log.warning("    fetch error: %s", e)
        time.sleep(REQUEST_DELAY)
    return None, ""
```

**Step 3: Update `_scrape_ashby_individual_fallback`**

- Replace `db = bronze.open_db("ashby")` with `copper_db = copper.open_db("ashby")`
- Update all `_fetch_snapshot(db, ...)` calls to `_fetch_snapshot(copper_db, ...)`
- Remove all `bronze.store(...)` calls — derivation is separate
- Remove all field-extraction code (calls to `_extract_job_fields`, `parse_json_ld_job_posting`, `extract_salary_block_from_html`, `parse_salary_text`) — this moves to bronze derivation. Keep only the CDX queries, the timestamp tracking loop, and the per-job fetch loop that writes to copper.
- The function should return `[]` (empty list) after storing to copper — the `JobRecord` building and CSV writing logic is removed in a later task; for now, just return `[]` to keep callers working.

**Step 4: Update `scrape_api_snapshots` — the board-level fetch**

The existing inline fetch in `scrape_api_snapshots` (the loop over `results`) directly calls `SESSION.get(snapshot_url)`. Add copper writes here. The existing `data = None` / `for mode in ["id_/", ""]` block should be replaced with a call to `_fetch_snapshot`:

```python
copper_db = copper.open_db(board)
# ... (existing CDX query code unchanged) ...

for i, row in enumerate(results):
    ts = row["timestamp"]
    url = row["original"]
    if board == "greenhouse" and "content=true" not in url:
        url = url.rstrip("/") + "?content=true"

    log.info("  [%d/%d] Fetching API snapshot from %s", i + 1, len(results), ts[:8])
    content, snapshot_url = _fetch_snapshot(copper_db, job_id="", ts=ts,
                                            page_type="api_board", orig_url=url)
    if content is None:
        log.warning("    Could not fetch snapshot, skipping")
        continue
    if not content.lstrip()[:1] == "{":
        log.warning("    Not JSON, skipping")
        continue
    # existing job-parsing loop (building JobRecords for CSV) unchanged for now
    ...
```

**Step 5: Run smoke test**

```bash
python scrape_wayback.py --board ashby --company pinecone --out /tmp/test_hist.csv
```
Expected: runs without error; `copper/ashby.db` has rows; existing CSV output still writes (the `JobRecord`-building code in `scrape_api_snapshots` is still present; `_scrape_ashby_individual_fallback` now returns `[]` so historical CSV will be empty for Ashby fallback — acceptable).

**Step 6: Commit**

```bash
git add scrape_wayback.py
git commit -m "refactor: wayback scraper writes to copper only"
```

---

## Task 4: Update `scrape_ashby.py` — write to copper

**Files:**
- Modify: `scrape_ashby.py`

**Step 1: Add copper write to `scrape_all_jobs`**

```python
def scrape_all_jobs(company: str) -> tuple[list[dict], str]:
    """Returns (jobs, source_date). source_date = today as YYYYMMDD."""
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
# Fix: publishedAt is "2025-01-15T12:00:00Z", need YYYYMMDD = [:10].replace("-","")
pub = job.get("publishedAt", "")
app_source_date = pub[:10].replace("-", "") if pub else source_date
_copper.store(db, url=job["applyUrl"], http_status=app_resp.status_code,
              content=app_resp.text, source_date=app_source_date)
```

**Step 3: Smoke test**

```bash
python scrape_ashby.py --company pinecone --out /tmp/test_live.csv
```
Expected: `copper/ashby.db` has rows, CSV written as before.

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

After `resp = requests.get(url)` succeeds, add:
```python
import copper as _copper
from datetime import date
source_date = date.today().strftime("%Y%m%d")
_db = _copper.open_db("greenhouse")
_copper.store(_db, url=url, http_status=resp.status_code,
              content=resp.text, source_date=source_date)
```

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

## Task 6: Bronze derivation — Ashby

Add `derive_ashby(copper_conn, bronze_conn, company)` to `bronze.py`. Handles three URL shapes in copper:
- `jobs.ashbyhq.com/{company}/{uuid}` → `page_type="job_page"` (raw HTML)
- `jobs.ashbyhq.com/{company}/{uuid}/application` → `page_type="application"` (extract JSON-LD)
- `api.ashbyhq.com/posting-api/job-board/{company}` → `page_type="api_board"` (split into per-job JSON with `department_raw`)

The `api_board` type is critical: it carries `department` from the structured API response. Silver uses it for `department_raw` classification.

**Files:**
- Modify: `bronze.py`
- Modify: `tests/test_bronze.py`

**Step 1: Write failing tests**

```python
# append to tests/test_bronze.py
import copper as _copper
import json

@pytest.fixture
def copper_db(tmp_path):
    return _copper.open_db("ashby", base_dir=str(tmp_path / "copper"))

@pytest.fixture
def bronze_db(tmp_path):
    return bronze.open_db("ashby", base_dir=str(tmp_path / "bronze"))

def test_derive_ashby_job_page(copper_db, bronze_db):
    _copper.store(copper_db,
                  url="https://jobs.ashbyhq.com/pinecone/abc-def-123",
                  http_status=200, content="<html>job</html>", source_date="20250101")
    bronze.derive_ashby(copper_db, bronze_db, company="pinecone")
    content = bronze.get_content(bronze_db, "pinecone", "abc-def-123", "20250101", "job_page")
    assert content == "<html>job</html>"

def test_derive_ashby_application_extracts_json_ld(copper_db, bronze_db):
    html = '<html><script type="application/ld+json">{"@type":"JobPosting","title":"ML Eng","baseSalary":{"@type":"MonetaryAmount","currency":"USD","value":{"@type":"QuantitativeValue","minValue":150000,"maxValue":200000,"unitText":"YEAR"}}}</script></html>'
    _copper.store(copper_db,
                  url="https://jobs.ashbyhq.com/pinecone/abc-def-123/application",
                  http_status=200, content=html, source_date="20250101")
    bronze.derive_ashby(copper_db, bronze_db, company="pinecone")
    raw = bronze.get_content(bronze_db, "pinecone", "abc-def-123", "20250101", "application")
    parsed = json.loads(raw)
    assert parsed["salary_min"] == 150000
    assert parsed["title"] == "ML Eng"

def test_derive_ashby_api_board_splits_jobs(copper_db, bronze_db):
    api_json = json.dumps({"jobs": [
        {"id": "uuid-1", "title": "SWE", "department": "Engineering", "descriptionHtml": ""},
        {"id": "uuid-2", "title": "PM", "department": "Product", "descriptionHtml": ""},
    ]})
    _copper.store(copper_db,
                  url="https://api.ashbyhq.com/posting-api/job-board/pinecone",
                  http_status=200, content=api_json, source_date="20250101")
    bronze.derive_ashby(copper_db, bronze_db, company="pinecone")
    c1 = bronze.get_content(bronze_db, "pinecone", "uuid-1", "20250101", "api_board")
    c2 = bronze.get_content(bronze_db, "pinecone", "uuid-2", "20250101", "api_board")
    assert json.loads(c1)["department"] == "Engineering"
    assert json.loads(c2)["department"] == "Product"
```

**Step 2: Run to verify fails**

```bash
pytest tests/test_bronze.py::test_derive_ashby_job_page -v
```
Expected: FAIL — `AttributeError: module 'bronze' has no attribute 'derive_ashby'`

**Step 3: Implement `derive_ashby` in `bronze.py`**

```python
import re as _re
import json as _json
from classify import parse_json_ld_job_posting as _parse_jld

_ASHBY_JOB_URL_RE = _re.compile(
    r"jobs\.ashbyhq\.com/([^/]+)"
    r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
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
```

**Step 4: Run all bronze tests**

```bash
pytest tests/test_bronze.py -v
```
Expected: all pass

**Step 5: Commit**

```bash
git add bronze.py tests/test_bronze.py
git commit -m "feat: add bronze derivation from copper for Ashby (job_page, application, api_board)"
```

---

## Task 6b: Bronze derivation — Greenhouse

Add `derive_greenhouse(copper_conn, bronze_conn, company)` to `bronze.py`. Greenhouse board API returns all jobs in one JSON blob; each job has an inline `content` HTML field. Store each job as `page_type="api_board"` (raw job JSON) — no separate `/application` page.

**Files:**
- Modify: `bronze.py`
- Modify: `tests/test_bronze.py`

**Step 1: Write failing tests**

```python
# append to tests/test_bronze.py

@pytest.fixture
def gh_copper_db(tmp_path):
    return _copper.open_db("greenhouse", base_dir=str(tmp_path / "copper"))

@pytest.fixture
def gh_bronze_db(tmp_path):
    return bronze.open_db("greenhouse", base_dir=str(tmp_path / "bronze"))

def test_derive_greenhouse_splits_jobs(gh_copper_db, gh_bronze_db):
    api_json = json.dumps({"jobs": [
        {"id": 101, "title": "Backend Eng",
         "departments": [{"name": "Engineering"}],
         "location": {"name": "Remote"},
         "content": "<p>Description</p>"},
        {"id": 102, "title": "Designer",
         "departments": [{"name": "Design"}],
         "location": {"name": "SF"},
         "content": "<p>Design role</p>"},
    ]})
    _copper.store(gh_copper_db,
                  url="https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true",
                  http_status=200, content=api_json, source_date="20250101")
    bronze.derive_greenhouse(gh_copper_db, gh_bronze_db, company="acme")
    c1 = bronze.get_content(gh_bronze_db, "acme", "101", "20250101", "api_board")
    assert json.loads(c1)["title"] == "Backend Eng"
    c2 = bronze.get_content(gh_bronze_db, "acme", "102", "20250101", "api_board")
    assert json.loads(c2)["title"] == "Designer"
```

**Step 2: Run to verify fails**

```bash
pytest tests/test_bronze.py::test_derive_greenhouse_splits_jobs -v
```
Expected: FAIL — `AttributeError: module 'bronze' has no attribute 'derive_greenhouse'`

**Step 3: Implement `derive_greenhouse` in `bronze.py`**

```python
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
```

**Step 4: Run all tests**

```bash
pytest tests/test_bronze.py -v
```
Expected: all pass

**Step 5: Commit**

```bash
git add bronze.py tests/test_bronze.py
git commit -m "feat: add bronze derivation from copper for Greenhouse"
```

---

## Task 6c: Bronze derivation — Adhoc

Add `derive_adhoc(copper_conn, bronze_conn, company, job_id)` to `bronze.py`. Adhoc jobs come from boards with no structured API — just raw HTML. Store as `page_type="job_page"`. The caller (run_pipeline.py) provides `company` and `job_id` since they can't be inferred from the URL.

**Files:**
- Modify: `bronze.py`
- Modify: `tests/test_bronze.py`

**Step 1: Write failing tests**

```python
# append to tests/test_bronze.py

@pytest.fixture
def adhoc_copper_db(tmp_path):
    return _copper.open_db("adhoc", base_dir=str(tmp_path / "copper"))

@pytest.fixture
def adhoc_bronze_db(tmp_path):
    return bronze.open_db("adhoc", base_dir=str(tmp_path / "bronze"))

def test_derive_adhoc(adhoc_copper_db, adhoc_bronze_db):
    url = "https://jobs.lever.co/acme/engineer-role"
    _copper.store(adhoc_copper_db, url=url, http_status=200,
                  content="<html><title>Engineer | Acme</title></html>",
                  source_date="20250101")
    bronze.derive_adhoc(adhoc_copper_db, adhoc_bronze_db,
                        company="acme", job_id="engineer-role")
    content = bronze.get_content(adhoc_bronze_db, "acme", "engineer-role", "20250101", "job_page")
    assert "<title>Engineer" in content
```

**Step 2: Run to verify fails**

```bash
pytest tests/test_bronze.py::test_derive_adhoc -v
```
Expected: FAIL — `AttributeError: module 'bronze' has no attribute 'derive_adhoc'`

**Step 3: Implement `derive_adhoc` in `bronze.py`**

```python
def derive_adhoc(copper_conn: sqlite3.Connection, bronze_conn: sqlite3.Connection,
                 company: str, job_id: str) -> int:
    """Derive a single bronze record for an adhoc (non-Ashby/Greenhouse) job."""
    rows = copper_conn.execute(
        "SELECT id, url, content, source_date FROM snapshots "
        "WHERE url LIKE ? ORDER BY source_date DESC LIMIT 1",
        (f"%{job_id}%",),
    ).fetchall()
    count = 0
    for row in rows:
        store(bronze_conn, company=company, board="adhoc", job_id=job_id,
              page_type="job_page", source_date=row["source_date"],
              original_url=row["url"], http_status=200,
              content=row["content"] or "", copper_id=row["id"])
        count += 1
    return count
```

**Step 4: Run all tests**

```bash
pytest tests/test_bronze.py -v
```
Expected: all pass

**Step 5: Commit**

```bash
git add bronze.py tests/test_bronze.py
git commit -m "feat: add bronze derivation for adhoc boards"
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

def test_upsert_updates_all_fields_on_conflict(db):
    silver.upsert_job(db, {
        "company": "pinecone", "board": "ashby", "job_id": "abc-123",
        "source_date": "20250101", "title": "Old Title", "location": "",
        "salary_min": None, "bronze_id": 1,
    })
    silver.upsert_job(db, {
        "company": "pinecone", "board": "ashby", "job_id": "abc-123",
        "source_date": "20250101", "title": "New Title", "location": "Remote",
        "salary_min": 150000, "department": "Engineering", "bronze_id": 2,
    })
    row = db.execute("SELECT title, location, department FROM jobs WHERE job_id='abc-123'").fetchone()
    assert row["title"] == "New Title"
    assert row["location"] == "Remote"
    assert row["department"] == "Engineering"

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

def test_adhoc_board_accepted(db):
    result = silver.upsert_job(db, {
        "company": "acme", "board": "adhoc", "job_id": "role-eng",
        "source_date": "20250101", "title": "Engineer", "bronze_id": 5,
    })
    assert result is True
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
```

**Step 4: Run tests**

```bash
pytest tests/test_silver.py -v
```
Expected: 6 passed

**Step 5: Commit**

```bash
git add silver.py tests/test_silver.py
git commit -m "feat: add silver layer — validated job records with full upsert and audit log"
```

---

## Task 8: Create `silver.ipynb`

Reads bronze → merges `api_board` + `application` + `job_page` per job → applies `classify.py` → validates → writes `silver/jobs.db`.

Merge strategy per job_id (in priority order):
1. `api_board` row → `department_raw`, `title`, `location`, `url` (structured API fields)
2. `application` row → salary fields (JSON-LD)
3. `job_page` row → `description_md`

This ensures `department_raw` comes from the API (which has it), not from JSON-LD (which doesn't).

**Files:**
- Create: `silver.ipynb`

**Step 1: Config cell (injectable by `run_pipeline.py`)**

```python
COMPANY = "pinecone"
BOARD = "ashby"
```

**Step 2: Bronze read cell**

```python
import sqlite3, json, bronze, silver
from collections import defaultdict

bronze_db = bronze.open_db(BOARD)
silver_db = silver.open_db()

rows = bronze_db.execute(
    "SELECT * FROM snapshots WHERE company=? ORDER BY source_date",
    (COMPANY,)
).fetchall()
print(f"Bronze records for {COMPANY}: {len(rows)}")

# Group by job_id → {page_type: row}
by_job: dict[str, dict] = defaultdict(dict)
for row in rows:
    by_job[row["job_id"]][row["page_type"]] = row

print(f"Unique jobs: {len(by_job)}")
```

**Step 3: Classification cell**

```python
from classify import (
    extract_salary_block_from_html, parse_salary_text,
    classify_seniority, classify_work_mode, normalize_department,
    SalaryParseResult,
)
import html2text

def _md(html_text: str) -> str:
    if not html_text:
        return ""
    h = html2text.HTML2Text()
    h.body_width = 0; h.ignore_images = True; h.ignore_links = True
    return h.handle(html_text).strip()

def merge_to_silver(job_id: str, page_rows: dict) -> dict:
    """Merge bronze page_type rows into one silver record.
    api_board → base fields + department_raw
    application → salary
    job_page → description_md (fallback title/location)
    """
    api = page_rows.get("api_board")
    app = page_rows.get("application")
    page = page_rows.get("job_page")
    source_row = api or app or page  # for company/board/source_date

    record = {
        "company": source_row["company"],
        "board": source_row["board"],
        "job_id": job_id,
        "source_date": source_row["source_date"],
        "bronze_id": source_row["id"],
    }

    # Base fields from api_board (most structured)
    if api:
        try:
            job = json.loads(api["content"] or "{}")
        except Exception:
            job = {}
        record["title"] = job.get("title", "")
        record["location"] = job.get("location", "")
        record["url"] = job.get("jobUrl") or job.get("absolute_url", "")
        record["department_raw"] = (
            job.get("department") or job.get("team") or
            (job.get("departments") or [{}])[0].get("name", "")
        )

    # Salary from application (JSON-LD)
    if app:
        try:
            jld = json.loads(app["content"] or "{}")
        except Exception:
            jld = {}
        if jld.get("salary_min"):
            record["salary_min"] = int(jld["salary_min"])
            record["salary_max"] = int(jld["salary_max"]) if jld.get("salary_max") else None
            record["currency"] = jld.get("currency", "")
            record["salary_unit"] = jld.get("salary_unit", "")
            record["salary_text"] = jld.get("salary_text", "")
        if not record.get("title"):
            record["title"] = jld.get("title", "")
        if not record.get("location"):
            record["location"] = jld.get("location", "")

    # Description + salary fallback from job_page HTML
    if page:
        content = page["content"] or ""
        record["description_md"] = _md(content)
        if not record.get("salary_min"):
            sal_block = extract_salary_block_from_html(content)
            parsed = parse_salary_text(sal_block) if sal_block else SalaryParseResult("", None, None, None, None)
            if parsed.salary_min:
                record["salary_min"] = parsed.salary_min
                record["salary_max"] = parsed.salary_max
                record["currency"] = parsed.currency or ""
                record["salary_unit"] = parsed.salary_unit or ""
                record["salary_text"] = parsed.salary_text or ""
        if not record.get("title"):
            record["title"] = _title_from_html(content)

    title = record.get("title", "")
    record["seniority"] = classify_seniority(title)
    record["department"] = normalize_department(record.get("department_raw", ""))
    record["work_mode"] = classify_work_mode(record.get("location", ""))
    return record
```

**Step 4: Upsert + audit cell**

```python
processed = upserted = rejected = 0

for job_id, page_rows in by_job.items():
    record = merge_to_silver(job_id, page_rows)
    processed += 1
    ok = silver.upsert_job(silver_db, record)
    upserted += ok
    rejected += not ok

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
git commit -m "feat: add silver.ipynb — bronze-to-silver ETL with api_board/application/job_page merge"
```

---

## Task 9: Update gold notebooks to read from silver

**Files:**
- Modify: `analyze_salaries.ipynb`
- Modify: `analyze_historical.ipynb`
- Modify: `analyze_nlp.ipynb`
- Modify: `analyze_role_gap.ipynb`

**Step 1: Update config cell in each notebook**

Replace `CSV_PATH = "..."` with:
```python
COMPANY = "pinecone"
BOARD = "ashby"
```

For `analyze_role_gap.ipynb`, config cell becomes:
```python
COMPANY = "pinecone"
BOARD = "ashby"
JOB_ID = "f83ba7a6-da11-421a-ae9e-909d375e2e93"
```

**Step 2: Update data load cell in each notebook**

Replace:
```python
df = pd.read_csv(CSV_PATH)
```
With:
```python
import sqlite3, pandas as pd
_conn = sqlite3.connect("silver/jobs.db")
df = pd.read_sql("SELECT * FROM jobs WHERE company=? AND board=?",
                 _conn, params=[COMPANY, BOARD])
_conn.close()
```

**Step 3: Smoke-test one notebook**

```bash
jupyter nbconvert --to notebook --execute analyze_salaries.ipynb \
  --ExecutePreprocessor.kernel_name=job-analysis \
  --output /tmp/test_salaries.ipynb
```
Expected: runs without error, charts generated

**Step 4: Commit**

```bash
git add analyze_salaries.ipynb analyze_historical.ipynb analyze_nlp.ipynb analyze_role_gap.ipynb
git commit -m "refactor: gold notebooks read from silver/jobs.db instead of CSV"
```

---

## Task 10: Update `run_pipeline.py`

Orchestrate: copper (scrape) → bronze (derive) → silver (classify) → gold (notebooks). Add adhoc board routing. Fix `inject_notebook_config` calls for gold notebooks. Fix `print_summary` to query silver.

**Files:**
- Modify: `run_pipeline.py`

**Step 1: Add `scrape_adhoc` function**

```python
def scrape_adhoc(url: str, company: str, job_id: str) -> None:
    """Fetch a single job page from an unknown board and store to copper/adhoc."""
    import copper as _copper, requests
    from datetime import date
    db = _copper.open_db("adhoc")
    source_date = date.today().strftime("%Y%m%d")
    log.info("Fetching adhoc job: %s", url)
    resp = requests.get(url, timeout=30, headers={"User-Agent": "JobBoardResearch/1.0"})
    resp.raise_for_status()
    _copper.store(db, url=url, http_status=resp.status_code,
                  content=resp.text, source_date=source_date)
    log.info("Stored adhoc page to copper/adhoc.db")
```

**Step 2: Update `parse_job_url` to handle unknown boards**

Replace the `raise ValueError(...)` at the end of `parse_job_url` with:

```python
    # Unknown board — route to adhoc
    parts = path.strip("/").split("/")
    job_id = parts[-1] if parts else path.replace("/", "-")
    company = (parsed.hostname or "").split(".")[0]
    return {"board": "adhoc", "company": company, "job_id": job_id}
```

**Step 3: Add `run_bronze_derivation` function**

```python
def run_bronze_derivation(board: str, company: str, job_id: str = "") -> None:
    import copper as _copper, bronze as _bronze
    copper_db = _copper.open_db(board)
    bronze_db = _bronze.open_db(board)
    if board == "ashby":
        count = _bronze.derive_ashby(copper_db, bronze_db, company)
    elif board == "greenhouse":
        count = _bronze.derive_greenhouse(copper_db, bronze_db, company)
    else:  # adhoc
        count = _bronze.derive_adhoc(copper_db, bronze_db, company, job_id)
    log.info("Bronze derivation: %d records for %s/%s", count, board, company)
```

**Step 4: Update `main()` pipeline**

```python
info = parse_job_url(args.url)
board, company, job_id = info["board"], info["company"], info["job_id"]

# Step 1: Scrape → copper
if board == "adhoc":
    scrape_adhoc(args.url, company, job_id)
else:
    run_scraper(board, company)       # still writes CSV as side-effect for now
    run_wayback(board, company)

# Step 2: Bronze derivation
run_bronze_derivation(board, company, job_id)

# Step 3: Silver ETL
tmp = inject_notebook_config("silver.ipynb", {"COMPANY": company, "BOARD": board})
results = [("Silver ETL", run_notebook(tmp, "Silver ETL"))]

# Step 4: Gold notebooks — inject COMPANY/BOARD (not CSV_PATH)
nb_config = {"COMPANY": company, "BOARD": board}

tmp = inject_notebook_config("analyze_salaries.ipynb", nb_config)
results.append(("Salary Analysis", run_notebook(tmp, "Salary Analysis")))

tmp = inject_notebook_config("analyze_nlp.ipynb", nb_config)
results.append(("NLP Analysis", run_notebook(tmp, "NLP Analysis")))

hist_path = Path(f"{company}_salaries_historical.csv")
if hist_path.exists():
    tmp = inject_notebook_config("analyze_historical.ipynb", nb_config)
    results.append(("Historical Analysis", run_notebook(tmp, "Historical Analysis")))

tmp = inject_notebook_config("analyze_role_gap.ipynb", {**nb_config, "JOB_ID": job_id})
results.append(("Role Gap Analysis", run_notebook(tmp, "Role Gap Analysis")))
```

**Step 5: Fix `print_summary` to query silver**

Replace the CSV-reading `print_summary` function with:

```python
def print_summary(company: str, board: str, job_id: str):
    import sqlite3 as _sqlite3
    try:
        conn = _sqlite3.connect("silver/jobs.db")
        conn.row_factory = _sqlite3.Row
        target = conn.execute(
            "SELECT * FROM jobs WHERE company=? AND board=? AND job_id=?",
            (company, board, job_id)
        ).fetchone()
        conn.close()
    except Exception as e:
        log.warning("Could not query silver for summary: %s", e)
        return
    if not target:
        log.warning("Job %s not found in silver for summary", job_id)
        return
    print("\n" + "=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    print(f"  Target:     {target['title']}")
    print(f"  Company:    {company}")
    print(f"  Department: {target['department'] or 'N/A'}")
    sal_min, sal_max = target["salary_min"], target["salary_max"]
    salary_str = f"${float(sal_min):,.0f} – ${float(sal_max):,.0f}" if sal_min and sal_max else "N/A"
    print(f"  Salary:     {salary_str}")
    print(f"  Location:   {target['location'] or 'N/A'}")
    print("=" * 60)
```

Update the call site in `main()`:
```python
print_summary(company, board, job_id)
```

**Step 6: Smoke test end-to-end**

```bash
python run_pipeline.py https://jobs.ashbyhq.com/pinecone/f83ba7a6-da11-421a-ae9e-909d375e2e93
```
Expected: all layers complete, summary printed from silver

**Step 7: Commit**

```bash
git add run_pipeline.py
git commit -m "refactor: run_pipeline orchestrates copper→bronze→silver→gold with adhoc support"
```

---

## Task 11: Remove CSV outputs from scrapers

Once the full pipeline passes end-to-end, remove `*_salaries.csv` writes. Scrapers become fetch-only.

**Files:**
- Modify: `scrape_ashby.py`
- Modify: `scrape_greenhouse.py`
- Modify: `scrape_wayback.py`
- Modify: `run_pipeline.py`
- Modify: `CLAUDE.md`

**Step 1: Remove CSV write and `--out` arg from `scrape_ashby.py`**

Delete: `fieldnames` list, `rows` list, the job-processing loop that builds rows, the `csv.DictWriter` block, and the `--out` argparse argument. The `main()` function should end after `scrape_all_jobs()` returns (copper write happens inside that function).

**Step 2: Remove CSV write and `--out` arg from `scrape_greenhouse.py`**

Same pattern as above.

**Step 3: Remove JobRecord building from `scrape_wayback.py`**

Remove: `JobRecord` dataclass, `write_csv`, `mark_active_jobs`, all `classify.py` calls, the `--out` argparse argument, and the summary log block. The `main()` function should end after `scrape_api_snapshots()` returns (copper writes happen inside).

**Step 4: Remove CSV references from `run_pipeline.py`**

Remove `run_scraper()` and `run_wayback()` functions (replaced by direct copper writes in scrapers + `run_bronze_derivation`). Remove the `--out` subprocess args. The `hist_path.exists()` check for historical analysis should query bronze/silver instead — replace with:
```python
has_historical = bool(bronze_db.execute(
    "SELECT 1 FROM snapshots WHERE company=? LIMIT 1", (company,)
).fetchone())
```

**Step 5: Run full test suite**

```bash
pytest tests/ -v
```
Expected: all pass

**Step 6: Update `CLAUDE.md`**

Update the Key Files section and Usage section to reflect:
- Scrapers write to `copper/{board}.db` only
- `silver.ipynb` produces `silver/jobs.db`
- Gold notebooks read from `silver/jobs.db`
- `run_pipeline.py <url>` still the single entry point

**Step 7: Final commit**

```bash
git add scrape_ashby.py scrape_greenhouse.py scrape_wayback.py run_pipeline.py CLAUDE.md
git commit -m "refactor: remove CSV outputs — scrapers are copper-only, silver is the query layer"
```

---

## Task 12: Update `README.md`

Update the README to reflect the medallion architecture: four-layer data flow, updated usage, new files, and removed CSV outputs.

**Files:**
- Modify: `README.md`

**Step 1: Update the Architecture section**

Replace or add an Architecture section describing the four layers:

```markdown
## Architecture

```
Copper  →  Bronze  →  Silver  →  Gold
(fetch)   (schema)   (classify)  (analyze)
```

- **Copper** (`copper/ashby.db`, `copper/greenhouse.db`, `copper/adhoc.db`) — immutable raw HTTP responses. Only layer that touches the network.
- **Bronze** (`bronze/ashby.db`, `bronze/greenhouse.db`, `bronze/adhoc.db`) — schema applied. Per-job records derived from copper. Re-derivable without re-scraping.
- **Silver** (`silver/jobs.db`) — classified and validated. `classify.py` applied, completeness flags set, failed records in `silver_rejected`.
- **Gold** — analysis notebooks that read from `silver/jobs.db` via `pd.read_sql`.
```

**Step 2: Update the Key Files section**

Replace the old scraper/CSV-centric descriptions. New entries to add or update:

- `copper.py` — Copper layer: raw HTTP response storage (one DB per board). Immutable; written by scrapers.
- `bronze.py` — Bronze layer: schema derivation from copper. `derive_ashby`, `derive_greenhouse`, `derive_adhoc`.
- `silver.py` — Silver layer: upsert helpers, governance tables (`silver_rejected`, `audit_log`).
- `silver.ipynb` — Interactive ETL: reads bronze → merges page types → applies `classify.py` → writes `silver/jobs.db`.
- Scrapers (`scrape_ashby.py`, `scrape_greenhouse.py`, `scrape_wayback.py`) — now write to copper only; no CSV output.
- Gold notebooks — read from `silver/jobs.db` (not CSV).

**Step 3: Update Usage section**

The single command is unchanged:
```bash
python run_pipeline.py https://jobs.ashbyhq.com/Crusoe/...
```

Add a note that scrapers can also be run standalone (writes copper only):
```bash
python scrape_ashby.py --company pinecone
python scrape_greenhouse.py --company anthropic
```

And silver can be rebuilt without re-scraping:
```bash
# Re-derive bronze from existing copper (no network)
python -c "import copper, bronze; bronze.derive_ashby(copper.open_db('ashby'), bronze.open_db('ashby'), 'pinecone')"

# Re-run silver ETL
jupyter nbconvert --to notebook --execute silver.ipynb --output silver.ipynb
```

**Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README for medallion architecture — four layers, no CSV outputs"
```
