# Job Analysis

Analyze job postings from any company to evaluate salary fairness relative to role scope. Scrapes current and historical job data from Greenhouse and Ashby job boards, then runs automated analysis notebooks.

## Quick Start

```bash
python run_pipeline.py <job_posting_url>
```

Example:

```bash
python run_pipeline.py https://jobs.ashbyhq.com/Anthropic/abc123
python run_pipeline.py https://job-boards.greenhouse.io/anthropic/jobs/456789
```

This single command:

1. **Scrapes current jobs** for the company (writes to `copper/`)
2. **Scrapes historical jobs** from the Wayback Machine (first run only)
3. **Runs ETL** through bronze → silver layers
4. **Runs 4 analysis notebooks** and prints a salary/location summary

Output notebooks are written to `/tmp/pipeline_out_*.ipynb` — open them in Jupyter to view charts.

## Setup

Requires Python 3.10+ and Jupyter. The pipeline uses a kernel named `job-analysis`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install requests beautifulsoup4 html2text pandas matplotlib seaborn scikit-learn wordcloud
python -m ipykernel install --user --name job-analysis --display-name "Python (job-analysis)"
```

## Supported Job Boards

| Board | URL Pattern | Example |
|---|---|---|
| Ashby | `jobs.ashbyhq.com/<company>/<job_id>` | `jobs.ashbyhq.com/Pinecone/abc-123` |
| Greenhouse | `job-boards.greenhouse.io/<company>/jobs/<job_id>` | `job-boards.greenhouse.io/anthropic/jobs/456789` |

Many companies embed Ashby or Greenhouse on their own domain (`careers.company.com`). Use the underlying board URL for best results — check the job listing page source or look for `ashbyhq.com` / `greenhouse.io` in network requests.

## Individual Commands

### Scrapers

Scrapers write raw HTTP responses to `copper/` only — no transformation, no CSV output.

```bash
# Scrape all current open jobs for a company
python scrape_ashby.py --company <company>
python scrape_greenhouse.py --company <company>

# Examples
python scrape_ashby.py --company pinecone
python scrape_greenhouse.py --company anthropic
```

```bash
# Scrape historical snapshots from the Wayback Machine
# Run once per company; slow (2.5s delay between requests)
python scrape_wayback.py --board <board> --company <company>

# Examples
python scrape_wayback.py --board ashby --company pinecone
python scrape_wayback.py --board greenhouse --company anthropic
```

### ETL Layers

Run a layer notebook directly (useful when re-processing after a schema or classifier change):

```bash
# Bronze: parse copper → structured per-job records
# Requires COMPANY and BOARD set in the config cell, or inject them:
jupyter nbconvert --to notebook --execute bronze.ipynb \
  --ExecutePreprocessor.kernel_name=job-analysis \
  --output /tmp/bronze_out.ipynb

# Silver: classify bronze records → silver/jobs.db
jupyter nbconvert --to notebook --execute silver.ipynb \
  --ExecutePreprocessor.kernel_name=job-analysis \
  --output /tmp/silver_out.ipynb
```

To re-derive bronze from existing copper without re-scraping:

```python
import db
copper_db = db.open_copper("ashby")
bronze_db = db.open_bronze("ashby")
count = db.derive_ashby(copper_db, bronze_db, "pinecone")
print(f"Derived {count} bronze records")
```

### Analysis Notebooks

Run a gold notebook directly in Jupyter, or via nbconvert:

```bash
jupyter notebook analyze_salaries.ipynb
jupyter notebook analyze_nlp.ipynb
jupyter notebook analyze_historical.ipynb
jupyter notebook analyze_role_gap.ipynb
```

Each notebook has a config cell at the top with `COMPANY`, `BOARD` (and `JOB_ID` for role gap). Set these before running.

### Database Queries

Query silver directly for quick lookups:

```bash
# Open a SQLite shell on the silver DB
sqlite3 silver/jobs.db

# Quick job count per company
sqlite3 silver/jobs.db "SELECT company, COUNT(*) FROM jobs GROUP BY company"

# Jobs with salary data
sqlite3 silver/jobs.db \
  "SELECT title, salary_min, salary_max, currency FROM jobs WHERE has_salary=1 ORDER BY salary_max DESC LIMIT 20"
```

See [docs/database.md](docs/database.md) for full schema documentation and example queries.

## Architecture

```
Copper  →  Bronze  →  Silver  →  Gold
(fetch)   (schema)   (classify)  (analyze)
```

- **Copper** (`copper/ashby.db`, `copper/greenhouse.db`) — immutable raw HTTP responses. The only layer that touches the network. Re-scraping the same URL on the same date is a no-op.
- **Bronze** (`bronze/ashby.db`, `bronze/greenhouse.db`) — schema applied. Per-job records extracted from copper. Re-derivable without re-scraping.
- **Silver** (`silver/jobs.db`) — classified and validated. Department, seniority, work mode, salary, and YOE fields populated. Failed records written to `silver_rejected` with reason.
- **Gold** — analysis notebooks that read from `silver/jobs.db` via `pd.read_sql`.

## Analysis Notebooks

| Notebook | What It Does |
|---|---|
| `analyze_salaries.ipynb` | Salary distributions by department, seniority, location |
| `analyze_nlp.ipynb` | Skills extraction, word clouds, job description clustering (requires scikit-learn) |
| `analyze_historical.ipynb` | Hiring volume trends and salary changes over time |
| `analyze_role_gap.ipynb` | Compare a target job's salary vs. scope-matched comparables |

## Role Gap Analysis

Compares a target job against comparable roles using **scope scoring** rather than title bands. Each role gets a 0–10 score based on description language:

- **Builder signals** (+2): "from scratch", "ground up", "greenfield", "first hire"
- **Owner signals** (+2): "own", "define the strategy", "set the vision", "roadmap"
- **Leader signals** (+1): "hire and manage", "build a team", "cross-functional leadership"
- **Contributor signals** (−1): "contribute to", "assist", "join a team", "report to"

Comparables are matched on normalized department + similar scope score (±1).

## Key Files

- `run_pipeline.py` — Single-command orchestrator. Parses job URL, scrapes, runs layer notebooks, then gold notebooks.
- `db.py` — All DB utilities: schemas, open/store/derive/upsert/log for every layer, plus salary parsing and classification functions. Imported by scrapers and gold notebooks.
- `classify.ipynb` — Source of truth for classification functions (department, seniority, work mode, YOE extraction). Loaded by `silver.ipynb` via `%run classify.ipynb`; gold notebooks import the same functions from `db`.
- `bronze.ipynb` — Copper → bronze ETL (executed by pipeline via nbconvert). Config: `COMPANY`, `BOARD`.
- `silver.ipynb` — Bronze → silver ETL (executed by pipeline via nbconvert). Config: `COMPANY`, `BOARD`.
- `copper.ipynb` — Documents the copper schema; shows row counts per board.
- `scrape_ashby.py` — Live Ashby scraper. Writes to `copper/ashby.db`.
- `scrape_greenhouse.py` — Live Greenhouse scraper. Writes to `copper/greenhouse.db`.
- `scrape_wayback.py` — Wayback Machine historical scraper. Writes to `copper/{board}.db`.
- `tests/` — pytest suite. `conftest.py` generates `classify.py` from `classify.ipynb` before tests run.

## Department Taxonomy

Jobs are classified into 16 detailed departments (regex on title) and 14 normalized buckets for cross-company comparison:

Research, Manufacturing, Design, Engineering, Product, People, Finance, Legal, Sales & BD, Marketing & Comms, Public Policy, Security & Compliance, IT, Operations, Other
