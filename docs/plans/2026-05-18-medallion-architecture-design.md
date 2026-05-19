# Medallion Architecture Design

**Date:** 2026-05-18
**Status:** Approved

## Goal

Separate fetching, schema application, classification, and analysis into distinct layers so that parsing bugs and schema changes can be fixed by reprocessing existing data — without re-scraping Wayback or live APIs.

Primary driver: schema stability. The gold notebooks should always read from a consistent, normalized silver layer regardless of changes upstream.

## Architecture

```
Copper  →  Bronze  →  Silver  →  Gold
(fetch)   (schema)   (classify)  (analyze)
```

---

## Copper — Raw Landing Zone

**Storage:** `copper/ashby.db`, `copper/greenhouse.db`, `copper/adhoc.db`

**Purpose:** Immutable archive of raw HTTP responses exactly as received. No interpretation, no job_id extraction, no page classification.

**Schema:**
```sql
CREATE TABLE snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT    NOT NULL,
    http_status INTEGER,
    content     TEXT,
    source_date TEXT    NOT NULL,  -- event time: Wayback CDX timestamp or publishedAt
    fetched_at  TEXT    NOT NULL,  -- processing time: when we stored this
    UNIQUE(url, source_date)
);
```

**Date fields:**
- `source_date` — event time. For Wayback: CDX timestamp. For live scrapes: `publishedAt` from API where available, scrape date otherwise.
- `fetched_at` — processing time. Always the system clock at ingestion.

**Rules:**
- The only layer that touches the network (Wayback or live APIs).
- Records are never modified or deleted.
- Re-runs are idempotent via `INSERT OR IGNORE` on `(url, source_date)`.

---

## Bronze — Schema Applied

**Storage:** `bronze/ashby.db`, `bronze/greenhouse.db`

**Purpose:** Copper content parsed into a structured, job-centric model. Re-derivable from copper without network access.

**Artifacts per board:**

| Board      | page_type      | content                                      |
|------------|----------------|----------------------------------------------|
| Ashby      | `job_page`     | Raw HTML from `jobs.ashbyhq.com/{id}`        |
| Ashby      | `application`  | Extracted + parsed JSON-LD from `{id}/application` |
| Greenhouse | `job_page`     | Raw HTML from `{id}` page                    |

**Schema:**
```sql
CREATE TABLE snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company     TEXT    NOT NULL,
    board       TEXT    NOT NULL,
    job_id      TEXT    NOT NULL,
    page_type   TEXT    NOT NULL,
    source_date TEXT    NOT NULL,
    fetched_at  TEXT    NOT NULL,
    content     TEXT,
    copper_id   INTEGER,            -- FK to copper snapshot
    UNIQUE(company, job_id, source_date, page_type)
);
```

**Rules:**
- Derived from copper: reads copper, extracts job_id from URL, classifies page_type, extracts JSON-LD where applicable.
- Re-run at any time to pick up schema changes without re-scraping.

---

## Silver — Classified and Enriched

**Storage:** `silver/jobs.db`

**Purpose:** Single normalized table across all companies and boards. `classify.py` applied, validated, ready for analysis.

**Transformation:** Driven by `silver.ipynb` — interactive, inspectable, re-runnable.

**Schema (key columns):**
```sql
CREATE TABLE jobs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    company        TEXT    NOT NULL,
    board          TEXT    NOT NULL,
    job_id         TEXT    NOT NULL,
    source_date    TEXT    NOT NULL,
    -- Parsed fields
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
    -- Visibility
    has_title      INTEGER,         -- boolean
    has_salary     INTEGER,         -- boolean
    has_location   INTEGER,         -- boolean
    completeness   INTEGER,         -- 0–3
    -- Auditability
    bronze_id      INTEGER,         -- FK to bronze snapshot used
    processed_at   TEXT    NOT NULL,
    fetched_at     TEXT,
    UNIQUE(company, board, job_id, source_date)
);

CREATE TABLE silver_rejected (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    company          TEXT,
    job_id           TEXT,
    source_date      TEXT,
    rejection_reason TEXT,
    raw_content      TEXT,
    rejected_at      TEXT NOT NULL
);

CREATE TABLE audit_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at         TEXT    NOT NULL,
    company        TEXT,
    board          TEXT,
    rows_processed INTEGER,
    rows_upserted  INTEGER,
    rows_rejected  INTEGER
);
```

**Governance rules enforced in `silver.ipynb`:**
- Required fields validated before upsert: `job_id`, `source_date`, `company`
- Type checks: `salary_min`/`salary_max` must be integer or null
- Failed records written to `silver_rejected` with reason — never silently dropped
- Each run appended to `audit_log`

**Upsert key:** `(company, board, job_id, source_date)` — same record scraped twice on the same date is idempotent; a new `source_date` creates a new row, preserving history.

---

## Gold — Analysis Notebooks

**Storage:** Read from `silver/jobs.db`

**Notebooks:** `analyze_salaries.ipynb`, `analyze_nlp.ipynb`, `analyze_historical.ipynb`, `analyze_role_gap.ipynb`

**Change:** Replace `pd.read_csv(CSV_PATH)` with `pd.read_sql("SELECT * FROM jobs WHERE company=?", conn, params=[COMPANY])`. Logic unchanged.

---

## Layer-as-Notebook Refactor (2026-05-18 update)

### Approved design decisions

**Files eliminated (go away entirely):**
- `copper.py`, `bronze.py`, `silver.py`, `classify.py`

**New files:**
- `db.py` — single importable module: DB schemas, `open_db()`, `store()`, `derive_ashby()`, `derive_greenhouse()`, `upsert_job()`, `log_run()`
- `copper.ipynb` — documents copper schema, demonstrates scraper write path
- `bronze.ipynb` — calls `db.derive_ashby()` / `db.derive_greenhouse()` to transform copper → bronze
- `classify.ipynb` — notebook of all helper functions (salary parsing, department, seniority, work mode, USD conversion, `extract_yoe()`). Other notebooks use `%run classify.ipynb` to bring functions into scope.

**Files merged:**
- `silver.py` + `silver.ipynb` → single `silver.ipynb`

**Import model:**
- Scrapers import from `db` only (`open_db`, `store`)
- `bronze.ipynb`, `silver.ipynb` use `%run classify.ipynb` to load classifiers
- No `classify.py` is generated; `classify.ipynb` is the source of truth
- No `importnb` dependency required

### `yoe` column

`extract_yoe(text: str) -> int | None` lives in `classify.ipynb`. Parses phrases like "5+ years", "3–5 years experience" from `description_md`; returns minimum years mentioned or `None`. Silver schema adds `yoe INTEGER`; `silver.ipynb` populates it during bronze → silver ETL.

### `run_pipeline.py` invocation order

```
1. scrape (unchanged)
2. nbconvert --execute bronze.ipynb    (copper → bronze)
3. nbconvert --execute silver.ipynb    (bronze → silver, includes %run classify.ipynb)
4. nbconvert --execute analyze_*.ipynb (gold, unchanged logic)
```

All nbconvert calls use `--ExecutePreprocessor.kernel_name=job-analysis`.

### What Changes

| File | Change |
|------|--------|
| `scrape_ashby.py` | `from db import open_db, store` instead of `from classify import ...` |
| `scrape_greenhouse.py` | Same |
| `scrape_wayback.py` | Same |
| `run_pipeline.py` | Invokes `bronze.ipynb` and `silver.ipynb` via nbconvert before gold |
| Gold notebooks | Analysis logic unchanged; data already in silver |

### What Stays the Same

- All classification logic (moves from `classify.py` to `classify.ipynb`, same code)
- Gold notebook analysis logic
- Silver schema (plus new `yoe` column)
- Copper and bronze schemas
