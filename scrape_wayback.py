"""
Scrape historical job postings from the Wayback Machine.

Supports Greenhouse and Ashby job boards for any company.

Strategy (optimized to minimize requests):
1. Query CDX API for all archived individual job page URLs — this gives us every
   unique job ID plus the timestamps it was seen, with ZERO page fetches.
2. For each unique job ID, fetch ONE archived snapshot to extract title, location,
   salary, and department.
3. Use CDX timestamps as first_seen/last_seen, compare against current live data
   to determine which jobs are closed.
"""

import argparse
import csv
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CDX_URL = "https://web.archive.org/cdx/search/cdx"
WEB_URL = "https://web.archive.org/web"

REQUEST_DELAY = 2.5  # seconds between page fetches
MAX_RETRIES = 5
BACKOFF_FACTOR = 5  # 5s, 10s, 20s, 40s, 80s


@dataclass
class JobRecord:
    job_id: str
    title: str = ""
    location: str = ""
    department: str = ""
    salary_text: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    currency: str = ""
    salary_unit: str = ""
    first_seen: str = ""
    last_seen: str = ""
    is_active: bool = False
    snapshot_url: str = ""


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=[429, 500, 502, 503, 504, 520, 521, 522, 523, 524],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "JobBoardResearch/1.0 (academic research)",
        "Accept": "text/html,application/json",
    })
    return session


SESSION = _build_session()


def cdx_query(url: str, **params) -> list[dict]:
    """Query the Wayback Machine CDX API (lightweight, no page fetching)."""
    defaults = {"output": "json", "fl": "timestamp,original,statuscode"}
    defaults.update(params)
    for attempt in range(3):
        try:
            resp = SESSION.get(CDX_URL, params={"url": url, **defaults}, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            if len(data) <= 1:
                return []
            headers = data[0]
            return [dict(zip(headers, row)) for row in data[1:]]
        except Exception as e:
            log.warning("CDX query attempt %d failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
    return []




def mark_active_jobs(records: list[JobRecord], current_csv: Path) -> None:
    if not current_csv.exists():
        return
    current_ids = set()
    with open(current_csv) as f:
        for row in csv.DictReader(f):
            current_ids.add(row.get("job_id", ""))
    for rec in records:
        rec.is_active = rec.job_id in current_ids


def write_csv(records: list[JobRecord], path: Path) -> None:
    fields = [
        "job_id", "title", "location", "department",
        "salary_min", "salary_max", "currency", "salary_unit",
        "first_seen", "last_seen", "is_active", "snapshot_url",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for rec in sorted(records, key=lambda r: r.first_seen):
            writer.writerow({
                "job_id": rec.job_id,
                "title": rec.title,
                "location": rec.location,
                "department": rec.department,
                "salary_min": rec.salary_min if rec.salary_min else "",
                "salary_max": rec.salary_max if rec.salary_max else "",
                "currency": rec.currency,
                "salary_unit": rec.salary_unit,
                "first_seen": rec.first_seen,
                "last_seen": rec.last_seen,
                "is_active": rec.is_active,
                "snapshot_url": rec.snapshot_url,
            })
    log.info("Wrote %d records to %s", len(records), path)


def _extract_job_fields(job: dict, board: str) -> dict:
    """Extract normalized fields from a single job JSON object. Board-specific."""
    if board == "ashby":
        return {
            "job_id": str(job.get("id", "")),
            "title": job.get("title", ""),
            "location": job.get("location", ""),
            "department": job.get("department", ""),
            "content_html": job.get("descriptionHtml", ""),
        }
    else:  # greenhouse
        return {
            "job_id": str(job.get("id", "")),
            "title": job.get("title", ""),
            "location": (job.get("location") or {}).get("name", ""),
            "department": "",  # Greenhouse doesn't provide department in API
            "content_html": job.get("content", ""),
        }


def scrape_api_snapshots(board: str, company: str, current_csv: Path) -> list[JobRecord]:
    """
    Fetch archived API snapshots from the Wayback Machine.

    Works for both Greenhouse and Ashby. Fetches the full job board API endpoint
    snapshots — each contains all jobs with descriptions for salary parsing.
    """
    from classify import (
        SalaryParseResult, extract_salary_block_from_html, parse_salary_text,
    )

    if board == "ashby":
        api_url = f"api.ashbyhq.com/posting-api/job-board/{company}"
    else:
        api_url = f"boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"

    log.info("Querying CDX for archived %s API snapshots: %s", board, api_url)
    results = cdx_query(api_url, filter="statuscode:200")

    # For Greenhouse, also check without query params (CDX sometimes strips them)
    if board == "greenhouse":
        alt_url = f"boards-api.greenhouse.io/v1/boards/{company}/jobs"
        alt_results = cdx_query(alt_url, filter="statuscode:200")
        # Deduplicate by timestamp
        seen = {r["timestamp"] for r in results}
        for r in alt_results:
            if r["timestamp"] not in seen:
                results.append(r)
                seen.add(r["timestamp"])
        # Sort by timestamp
        results.sort(key=lambda r: r["timestamp"])

    log.info("Found %d API snapshots", len(results))

    if not results:
        return []

    all_jobs: dict[str, JobRecord] = {}

    for i, row in enumerate(results):
        ts = row["timestamp"]
        url = row["original"]
        # For Greenhouse, ensure content=true is in the URL
        if board == "greenhouse" and "content=true" not in url:
            url = url.rstrip("/") + "?content=true"
        date_str = ts[:8]

        log.info("  [%d/%d] Fetching API snapshot from %s-%s-%s",
                 i + 1, len(results), date_str[:4], date_str[4:6], date_str[6:8])

        try:
            # Try id_ first (raw JSON), fall back to without (some hosts need it)
            data = None
            for mode in ["id_/", ""]:
                snapshot_url = f"{WEB_URL}/{ts}{mode}{url}"
                resp = SESSION.get(snapshot_url, timeout=60)
                if resp.status_code != 200:
                    continue
                if resp.text.lstrip()[:1] == "{":
                    data = resp.json()
                    break

            if data is None:
                log.warning("    Could not get JSON, skipping")
                continue
            jobs = data.get("jobs", [])
            log.info("    Found %d jobs in snapshot", len(jobs))

            for job in jobs:
                fields = _extract_job_fields(job, board)
                jid = fields["job_id"]
                if not jid:
                    continue

                content_html = fields["content_html"]
                salary_block = extract_salary_block_from_html(content_html or "")
                parsed = parse_salary_text(salary_block) if salary_block else SalaryParseResult("", None, None, None, None)

                if jid not in all_jobs:
                    all_jobs[jid] = JobRecord(
                        job_id=jid,
                        title=fields["title"],
                        location=fields["location"],
                        department=fields["department"],
                        salary_text=parsed.salary_text,
                        salary_min=parsed.salary_min,
                        salary_max=parsed.salary_max,
                        currency=parsed.currency or "",
                        salary_unit=parsed.salary_unit or "",
                        first_seen=date_str,
                        last_seen=date_str,
                        snapshot_url=snapshot_url,
                    )
                else:
                    rec = all_jobs[jid]
                    if date_str < rec.first_seen:
                        rec.first_seen = date_str
                    if date_str > rec.last_seen:
                        rec.last_seen = date_str
                    if not rec.salary_min and parsed.salary_min:
                        rec.salary_text = parsed.salary_text
                        rec.salary_min = parsed.salary_min
                        rec.salary_max = parsed.salary_max
                        rec.currency = parsed.currency or ""
                        rec.salary_unit = parsed.salary_unit or ""

        except Exception as e:
            log.warning("    Failed to parse snapshot: %s", e)
            continue

        time.sleep(REQUEST_DELAY)

    records = list(all_jobs.values())
    mark_active_jobs(records, current_csv)

    log.info("API snapshots: %d unique jobs across %d snapshots", len(records), len(results))
    return records


def main():
    ap = argparse.ArgumentParser(description="Scrape historical job postings from the Wayback Machine")
    ap.add_argument("--board", required=True, choices=["greenhouse", "ashby"])
    ap.add_argument("--company", required=True, help="Company slug")
    ap.add_argument("--out", default=None, help="Output CSV path")
    args = ap.parse_args()

    out_path = Path(args.out or f"{args.company}_salaries_historical.csv")
    current_csv = Path(f"{args.company}_salaries.csv")
    progress_file = Path(f".wayback_progress_{args.company}.json")

    records = scrape_api_snapshots(args.board, args.company, current_csv)

    # Write output
    write_csv(records, out_path)

    # Summary
    total = len(records)
    with_salary = sum(1 for r in records if r.salary_min)
    active = sum(1 for r in records if r.is_active)
    closed = total - active
    log.info("=" * 60)
    log.info("SUMMARY")
    log.info("  Total unique jobs: %d", total)
    log.info("  With salary data:  %d", with_salary)
    log.info("  Currently active:  %d", active)
    log.info("  Closed/filled:     %d", closed)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
