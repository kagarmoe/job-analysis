#!/usr/bin/env python3
"""
Scrape jobs from any Greenhouse job board and store to copper layer.

Usage:
  python scrape_greenhouse.py --company anthropic
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

import db
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def scrape_all_jobs(company: str) -> tuple[list[dict], str]:
    """Returns (jobs, source_date). source_date = today as YYYYMMDD."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
    log.info("Fetching all jobs from Greenhouse API for %s ...", company)
    resp = requests.get(url, params={"content": "true"}, timeout=30)
    resp.raise_for_status()
    source_date = date.today().strftime("%Y%m%d")
    copper_db = db.open_copper("greenhouse")
    db.store_copper(copper_db, url=url, http_status=resp.status_code,
                    content=resp.text, source_date=source_date)
    jobs = resp.json().get("jobs", [])
    log.info("Fetched %d jobs", len(jobs))
    return jobs, source_date


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", required=True)
    args = ap.parse_args()
    jobs, source_date = scrape_all_jobs(args.company)
    log.info("Stored %d jobs to copper for %s on %s", len(jobs), args.company, source_date)


if __name__ == "__main__":
    main()
