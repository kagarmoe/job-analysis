# Job Analysis Project

## Project Overview
Analyzing Anthropic job postings scraped from Greenhouse job board.

## Key Files
- `classify.py` — Shared classification utilities (department, seniority, work mode, USD conversion). All three notebooks import from here. Single source of truth for the 16 Anthropic department regex rules.
- `scrape_anthropic.py` — Live scraper for current jobs via Greenhouse API. Outputs `anthropic_salaries.csv`.
- `scrape_wayback.py` — Historical scraper via Wayback Machine CDX API. Outputs `anthropic_salaries_historical.csv`.
- `analyze_salaries.ipynb` — Part I: Current salary analysis (34 cells, sections 1-9).
- `analyze_nlp.ipynb` — NLP & text analysis on job descriptions (19 cells, requires sklearn + wordcloud).
- `analyze_historical.ipynb` — Historical hiring trends (21 cells, sections 10-16).
- `anthropic_salaries.csv` — Current live data (442 jobs with description_md).
- `analyze_role_gap.ipynb` — Role complexity gap analysis: Support Ops Specialist vs. Content Architect roles.
- `anthropic_salaries_historical.csv` — Historical data (1,501 jobs, 1,413 with salary, 1,140 closed). Complete.

## Current Status (2026-02-25)
- All three notebooks are ready to run independently
- `analyze_salaries.ipynb` — no special dependencies beyond pandas/matplotlib/seaborn/bs4
- `analyze_nlp.ipynb` — requires scikit-learn and wordcloud in the notebook kernel
- `analyze_historical.ipynb` — no special dependencies beyond pandas/matplotlib/seaborn
- Department classifier uses Anthropic's real 16 departments (regex on job titles)
- Known issue: sklearn may not be in the notebook kernel's Python. Fix: `!{sys.executable} -m pip install scikit-learn wordcloud`

## TODO — Future Data Sources
- Research Google BigQuery public datasets for job posting data
- Research Common Crawl for historical Anthropic job board pages

## Technical Details
- Greenhouse API content is double-escaped HTML — must `html.unescape()` before parsing
- Currency rates: USD=1.0, EUR=1.05, GBP=1.27, CAD=0.72, AUD=0.64
- Department rules: 16 ordered regex patterns, most-specific-first, in classify.py
- Word clouds: use `generate_from_frequencies()` with pre-filtered words to ensure stopword removal
- Wayback Machine: 2.5s delay between fetches, 5 retries with 5s backoff
