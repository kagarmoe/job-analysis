#!/usr/bin/env python3
"""
Scrape jobs from a Workday job board (*.myworkdayjobs.com) and store to copper layer.

Usage:
  python -m job_analysis.scrape_workday --url https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from datetime import date
from urllib.parse import urlparse

from job_analysis import db
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

PAGE_SIZE = 20  # Workday's cap per list request
DELAY_SECONDS = 0.2  # between requests; a big board is ~100 list pages + one detail per job
CATEGORY_FACET = "jobFamilyGroup"  # "Job Category" on every tenant checked; becomes department


def parse_workday_url(url: str) -> dict | None:
    """{tenant}.wdN.myworkdayjobs.com/[locale/]{site}[/job/{location}/{title}_{reqId}]"""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host.endswith(".myworkdayjobs.com"):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
        parts = parts[1:]
    if not parts:
        return None
    job_id = parts[-1].rsplit("_", 1)[-1] if "job" in parts and "_" in parts[-1] else ""
    return {"company": host.split(".")[0].lower(), "host": host, "site": parts[0], "job_id": job_id}


def scrape_all_jobs(
    company: str, *, host: str, site: str, copper_base_dir: str = db.COPPER_DIR,
) -> tuple[list[dict], str]:
    """Page every job category, then fetch each job's detail. Returns (details, source_date)."""
    api = f"https://{host}/wday/cxs/{company}/{site}"
    source_date = date.today().strftime("%Y%m%d")
    copper_db = db.open_copper("workday", base_dir=copper_base_dir)
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "User-Agent": "JobBoardResearch/1.0"})

    def list_page(applied: dict, offset: int, key: str) -> dict:
        # The list API is a POST; copper's url records the query that produced each page.
        resp = session.post(f"{api}/jobs", json={"appliedFacets": applied, "limit": PAGE_SIZE,
                                                 "offset": offset, "searchText": ""}, timeout=30)
        resp.raise_for_status()
        db.store_copper(copper_db, url=f"{api}/jobs?{key}offset={offset}", http_status=resp.status_code,
                        content=resp.text, source_date=source_date)
        time.sleep(DELAY_SECONDS)
        return resp.json()

    log.info("Fetching job categories from Workday for %s/%s ...", company, site)
    first = list_page({}, 0, "")
    categories = next((f.get("values", []) for f in first.get("facets", [])
                       if f.get("facetParameter") == CATEGORY_FACET), [])
    queries = [({CATEGORY_FACET: [c["id"]]}, f"{CATEGORY_FACET}={c['id']}&") for c in categories] or [({}, "")]

    paths: list[str] = []
    for applied, key in queries:
        offset = 0
        page = first if not applied else list_page(applied, offset, key)
        while True:
            postings = page.get("jobPostings", [])
            paths += [p["externalPath"] for p in postings if p.get("externalPath")]
            if len(postings) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
            page = list_page(applied, offset, key)
    paths = list(dict.fromkeys(paths))
    log.info("Found %d jobs in %d categories; fetching details ...", len(paths), len(categories))

    details = []
    for i, path in enumerate(paths, 1):
        url = f"{api}{path}"
        if db.get_copper(copper_db, url, source_date) is not None:
            continue  # already fetched today: a re-run resumes instead of starting over
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("Skipping %s: %s", path, exc)
            continue
        db.store_copper(copper_db, url=url, http_status=resp.status_code,
                        content=resp.text, source_date=source_date)
        details.append(resp.json())
        if i % 100 == 0:
            log.info("  %d/%d details", i, len(paths))
        time.sleep(DELAY_SECONDS)
    log.info("Fetched %d job details", len(details))
    return details, source_date


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="Any board or job URL on *.myworkdayjobs.com")
    args = ap.parse_args()
    info = parse_workday_url(args.url)
    if not info:
        ap.error(f"not a Workday URL: {args.url}")
    jobs, source_date = scrape_all_jobs(info["company"], host=info["host"], site=info["site"])
    log.info("Stored %d jobs to copper for %s on %s", len(jobs), info["company"], source_date)


if __name__ == "__main__":
    main()
