# Job Analysis

Analyze job postings from any company to evaluate salary fairness relative to role scope. Scrapes current and historical job data from Greenhouse and Ashby job boards, then runs automated analysis notebooks.

## Quick Start

```bash
python run_pipeline.py <job_posting_url>
```

Example:

```bash
python run_pipeline.py https://jobs.ashbyhq.com/<company>/<job_id>
```

This single command:

1. **Scrapes current jobs** for the company (writes to copper)
2. **Scrapes historical jobs** from the Wayback Machine (first run only)
3. **Runs 4 analysis notebooks** with the target job's data
4. **Prints a summary** with salary, department, and location

Output notebooks are written to `/tmp/pipeline_out_*.ipynb` — open them in Jupyter to view charts.

## Architecture

```
Copper  →  Bronze  →  Silver  →  Gold
(fetch)   (schema)   (classify)  (analyze)
```

- **Copper** (`copper/ashby.db`, `copper/greenhouse.db`, `copper/adhoc.db`) — immutable raw HTTP responses. The only layer that touches the network.
- **Bronze** (`bronze/ashby.db`, `bronze/greenhouse.db`, `bronze/adhoc.db`) — schema applied. Per-job records derived from copper. Re-derivable without re-scraping.
- **Silver** (`silver/jobs.db`) — classified and validated. `classify.py` applied, completeness flags set, failed records in `silver_rejected`.
- **Gold** — analysis notebooks that read from `silver/jobs.db` via `pd.read_sql`.

## Supported Job Boards

| Board | URL Pattern 
|---|---|
| Ashby | `jobs.ashbyhq.com/<company>/<job_id>`
| Greenhouse | `job-boards.greenhouse.io/<company>/jobs/<job_id>` 

## Analysis Notebooks

| Notebook | What It Does |
|---|---|
| `analyze_salaries.ipynb` | Salary distributions by department, seniority, location — reads from `silver/jobs.db` |
| `analyze_nlp.ipynb` | Skills extraction, word clouds, job description clustering — reads from `silver/jobs.db` |
| `analyze_historical.ipynb` | Hiring volume trends, salary changes over time, time-to-fill — reads from `silver/jobs.db` |
| `analyze_role_gap.ipynb` | Compare a target job's salary vs. scope-matched comparable roles — reads from `silver/jobs.db` |

All notebooks are parameterized via `JOB_ID`. The pipeline injects these automatically, but you can also run notebooks standalone in Jupyter.

## Role Gap Analysis

The role gap notebook compares a target job against comparable roles using **scope scoring** rather than title-based seniority. Each role gets a 0-10 score based on description language:

- **Builder signals** (+2): "from scratch", "ground up", "greenfield", "first hire"
- **Owner signals** (+2): "own", "define the strategy", "set the vision", "roadmap"
- **Leader signals** (+1): "hire and manage", "build a team", "cross-functional leadership"
- **Contributor signals** (-1): "contribute to", "assist", "join a team", "report to"

Comparables are found by matching on normalized department + similar scope score.

## Setup

Requires Python 3.10+ and a Jupyter kernel. I named my kernel "job-analysis", which may or may not be hard-coded somewhere. 
There is no upstream "job-analysis" kernel, it's a decision that I made somewhere along the way.
It may, or may not, be a problem. YMMV.

```bash
python -m venv .venv
source .venv/bin/activate
pip install requests beautifulsoup4 html2text pandas matplotlib seaborn scikit-learn wordcloud
python -m ipykernel install --user --name job-analysis --display-name "Python (job-analysis)"
```

## Key Files

- `run_pipeline.py` — Single-command pipeline orchestrator. Parses job URL, scrapes, runs notebooks.
- `classify.py` — Shared classification utilities (salary parsing, department, seniority, work mode, USD conversion, normalized department taxonomy). All notebooks and scrapers import from here.
- `copper.py` — Copper layer: immutable raw HTTP response storage. One DB per board.
- `bronze.py` — Bronze layer: schema derivation from copper. Functions: `derive_ashby`, `derive_greenhouse`, `derive_adhoc`. Re-runnable without network access.
- `silver.py` — Silver layer: upsert helpers and governance tables (`silver_rejected`, `audit_log`).
- `silver.ipynb` — ETL notebook: reads bronze, merges page types, applies `classify.py`, writes `silver/jobs.db`.
- `scrape_greenhouse.py` — Live scraper for Greenhouse job boards. Usage: `python scrape_greenhouse.py --company anthropic`. Writes to `copper/greenhouse.db` only.
- `scrape_ashby.py` — Live scraper for Ashby-hosted job boards. Usage: `python scrape_ashby.py --company crusoe`. Writes to `copper/ashby.db` only.
- `scrape_wayback.py` — Historical scraper via Wayback Machine CDX API. Usage: `python scrape_wayback.py --board greenhouse --company anthropic`. Writes to `copper/{board}.db`.

## Usage

```bash
python run_pipeline.py <job_posting_url>
```

Scrapers can also be run standalone (writes copper only, no CSV):

```bash
python scrape_ashby.py --company pinecone
python scrape_greenhouse.py --company anthropic

# Historical jobs (Wayback Machine)
python scrape_wayback.py --board greenhouse --company <company>
python scrape_wayback.py --board ashby --company <company>
```

Re-derive bronze from existing copper (no network required):

```python
import copper, bronze
bronze.derive_ashby(copper.open_db("ashby"), bronze.open_db("ashby"), "pinecone")
```

Re-run silver ETL:

```bash
jupyter nbconvert --to notebook --execute silver.ipynb --output silver.ipynb
```

## Department Taxonomy

Jobs are classified into 15 normalized departments for cross-company comparison:

Research, Manufacturing, Engineering, Product, Design, People, Finance, Legal, Sales & BD, Marketing & Comms, Public Policy, Security & Compliance, IT, Operations, Other

## Current Status (2026-05-18)

Medallion architecture is live. Pipeline runs from a single command: `python run_pipeline.py <url>`. Supports Greenhouse and Ashby job boards. All four gold notebooks read from `silver/jobs.db`. Department classifier uses regex on titles with 16 ordered patterns plus an 11-bucket normalized taxonomy for cross-company analysis.
