# Single-Command Pipeline

**Date:** 2026-03-25
**Status:** Approved

## Goal

Run the entire analysis pipeline from a single command given a job posting URL.

## Usage

```bash
python run_pipeline.py https://jobs.ashbyhq.com/Crusoe/2689707b-7314-4246-ac95-1e6466970ba3
```

## Steps

1. **Parse URL** — detect board (Ashby/Greenhouse) + company slug + job ID
   - `jobs.ashbyhq.com/{company}/{job_id}` → Ashby
   - `job-boards.greenhouse.io/{company}/jobs/{job_id}` → Greenhouse
2. **Scrape current jobs** → `{company}_salaries.csv` (always runs, data changes)
3. **Scrape historical for that company (if `{company}_salaries_historical.csv` doesn't exist)** — run generalized wayback scraper; skip if file already present
4. **Inject config into notebooks** — set `CSV_PATH` and `JOB_ID`
5. **Execute all 4 notebooks:**
   - `analyze_salaries.ipynb` — current salary landscape
   - `analyze_nlp.ipynb` — job description text analysis
   - `analyze_historical.ipynb` — historical trends (skip if no historical CSV)
   - `analyze_role_gap.ipynb` — target job comparison with scope scoring
6. **Print summary** — target job title, salary, scope score, percentile, gap vs comparables

## Changes

- **New:** `run_pipeline.py` — orchestrator
- **Rename:** `scrape_anthropic.py` → `scrape_greenhouse.py`
- **Modify:** `scrape_wayback.py` — accept `--board` and `--company` args, generalize URL patterns and output path
- **Modify:** `analyze_salaries.ipynb`, `analyze_nlp.ipynb`, `analyze_historical.ipynb` — read CSV_PATH from config cell instead of hardcoded filenames
- **Modify:** `analyze_role_gap.ipynb` — already parameterized (JOB_ID + CSV_PATH)
