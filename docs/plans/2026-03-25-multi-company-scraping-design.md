# Multi-Company Job Scraping

**Date:** 2026-03-25
**Status:** Approved

## Goal

Generalize the job scraping pipeline to support companies beyond Anthropic. First new target: Crusoe (Ashby job board).

## Architecture

Separate scripts per job board platform, sharing common utilities:

```
scrape_anthropic.py  -> anthropic_salaries.csv   (Greenhouse API, exists)
scrape_ashby.py      -> crusoe_salaries.csv       (Ashby API, new)
classify.py          -> shared: salary parsing, seniority, work mode, normalized departments
```

Output: one CSV per company. No combined file.

## Common Department Taxonomy (~9 buckets)

| Normalized | Anthropic examples | Crusoe examples |
|---|---|---|
| Engineering | SW Eng - Infra, Eng & Design - Product | Software, Hardware |
| Research | AI Research & Engineering | (if applicable) |
| Product & Design | Product Mgmt, Support, & Ops | Product and Design |
| People | People | People |
| Finance & Legal | Finance, Legal | Finance and Accounting |
| Sales & BD | Sales | Sales and BD |
| Marketing & Comms | Marketing & Brand, Communications | Marketing |
| Security & IT | Security, Safeguards | IT, Compliance, and Security |
| Operations & Other | TPM, Compute, Data Science, AI Policy | Operations, unmapped |

Each CSV has `department_raw` (original) and `department` (normalized).

## Changes

### classify.py
- Receive salary parsing functions from scrape_anthropic.py
- Add `NORMALIZED_DEPARTMENT_RULES` mapping company-specific -> common buckets
- Add `normalize_department()` function
- Keep existing `classify_department()` for Anthropic title-based regex

### scrape_anthropic.py
- Import salary parsing from classify.py instead of defining locally
- Add `department_raw` and `department` columns
- Add `seniority` and `work_mode` columns to CSV output

### scrape_ashby.py (new)
- Hits `https://api.ashbyhq.com/posting-api/job-board/{company}`
- Uses API's native `department` field as `department_raw`
- Reuses salary parsing from classify.py
- CLI: `python scrape_ashby.py --company crusoe --out crusoe_salaries.csv`

## CSV Schema (both scrapers)

```
job_id, title, location, url, updated_at, salary_text, currency,
salary_min, salary_max, salary_unit, department_raw, department,
seniority, work_mode, description_md
```
