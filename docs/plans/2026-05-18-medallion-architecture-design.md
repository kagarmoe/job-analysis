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

## What Changes

| File | Change |
|------|--------|
| `scrape_ashby.py` | Writes to copper only — no `classify.py` calls |
| `scrape_greenhouse.py` | Writes to copper only |
| `scrape_wayback.py` | Writes to copper only |
| `bronze.py` | Extended: reads copper → extracts/normalizes → writes bronze |
| `silver.ipynb` | New: reads bronze → classifies → validates → writes silver |
| `run_pipeline.py` | Updated to orchestrate copper → bronze → silver → gold |
| Gold notebooks | `pd.read_csv` → `pd.read_sql` from `silver/jobs.db` |

## What Stays the Same

- `classify.py` — all parsing logic unchanged, called from `silver.ipynb`
- Gold notebook analysis logic — only data source changes
- `bronze.py` module interface — extended, not replaced
