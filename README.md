# Job Analysis

Analyze job postings from any company to evaluate salary fairness relative to role scope. Scrapes current and historical job data from Greenhouse and Ashby job boards, then processes it through local SQLite layers.

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
4. **Prints a salary/location summary**

To also execute the optional gold analysis notebooks, pass `--run-notebooks`. Output notebooks are written to `/tmp/pipeline_out_*.ipynb`.

## Setup

Requires Python 3.10+. Jupyter is only needed for optional analysis notebooks.

```bash
python -m venv .venv
source .venv/bin/activate
pip install requests beautifulsoup4 html2text pandas matplotlib seaborn scikit-learn wordcloud
```

If you want to run notebooks via `--run-notebooks`, also install a Jupyter kernel:

```bash
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

Run a layer directly (useful when re-processing after a schema or classifier change):

```bash
# Bronze: parse copper → structured per-job records
python bronze.py --board ashby --company pinecone
python bronze.py --board greenhouse --company anthropic

# Silver: classify bronze records → silver/jobs.db
python silver.py --board ashby --company pinecone
python silver.py --board greenhouse --company anthropic
```

To re-derive bronze from existing copper without re-scraping:

```python
import bronze
count = bronze.derive("ashby", "pinecone")
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

- `run_pipeline.py` — Single-command orchestrator. Parses job URL, scrapes, runs bronze and silver ETL, then prints a summary. Optional `--run-notebooks` executes gold notebooks.
- `db.py` — Storage utilities: schemas, open/store/upsert/log helpers, plus salary parsing helpers used by bronze/silver.
- `classify.py` — Source of truth for classification functions (department, seniority, work mode, YOE extraction, USD conversion).
- `bronze.py` — Copper → bronze ETL. Derives structured board-specific records from raw copper snapshots.
- `silver.py` — Bronze → silver ETL. Merges page types, classifies jobs, validates rows, writes rejects, and logs runs.
- `scrape_ashby.py` — Live Ashby scraper. Writes to `copper/ashby.db`.
- `scrape_greenhouse.py` — Live Greenhouse scraper. Writes to `copper/greenhouse.db`.
- `scrape_wayback.py` — Wayback Machine historical scraper. Writes to `copper/{board}.db`.
- `tests/` — pytest suite, including a no-network app smoke test for the core pipeline.

## Department Taxonomy

Jobs are classified into 16 detailed departments (regex on title) and 14 normalized buckets for cross-company comparison:

Research, Manufacturing, Design, Engineering, Product, People, Finance, Legal, Sales & BD, Marketing & Comms, Public Policy, Security & Compliance, IT, Operations, Other
