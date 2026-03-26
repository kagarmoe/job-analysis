#!/usr/bin/env python3
"""
Scrape salary ranges from any Greenhouse job board and export to CSV.

Usage:
  python scrape_greenhouse.py --company anthropic
  python scrape_greenhouse.py --company anthropic --out anthropic_salaries.csv
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
    SalaryParseResult, extract_salary_block_from_html, parse_salary_text,
    classify_department, classify_seniority, classify_work_mode, normalize_department,
)



def _html_to_markdown(content_html: str) -> str:
    """Convert Greenhouse job HTML to clean markdown."""
    if not content_html:
        return ""
    unescaped = html.unescape(content_html)
    h = html2text.HTML2Text()
    h.body_width = 0
    h.ignore_images = True
    h.ignore_links = True
    md = h.handle(unescaped).strip()
    # Collapse 3+ blank lines
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md


def greenhouse_job_url(company: str, job_id: int) -> str:
    return f"https://job-boards.greenhouse.io/{company}/jobs/{job_id}"


def scrape_all_jobs(company: str) -> List[Dict[str, Any]]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
    log.info("Fetching all jobs from Greenhouse API for %s ...", company)
    resp = requests.get(url, params={"content": "true"}, timeout=30)
    resp.raise_for_status()
    jobs = resp.json().get("jobs", [])
    log.info("Fetched %d jobs", len(jobs))
    return jobs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", required=True, help="Greenhouse company slug (e.g. anthropic)")
    ap.add_argument("--out", default=None)
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
        location = (job.get("location") or {}).get("name")
        updated_at = job.get("updated_at")
        content_html = job.get("content", "")

        salary_block = extract_salary_block_from_html(content_html or "")
        parsed = parse_salary_text(salary_block) if salary_block else SalaryParseResult("", None, None, None, None)
        description_md = _html_to_markdown(content_html or "")
        department_raw = classify_department(title)

        rows.append(
            {
                "job_id": job_id,
                "title": title,
                "location": location,
                "url": greenhouse_job_url(args.company, job_id),
                "updated_at": updated_at,
                "salary_text": parsed.salary_text,
                "currency": parsed.currency,
                "salary_min": parsed.salary_min,
                "salary_max": parsed.salary_max,
                "salary_unit": parsed.salary_unit,
                "department_raw": department_raw,
                "department": normalize_department(department_raw),
                "seniority": classify_seniority(title),
                "work_mode": classify_work_mode(location),
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
