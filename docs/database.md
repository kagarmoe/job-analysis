# Database Reference

The pipeline writes to three SQLite layers. All are local files; no server required.

---

## Connecting

```python
import sqlite3

# Quick read-only connection
conn = sqlite3.connect("silver/jobs.db")
conn.row_factory = sqlite3.Row   # rows behave like dicts

# Via db.py (preferred — handles schema migrations)
import db
conn = db.open_silver()          # silver/jobs.db
conn = db.open_copper("ashby")   # copper/ashby.db
conn = db.open_bronze("ashby")   # bronze/ashby.db
```

From a notebook:
```python
import sqlite3, pandas as pd
conn = sqlite3.connect("silver/jobs.db")
df = pd.read_sql("SELECT * FROM jobs WHERE company = 'crusoe'", conn)
```

---

## Layers

```
copper/{board}.db   — raw HTTP responses, immutable
bronze/{board}.db   — structured per-job records, re-derivable from copper
silver/jobs.db      — classified, normalized, analysis-ready
```

`board` is one of: `ashby`, `greenhouse`, `adhoc`.

---

## Schema

### Copper — `copper/{board}.db`

One row per HTTP fetch. Never modified after insert.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | PK |
| `url` | TEXT | Full URL fetched |
| `http_status` | INTEGER | e.g. 200 |
| `content` | TEXT | Raw response body (HTML or JSON) |
| `source_date` | TEXT | Event time: Wayback CDX timestamp or `publishedAt` |
| `fetched_at` | TEXT | Processing time: ISO-8601 UTC |

Unique constraint: `(url, source_date)` — re-scraping the same URL on the same date is a no-op.

---

### Bronze — `bronze/{board}.db`

One row per job per snapshot date per page type. Re-derived from copper without network access.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | PK |
| `company` | TEXT | e.g. `crusoe` |
| `board` | TEXT | `ashby`, `greenhouse`, `adhoc` |
| `job_id` | TEXT | Board-specific job identifier |
| `page_type` | TEXT | `api_board`, `job_page`, `application` |
| `source_date` | TEXT | Inherited from copper |
| `fetched_at` | TEXT | When this bronze row was written |
| `original_url` | TEXT | Source copper URL |
| `http_status` | INTEGER | |
| `content` | TEXT | Extracted/parsed content (JSON for api_board; HTML for pages) |
| `copper_id` | INTEGER | FK → copper.snapshots.id |

Unique constraint: `(company, job_id, source_date, page_type)`.

**page_type values:**
- `api_board` — one JSON object per job from the board API (most common for live scrapes)
- `job_page` — raw HTML of the individual job listing page
- `application` — parsed JSON-LD from the `/application` page (Ashby only; contains structured salary)

---

### Silver — `silver/jobs.db`

The query layer. Three tables.

#### `jobs`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | PK |
| `company` | TEXT | e.g. `crusoe` |
| `board` | TEXT | `ashby`, `greenhouse` |
| `job_id` | TEXT | Board-specific identifier |
| `source_date` | TEXT | Date of the source snapshot (YYYYMMDD or ISO) |
| `title` | TEXT | Job title |
| `location` | TEXT | Raw location string |
| `url` | TEXT | Canonical job URL |
| `department_raw` | TEXT | Department as-reported by the board |
| `department` | TEXT | Classified to Anthropic's 16-bucket taxonomy |
| `seniority` | TEXT | `Intern / Fellow` → `Director+` |
| `work_mode` | TEXT | `Remote-Friendly` or `Office-Only` |
| `salary_text` | TEXT | Original salary string from the posting |
| `currency` | TEXT | `USD`, `EUR`, `GBP`, `CAD`, `AUD` |
| `salary_min` | INTEGER | Annualized minimum (native currency) |
| `salary_max` | INTEGER | Annualized maximum (native currency) |
| `salary_unit` | TEXT | `annual`, `hourly`, `monthly`, `weekly` |
| `description_md` | TEXT | Job description as Markdown |
| `has_title` | INTEGER | 1 if title present |
| `has_salary` | INTEGER | 1 if salary parsed |
| `has_location` | INTEGER | 1 if location present |
| `completeness` | INTEGER | Sum of has_* flags (0–3) |
| `yoe` | INTEGER | Minimum years of experience extracted from description; NULL if not found |
| `bronze_id` | INTEGER | FK → bronze.snapshots.id |
| `processed_at` | TEXT | ISO-8601 UTC when silver row was written |
| `fetched_at` | TEXT | Inherited from bronze |

Unique constraint: `(company, board, job_id, source_date)` — same job scraped twice on the same date is idempotent; a new date creates a new row (history preserved).

#### `silver_rejected`

Records that failed validation (missing required fields). Inspect here before assuming data is missing.

| Column | Type |
|--------|------|
| `company`, `job_id`, `source_date` | TEXT |
| `rejection_reason` | TEXT |
| `raw_content` | TEXT (JSON) |
| `rejected_at` | TEXT |

#### `audit_log`

One row per silver ETL run.

| Column | Type |
|--------|------|
| `run_at` | TEXT |
| `company`, `board` | TEXT |
| `rows_processed`, `rows_upserted`, `rows_rejected` | INTEGER |

---

## Example Queries

### 1. All jobs for a company

```sql
SELECT title, location, department, seniority, salary_min, salary_max
FROM jobs
WHERE company = 'crusoe'
ORDER BY source_date DESC;
```

### 2. Jobs with salary data

```sql
SELECT title, salary_min, salary_max, currency, salary_text
FROM jobs
WHERE company = 'crusoe'
  AND has_salary = 1
ORDER BY salary_max DESC;
```

### 3. Find postings where the description mentions salary or compensation

```sql
SELECT title, company, source_date, salary_min, salary_max,
       substr(description_md, instr(lower(description_md), 'salary'), 200) AS excerpt
FROM jobs
WHERE lower(description_md) LIKE '%salary%'
   OR lower(description_md) LIKE '%compensation%'
ORDER BY company, source_date DESC;
```

### 4. Salary coverage by company

```sql
SELECT company,
       COUNT(*)                                      AS total_jobs,
       SUM(has_salary)                               AS with_salary,
       ROUND(100.0 * SUM(has_salary) / COUNT(*), 1) AS pct_salary
FROM jobs
GROUP BY company
ORDER BY pct_salary DESC;
```

### 5. Salary range by department (USD, current snapshot per job)

```sql
-- "Current" = latest source_date per job
WITH latest AS (
    SELECT company, board, job_id,
           MAX(source_date) AS max_date
    FROM jobs
    GROUP BY company, board, job_id
),
current_jobs AS (
    SELECT j.*
    FROM jobs j
    JOIN latest l
      ON j.company = l.company
     AND j.board   = l.board
     AND j.job_id  = l.job_id
     AND j.source_date = l.max_date
)
SELECT department,
       COUNT(*)                              AS n,
       MIN(salary_min)                       AS floor,
       ROUND(AVG((salary_min + salary_max) / 2.0)) AS avg_mid,
       MAX(salary_max)                       AS ceiling
FROM current_jobs
WHERE has_salary = 1
  AND currency   = 'USD'
GROUP BY department
HAVING n >= 3
ORDER BY avg_mid DESC;
```

### 6. Historical headcount trend (new postings per month)

```sql
SELECT company,
       substr(source_date, 1, 6) AS month,   -- YYYYMM
       COUNT(DISTINCT job_id)    AS new_postings
FROM jobs
GROUP BY company, month
ORDER BY company, month;
```

### 7. Jobs requiring 5+ years experience, cross-company

```sql
SELECT company, title, yoe, salary_min, salary_max, department
FROM jobs
WHERE yoe >= 5
  AND has_salary = 1
ORDER BY yoe DESC, salary_max DESC;
```

### 8. Audit: recent ETL runs and rejection rate

```sql
SELECT run_at, company, board,
       rows_processed, rows_upserted, rows_rejected,
       ROUND(100.0 * rows_rejected / MAX(rows_processed, 1), 1) AS pct_rejected
FROM audit_log
ORDER BY run_at DESC
LIMIT 20;
```

### 9. Check what was rejected and why

```sql
SELECT company, job_id, source_date, rejection_reason, rejected_at
FROM silver_rejected
ORDER BY rejected_at DESC
LIMIT 20;
```

---

## Cross-Layer Tracing

Each silver row carries `bronze_id`; each bronze row carries `copper_id`. You can trace any silver job back to the raw HTTP response:

```sql
-- Trace a silver job back to its raw copper content
SELECT c.url, c.source_date, c.content
FROM silver.jobs j                    -- attach silver as needed
JOIN bronze.snapshots b ON b.id = j.bronze_id
JOIN copper.snapshots c ON c.id = b.copper_id
WHERE j.company = 'crusoe'
  AND j.job_id  = '2689707b-7314-4246-ac95-1e6466970ba3'
LIMIT 1;
```

In Python with `db.py`:
```python
import db, sqlite3

silver = db.open_silver()
bronze = db.open_bronze("ashby")
copper = db.open_copper("ashby")

row = silver.execute(
    "SELECT bronze_id FROM jobs WHERE company=? AND job_id=? ORDER BY source_date DESC LIMIT 1",
    ("crusoe", "2689707b-7314-4246-ac95-1e6466970ba3")
).fetchone()

b = bronze.execute("SELECT copper_id, content FROM snapshots WHERE id=?",
                   (row["bronze_id"],)).fetchone()
c = copper.execute("SELECT url, content FROM snapshots WHERE id=?",
                   (b["copper_id"],)).fetchone()
print(c["url"])
```
