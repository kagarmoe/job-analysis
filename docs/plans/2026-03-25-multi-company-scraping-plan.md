# Multi-Company Scraping Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Generalize the scraping pipeline to support multiple companies/job boards, starting with Crusoe on Ashby.

**Architecture:** Separate scraper scripts per job board platform (Greenhouse, Ashby), sharing salary parsing and classification logic via `classify.py`. A normalized ~9-bucket department taxonomy enables cross-company analysis.

**Tech Stack:** Python 3, requests, BeautifulSoup, html2text, csv, pytest

**Design doc:** `docs/plans/2026-03-25-multi-company-scraping-design.md`

---

### Task 1: Move salary parsing from scrape_anthropic.py to classify.py

**Files:**
- Modify: `classify.py` (add salary parsing functions)
- Modify: `scrape_anthropic.py` (import from classify instead of defining locally)

**Step 1: Move salary parsing code to classify.py**

Move these items from `scrape_anthropic.py` to `classify.py`:
- Imports: `html`, `from dataclasses import dataclass`, `from typing import Optional`, `from bs4 import BeautifulSoup`
- Constants: `DASH_PATTERN`, `CURRENCY_SYM_1`, `CURRENCY_SYM_2`, `NUMBER`, `SALARY_RANGE_RE`
- Classes: `SalaryParseResult`
- Functions: `normalize_whitespace`, `looks_like_salary_text`, `extract_salary_block_from_html`, `parse_salary_text`

Add them after the existing `add_usd_salary` function. Keep `_html_to_markdown` in `scrape_anthropic.py` (it's scraper-specific).

**Step 2: Update scrape_anthropic.py imports**

Replace the local definitions with:
```python
from classify import (
    SalaryParseResult, extract_salary_block_from_html, parse_salary_text,
)
```

Remove from `scrape_anthropic.py`:
- `from dataclasses import dataclass`
- `SalaryParseResult` class
- `DASH_PATTERN`, `CURRENCY_SYM_1`, `CURRENCY_SYM_2`, `NUMBER`, `SALARY_RANGE_RE`
- `normalize_whitespace`, `looks_like_salary_text`, `extract_salary_block_from_html`, `parse_salary_text`

Keep: `_html_to_markdown`, `greenhouse_job_url`, `scrape_all_jobs`, `main`, and all non-salary imports.

**Step 3: Verify scrape_anthropic.py still runs**

Run: `python scrape_anthropic.py --out /tmp/test_anthropic.csv`
Expected: completes without error, CSV written with salary data

**Step 4: Commit**

```bash
git add classify.py scrape_anthropic.py
git commit -m "refactor: move salary parsing from scrape_anthropic to classify.py"
```

---

### Task 2: Add normalized department taxonomy to classify.py

**Files:**
- Modify: `classify.py`
- Create: `tests/test_classify.py`

**Step 1: Write failing tests for normalize_department**

Create `tests/test_classify.py`:

```python
"""Tests for classify.py department normalization."""
from classify import normalize_department


def test_anthropic_engineering():
    assert normalize_department("Software Engineering - Infrastructure") == "Engineering"
    assert normalize_department("Engineering & Design - Product") == "Engineering"


def test_anthropic_research():
    assert normalize_department("AI Research & Engineering") == "Research"


def test_anthropic_product():
    assert normalize_department("Product Management, Support, & Operations") == "Product & Design"


def test_anthropic_people():
    assert normalize_department("People") == "People"


def test_anthropic_finance_legal():
    assert normalize_department("Finance") == "Finance & Legal"
    assert normalize_department("Legal") == "Finance & Legal"


def test_anthropic_sales():
    assert normalize_department("Sales") == "Sales & BD"


def test_anthropic_marketing():
    assert normalize_department("Marketing & Brand") == "Marketing & Comms"
    assert normalize_department("Communications") == "Marketing & Comms"


def test_anthropic_security():
    assert normalize_department("Security") == "Security & IT"
    assert normalize_department("Safeguards (Trust & Safety)") == "Security & IT"


def test_anthropic_operations():
    assert normalize_department("Technical Program Management") == "Operations & Other"
    assert normalize_department("Compute") == "Operations & Other"
    assert normalize_department("Data Science & Analytics") == "Operations & Other"
    assert normalize_department("AI Public Policy & Societal Impacts") == "Operations & Other"


def test_crusoe_departments():
    assert normalize_department("Software") == "Engineering"
    assert normalize_department("Hardware") == "Engineering"
    assert normalize_department("Product and Design") == "Product & Design"
    assert normalize_department("People") == "People"
    assert normalize_department("Finance and Accounting") == "Finance & Legal"
    assert normalize_department("Sales and BD") == "Sales & BD"
    assert normalize_department("IT, Compliance, and Security") == "Security & IT"
    assert normalize_department("Operations") == "Operations & Other"


def test_unknown_department():
    assert normalize_department("Something Totally New") == "Operations & Other"
    assert normalize_department("") == "Operations & Other"


def test_other_passthrough():
    assert normalize_department("Other") == "Operations & Other"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_classify.py -v`
Expected: FAIL — `normalize_department` does not exist yet

**Step 3: Implement normalize_department in classify.py**

Add after `SENIORITY_ORDER` (line 114):

```python
# Normalized department taxonomy — maps company-specific departments to ~9 common buckets.
# Rules are ordered most-specific-first; first regex match wins.
NORMALIZED_DEPARTMENT_RULES = [
    ("Research",        r"\bresearch\b"),
    ("Engineering",     r"\bengineering\b|\bsoftware\b|\bhardware\b|\binfrastructure\b"),
    ("Product & Design", r"\bproduct\b|\bdesign\b"),
    ("People",          r"\bpeople\b|\brecruit|\bHR\b|\bhuman resources\b"),
    ("Finance & Legal", r"\bfinance\b|\blegal\b|\baccounting\b|\bcounsel\b"),
    ("Sales & BD",      r"\bsales\b|\bbusiness development\b|\b[BS]DR\b|\bBD\b"),
    ("Marketing & Comms", r"\bmarketing\b|\bbrand\b|\bcommunication"),
    ("Security & IT",   r"\bsecurity\b|\bsafeguard|\bIT\b|\bcompliance\b"),
    ("Operations & Other", r".*"),  # catch-all
]


def normalize_department(department_raw: str) -> str:
    """Map a company-specific department name to a normalized ~9-bucket taxonomy."""
    if not isinstance(department_raw, str) or not department_raw:
        return "Operations & Other"
    for bucket, pattern in NORMALIZED_DEPARTMENT_RULES:
        if re.search(pattern, department_raw, re.I):
            return bucket
    return "Operations & Other"
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_classify.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add classify.py tests/test_classify.py
git commit -m "feat: add normalized department taxonomy with 9 common buckets"
```

---

### Task 3: Add department/seniority/work_mode columns to scrape_anthropic.py output

**Files:**
- Modify: `scrape_anthropic.py:199-255` (main function)

**Step 1: Update scrape_anthropic.py main() to add new columns**

In `main()`, add import at top of file:
```python
from classify import (
    SalaryParseResult, extract_salary_block_from_html, parse_salary_text,
    classify_department, classify_seniority, classify_work_mode, normalize_department,
)
```

Update `fieldnames` list (line 206) to:
```python
fieldnames = [
    "job_id",
    "title",
    "location",
    "url",
    "updated_at",
    "salary_text",
    "currency",
    "salary_min",
    "salary_max",
    "salary_unit",
    "department_raw",
    "department",
    "seniority",
    "work_mode",
    "description_md",
]
```

In the row-building loop, add after `description_md`:
```python
department_raw = classify_department(title)
rows.append(
    {
        ...existing fields...,
        "department_raw": department_raw,
        "department": normalize_department(department_raw),
        "seniority": classify_seniority(title),
        "work_mode": classify_work_mode(location),
        "description_md": description_md,
    }
)
```

**Step 2: Verify it runs**

Run: `python scrape_anthropic.py --out /tmp/test_anthropic2.csv`
Then: `head -2 /tmp/test_anthropic2.csv` — verify new columns present

**Step 3: Commit**

```bash
git add scrape_anthropic.py
git commit -m "feat: add department, seniority, work_mode columns to Anthropic scraper output"
```

---

### Task 4: Create scrape_ashby.py

**Files:**
- Create: `scrape_ashby.py`

**Step 1: Write scrape_ashby.py**

```python
#!/usr/bin/env python3
"""
Scrape salary ranges from an Ashby job board and export to CSV.

Usage:
  python scrape_ashby.py --company crusoe --out crusoe_salaries.csv
"""

from __future__ import annotations

import argparse
import csv
import html
import logging
import re
from typing import Any, Dict, List

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

import html2text
import requests

from classify import (
    SalaryParseResult,
    extract_salary_block_from_html,
    parse_salary_text,
    classify_seniority,
    classify_work_mode,
    normalize_department,
)


def _html_to_markdown(content_html: str) -> str:
    """Convert Ashby job HTML to clean markdown."""
    if not content_html:
        return ""
    unescaped = html.unescape(content_html)
    h = html2text.HTML2Text()
    h.body_width = 0
    h.ignore_images = True
    h.ignore_links = True
    md = h.handle(unescaped).strip()
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md


def scrape_all_jobs(company: str) -> List[Dict[str, Any]]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
    log.info("Fetching all jobs from Ashby API for %s ...", company)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    jobs = resp.json().get("jobs", [])
    log.info("Fetched %d jobs", len(jobs))
    return jobs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", required=True, help="Ashby company slug (e.g. crusoe)")
    ap.add_argument("--out", default=None, help="Output CSV path (default: {company}_salaries.csv)")
    args = ap.parse_args()

    out_path = args.out or f"{args.company}_salaries.csv"
    jobs = scrape_all_jobs(args.company)

    fieldnames = [
        "job_id",
        "title",
        "location",
        "url",
        "updated_at",
        "salary_text",
        "currency",
        "salary_min",
        "salary_max",
        "salary_unit",
        "department_raw",
        "department",
        "seniority",
        "work_mode",
        "description_md",
    ]

    rows = []
    for job in jobs:
        job_id = job.get("id")
        title = job.get("title")
        location = job.get("location", "")
        published_at = job.get("publishedAt")
        content_html = job.get("descriptionHtml", "")
        department_raw = job.get("department", "")
        job_url = job.get("jobUrl", "")
        is_remote = job.get("isRemote", False)
        workplace_type = job.get("workplaceType", "")

        # Work mode: use Ashby's structured fields
        if is_remote:
            work_mode = "Remote-Friendly"
        elif workplace_type == "Remote":
            work_mode = "Remote-Friendly"
        else:
            work_mode = classify_work_mode(location)

        salary_block = extract_salary_block_from_html(content_html or "")
        parsed = parse_salary_text(salary_block) if salary_block else SalaryParseResult("", None, None, None, None)
        description_md = _html_to_markdown(content_html or "")

        rows.append(
            {
                "job_id": job_id,
                "title": title,
                "location": location,
                "url": job_url,
                "updated_at": published_at,
                "salary_text": parsed.salary_text,
                "currency": parsed.currency,
                "salary_min": parsed.salary_min,
                "salary_max": parsed.salary_max,
                "salary_unit": parsed.salary_unit,
                "department_raw": department_raw,
                "department": normalize_department(department_raw),
                "seniority": classify_seniority(title),
                "work_mode": work_mode,
                "description_md": description_md,
            }
        )

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    with_salary = sum(1 for r in rows if r["salary_min"] is not None and r["salary_max"] is not None)
    log.info("Parsed salary ranges for %d / %d jobs", with_salary, len(rows))
    log.info("Wrote %s", out_path)


if __name__ == "__main__":
    main()
```

**Step 2: Test it against Crusoe**

Run: `python scrape_ashby.py --company crusoe --out /tmp/test_crusoe.csv`
Then: `head -2 /tmp/test_crusoe.csv` — verify fields present and populated

**Step 3: Commit**

```bash
git add scrape_ashby.py
git commit -m "feat: add Ashby job board scraper (first target: Crusoe)"
```

---

### Task 5: Update CLAUDE.md and run final verification

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update CLAUDE.md key files section**

Add `scrape_ashby.py` entry and update `classify.py` description to mention salary parsing and normalized departments.

**Step 2: Run both scrapers end-to-end**

Run: `python scrape_anthropic.py --out /tmp/final_anthropic.csv && python scrape_ashby.py --company crusoe --out /tmp/final_crusoe.csv`
Then: verify both CSVs have matching column schemas

**Step 3: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: all PASS

**Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for multi-company scraping support"
```
