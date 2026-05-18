#!/usr/bin/env python3
"""
Scrape jobs from an Ashby job board and store to copper layer.

Usage:
  python scrape_ashby.py --company pinecone
"""

from __future__ import annotations

import argparse
import html
import logging
import re
import sqlite3
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
    parse_json_ld_job_posting,
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


def scrape_all_jobs(company: str) -> tuple[list[dict], str, sqlite3.Connection]:
    """Returns (jobs, source_date, db). source_date = today as YYYYMMDD."""
    import copper as _copper
    from datetime import date
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
    log.info("Fetching all jobs from Ashby API for %s ...", company)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    source_date = date.today().strftime("%Y%m%d")
    db = _copper.open_db("ashby")
    _copper.store(db, url=url, http_status=resp.status_code,
                  content=resp.text, source_date=source_date)
    jobs = resp.json().get("jobs", [])
    log.info("Fetched %d jobs", len(jobs))
    return jobs, source_date, db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", required=True, help="Ashby company slug (e.g. crusoe)")
    args = ap.parse_args()
    jobs, source_date, _copper_db = scrape_all_jobs(args.company)
    log.info("Stored %d jobs to copper for %s on %s", len(jobs), args.company, source_date)


if __name__ == "__main__":
    main()
