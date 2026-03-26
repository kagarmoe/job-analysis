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
