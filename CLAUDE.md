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
This scrapes the company's jobs, runs wayback historical (first time only), and executes all 4 analysis notebooks.

## Key Files
- `run_pipeline.py` — Single-command pipeline orchestrator. Parses job URL, scrapes, runs notebooks.
- `classify.py` — Shared classification utilities (salary parsing, department, seniority, work mode, USD conversion, normalized department taxonomy). All notebooks and scrapers import from here.
- `scrape_greenhouse.py` — Live scraper for Greenhouse job boards. Usage: `python scrape_greenhouse.py --company anthropic`. Outputs `{company}_salaries.csv`.
- `scrape_ashby.py` — Live scraper for Ashby-hosted job boards. Usage: `python scrape_ashby.py --company crusoe`. Outputs `{company}_salaries.csv`.
- `scrape_wayback.py` — Historical scraper via Wayback Machine CDX API. Usage: `python scrape_wayback.py --board greenhouse --company anthropic`. Outputs `{company}_salaries_historical.csv`.
- `analyze_salaries.ipynb` — Current salary analysis (configurable via `CSV_PATH`).
- `analyze_nlp.ipynb` — NLP & text analysis on job descriptions (requires sklearn + wordcloud).
- `analyze_historical.ipynb` — Historical hiring trends (configurable via `CSV_PATH`).
- `analyze_role_gap.ipynb` — Role gap analysis: compare any job's salary vs. scope-matched comparables (configurable via `JOB_ID` + `CSV_PATH`).
- `anthropic_salaries.csv` — Current live data.
- `anthropic_salaries_historical.csv` — Historical data (1,501 jobs, 1,413 with salary, 1,140 closed).

## Current Status (2026-03-25)
- Pipeline runs from a single command: `python run_pipeline.py <url>`
- Supports Greenhouse and Ashby job boards
- All four notebooks are configurable via `CSV_PATH` (and `JOB_ID` for role gap)
- Department classifier uses Anthropic's 16 departments (regex on titles) + normalized 11-bucket taxonomy for cross-company analysis
- Known issue: sklearn may not be in the notebook kernel's Python. Fix: `!{sys.executable} -m pip install scikit-learn wordcloud`

## TODO — Future Data Sources
- Research Google BigQuery public datasets for job posting data
- Research Common Crawl for historical Anthropic job board pages

## Technical Details
- Greenhouse API content is double-escaped HTML — must `html.unescape()` before parsing
- Currency rates: USD=1.0, EUR=1.05, GBP=1.27, CAD=0.72, AUD=0.64
- Department rules: 16 ordered regex patterns, most-specific-first, in classify.py
- Normalized departments: 11 common buckets (Research, Manufacturing, Engineering, Product & Design, People, Finance & Legal, Sales & BD, Marketing & Comms, Public Policy, Security & IT, Operations & Other)
- Ashby API: `https://api.ashbyhq.com/posting-api/job-board/{company}` — returns JSON with department/team as structured fields
- Word clouds: use `generate_from_frequencies()` with pre-filtered words to ensure stopword removal
- Wayback Machine: 2.5s delay between fetches, 5 retries with 5s backoff
