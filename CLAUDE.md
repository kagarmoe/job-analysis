# Job Analysis Project

## Project Overview
Analyzing job postings scraped from multiple job boards (Greenhouse, Ashby).

## Usage
```bash
python run_pipeline.py <job_posting_url>
```
Example:
```bash
python run_pipeline.py https://jobs.ashbyhq.com/Crusoe/2689707b-7314-4246-ac95-1e6466970ba3
```
This scrapes the company's jobs, runs wayback historical (first time only), processes bronze/silver ETL, and prints a summary. Add `--run-notebooks` to execute the optional gold analysis notebooks.

## Key Files
- `run_pipeline.py` — Single-command pipeline orchestrator. Parses job URL, scrapes, runs bronze/silver Python ETL, then prints a summary. Optional `--run-notebooks` executes gold notebooks.
- `db.py` — Storage utilities: open/store/upsert/log functions for SQLite layers, plus salary parsing helpers.
- `classify.py` — Source of truth for classification functions (department, seniority, work mode, extract_yoe, USD conversion). Gold notebooks import helpers from here.
- `bronze.py` — Copper → bronze ETL. Derives board-specific structured records from raw copper snapshots.
- `silver.py` — Bronze → silver ETL. Merges page types, classifies jobs, validates rows, writes rejects, and logs runs.
- `scrape_greenhouse.py` — Live scraper for Greenhouse job boards. Usage: `python scrape_greenhouse.py --company anthropic`. Writes raw responses to `copper/greenhouse.db` only.
- `scrape_ashby.py` — Live scraper for Ashby-hosted job boards. Usage: `python scrape_ashby.py --company crusoe`. Writes raw responses to `copper/ashby.db` only.
- `scrape_wayback.py` — Historical scraper via Wayback Machine CDX API. Usage: `python scrape_wayback.py --board greenhouse --company anthropic`. Writes raw snapshots to `copper/{board}.db` only.
- `analyze_salaries.ipynb` — Current salary analysis. Config: `COMPANY`, `BOARD`.
- `analyze_nlp.ipynb` — NLP & text analysis on job descriptions (requires sklearn + wordcloud). Config: `COMPANY`, `BOARD`.
- `analyze_historical.ipynb` — Historical hiring trends. Config: `COMPANY`, `BOARD`.
- `analyze_role_gap.ipynb` — Role gap analysis: compare any job's salary vs. scope-matched comparables. Config: `COMPANY`, `BOARD`, `JOB_ID`.

## Current Status (2026-06-09)
- Medallion architecture active: copper (raw HTTP) → bronze (schema derivation) → silver (classified, queryable) → gold (notebooks)
- Pipeline runs from a single command: `python run_pipeline.py <url>`
- Core pipeline does not require Jupyter; notebooks are optional gold analysis only
- Scrapers are fetch-only: all write to `copper/{board}.db`, no CSV output
- `silver/jobs.db` is the query layer for all analysis notebooks; includes `yoe INTEGER` column
- Supports Greenhouse and Ashby job boards
- Gold notebooks are configurable via injected `COMPANY`/`BOARD` variables (and `JOB_ID` for role gap)
- Department classifier uses Anthropic's 16 departments (regex on titles) + normalized 11-bucket taxonomy for cross-company analysis
- `python -m pytest -q` includes a no-network app smoke test; passing tests should mean the core app runs

## TODO — Future Data Sources
- Research Google BigQuery public datasets for job posting data
- Research Common Crawl for historical Anthropic job board pages

## Technical Details
- Greenhouse API content is double-escaped HTML — must `html.unescape()` before parsing
- Currency rates: USD=1.0, EUR=1.05, GBP=1.27, CAD=0.72, AUD=0.64
- Department rules: ordered regex patterns, most-specific-first, in `classify.py`
- Normalized departments: 11 common buckets (Research, Manufacturing, Engineering, Product & Design, People, Finance & Legal, Sales & BD, Marketing & Comms, Public Policy, Security & IT, Operations & Other)
- Ashby API: `https://api.ashbyhq.com/posting-api/job-board/{company}` — returns JSON with department/team as structured fields
- Word clouds: use `generate_from_frequencies()` with pre-filtered words to ensure stopword removal
- Wayback Machine: 2.5s delay between fetches, 5 retries with 5s backoff
