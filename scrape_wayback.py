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
import html as _html
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import copper
from classify import (
    SalaryParseResult,
    extract_salary_block_from_html,
    parse_salary_text,
    parse_json_ld_job_posting,
)

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
    url: str = ""
    updated_at: str = ""
    salary_text: str = ""
    currency: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    salary_unit: str = ""
    description_md: str = ""
    department: str = ""
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
        log.info("CDX attempt %d/3: %s", attempt + 1, url)
        try:
            resp = SESSION.get(CDX_URL, params={"url": url, **defaults}, timeout=60)
            log.info("CDX response: HTTP %d  (%d bytes)", resp.status_code, len(resp.content))
            resp.raise_for_status()
            data = resp.json()
            if len(data) <= 1:
                log.info("CDX: no results")
                return []
            log.info("CDX: %d rows", len(data) - 1)
            headers = data[0]
            return [dict(zip(headers, row)) for row in data[1:]]
        except Exception as e:
            log.warning("CDX attempt %d/3 failed: %s", attempt + 1, e)
            if attempt < 2:
                wait = 10 * (attempt + 1)
                log.info("CDX: retrying in %ds", wait)
                time.sleep(wait)
    log.warning("CDX: all attempts failed, returning empty")
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
    # Schema is a superset of *_salaries.csv: all live columns + historical tracking columns.
    fields = [
        "job_id", "title", "location", "url", "updated_at",
        "salary_text", "currency", "salary_min", "salary_max", "salary_unit",
        "description_md", "first_seen", "last_seen", "is_active", "snapshot_url",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for rec in sorted(records, key=lambda r: r.first_seen):
            writer.writerow({
                "job_id": rec.job_id,
                "title": rec.title,
                "location": rec.location,
                "url": rec.url,
                "updated_at": rec.updated_at,
                "salary_text": rec.salary_text,
                "currency": rec.currency,
                "salary_min": rec.salary_min if rec.salary_min else "",
                "salary_max": rec.salary_max if rec.salary_max else "",
                "salary_unit": rec.salary_unit,
                "description_md": rec.description_md,
                "first_seen": rec.first_seen,
                "last_seen": rec.last_seen,
                "is_active": rec.is_active,
                "snapshot_url": rec.snapshot_url,
            })
    log.info("Wrote %d records to %s", len(records), path)


def _extract_job_fields(job: dict, board: str) -> dict:
    """Normalize a single job JSON object to canonical field names.

    Maps board-specific field names to the shared JobRecord schema so the rest
    of the scraper is source-agnostic. Missing fields default to empty string.

    Canonical keys returned: job_id, title, location, url, department, content_html.
    content_html is the raw description HTML; callers extract salary_text and
    description_md from it.
    """
    if board == "ashby":
        loc_parts = []
        if job.get("location"):
            loc_parts.append(job["location"])
        for sec in job.get("secondaryLocations") or []:
            if sec.get("location"):
                loc_parts.append(sec["location"])
        return {
            "job_id": str(job.get("id", "")),
            "title": job.get("title", ""),
            "location": " | ".join(loc_parts),
            "url": job.get("jobUrl", ""),
            "department": job.get("department") or job.get("team") or "",
            "content_html": job.get("descriptionHtml", ""),
        }
    else:  # greenhouse
        locs = [job.get("location") or {}]
        loc_str = " | ".join(l.get("name", "") for l in locs if l.get("name"))
        jid = str(job.get("id", ""))
        return {
            "job_id": jid,
            "title": job.get("title", ""),
            "location": loc_str,
            "url": job.get("absolute_url", ""),
            "department": "",
            "content_html": job.get("content", ""),
        }


_UUID_RE = re.compile(
    r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:[/?]|$)"
)

_TITLE_TAG_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)


def _title_from_html(html_text: str) -> str:
    """Extract job title from <title> tag, stripping ' | Company' suffix."""
    m = _TITLE_TAG_RE.search(html_text)
    if not m:
        return ""
    title = _html.unescape(m.group(1)).strip()
    return title.split(" | ")[0].strip() if " | " in title else title


def _fetch_snapshot(
    copper_db: "sqlite3.Connection",
    job_id: str,
    ts: str,          # CDX timestamp — this IS the source_date
    page_type: str,
    orig_url: str,
) -> tuple[str | None, str]:
    """Return (content, wayback_url), reading copper cache first."""
    cached = copper.get_content(copper_db, orig_url, ts)
    if cached is not None:
        log.info("    [cached] %s", page_type)
        return cached, f"{WEB_URL}/{ts}id_/{orig_url}"

    for mode in ["id_/", ""]:
        wayback_url = f"{WEB_URL}/{ts}{mode}{orig_url}"
        try:
            resp = SESSION.get(wayback_url, timeout=60)
            log.info("    HTTP %d (%d bytes) [%s]", resp.status_code, len(resp.content), mode or "plain")
            if resp.status_code == 200:
                copper.store(copper_db, url=orig_url, http_status=resp.status_code,
                             content=resp.text, source_date=ts)
                return resp.text, wayback_url
        except Exception as e:
            log.warning("    fetch error: %s", e)
        time.sleep(REQUEST_DELAY)
    return None, ""


def _scrape_ashby_individual_fallback(company: str) -> list[JobRecord]:
    """
    Fallback for Ashby boards where the board-level API was never archived.

    Copper write stub — raw fetches are stored to copper; derivation (bronze)
    and JobRecord construction move to later medallion tasks.
    Returns [] for now; the CSV will have no fallback rows.
    """
    copper_db = copper.open_db("ashby")

    # --- 1. Single CDX query: job pages + application pages ---
    html_rows = cdx_query(f"jobs.ashbyhq.com/{company}/*", filter="statuscode:200")
    log.info("Fallback CDX (HTML pages): %d rows", len(html_rows))

    job_timestamps: dict[str, dict] = {}
    app_snaps: dict[str, list[tuple[str, str]]] = {}   # job_id -> [(ts, orig_url)]
    page_snaps: dict[str, list[tuple[str, str]]] = {}  # job_id -> [(ts, orig_url)]

    for row in html_rows:
        url = row["original"]
        m = _UUID_RE.search(url)
        if not m:
            continue
        jid, ts = m.group(1), row["timestamp"]
        date_str = ts[:8]

        if url.rstrip("/").endswith("/application"):
            app_snaps.setdefault(jid, []).append((ts, url))
        else:
            page_snaps.setdefault(jid, []).append((ts, url))

        if jid not in job_timestamps:
            job_timestamps[jid] = {"first_seen": date_str, "last_seen": date_str}
        else:
            if date_str < job_timestamps[jid]["first_seen"]:
                job_timestamps[jid]["first_seen"] = date_str
            if date_str > job_timestamps[jid]["last_seen"]:
                job_timestamps[jid]["last_seen"] = date_str

    log.info(
        "Discovered %d unique job IDs  (%d /application  %d {id} page snapshots)",
        len(job_timestamps), len(app_snaps), len(page_snaps),
    )
    if not job_timestamps:
        return []

    # --- 2. Individual API snapshots (separate CDX query) ---
    api_rows = cdx_query(
        f"api.ashbyhq.com/posting-api/job-board/{company}/job/*",
        filter="statuscode:200",
    )
    log.info("Fallback CDX (individual API): %d rows", len(api_rows))

    api_snaps: dict[str, list[tuple[str, str]]] = {}
    for row in api_rows:
        m = _UUID_RE.search(row["original"])
        if not m:
            continue
        api_snaps.setdefault(m.group(1), []).append((row["timestamp"], row["original"]))

    log.info(
        "Sources: api=%d  /application=%d  {id}=%d",
        len(api_snaps), len(app_snaps), len(page_snaps),
    )

    # --- 3. Fetch and store to copper (derivation deferred to bronze task) ---
    total = len(job_timestamps)
    for i, (jid, ts_info) in enumerate(job_timestamps.items(), 1):
        log.info("  [%d/%d] %s  first=%s  last=%s", i, total, jid,
                 ts_info["first_seen"], ts_info["last_seen"])

        if jid in api_snaps:
            ts, orig_url = api_snaps[jid][0]
            _fetch_snapshot(copper_db, jid, ts, "api_job", orig_url)
        elif jid in app_snaps:
            ts, orig_url = app_snaps[jid][0]
            _fetch_snapshot(copper_db, jid, ts, "application", orig_url)
        elif jid in page_snaps:
            ts, orig_url = page_snaps[jid][0]
            _fetch_snapshot(copper_db, jid, ts, "job_page", orig_url)

    return []


def scrape_api_snapshots(board: str, company: str, current_csv: Path) -> list[JobRecord]:
    """
    Fetch archived API snapshots from the Wayback Machine.

    Works for both Greenhouse and Ashby. Fetches the full job board API endpoint
    snapshots — each contains all jobs with descriptions for salary parsing.
    Falls back to per-job scraping for Ashby boards where the board-level API
    was never archived: tries individual API snapshots, then /application page
    JSON-LD (which carries clean baseSalary structured data), then stubs.
    """

    copper_db = copper.open_db(board)

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
        if board == "ashby":
            log.info("No board-level API snapshots; trying individual job fallback")
            return _scrape_ashby_individual_fallback(company)
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
            snapshot_url = ""
            for mode in ["id_/", ""]:
                snapshot_url = f"{WEB_URL}/{ts}{mode}{url}"
                resp = SESSION.get(snapshot_url, timeout=60)
                if resp.status_code != 200:
                    continue
                if resp.text.lstrip()[:1] == "{":
                    data = resp.json()
                    copper.store(copper_db, url=url, http_status=resp.status_code,
                                 content=resp.text, source_date=ts)
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

                content_html = fields["content_html"] or ""
                salary_block = extract_salary_block_from_html(content_html)
                parsed = parse_salary_text(salary_block) if salary_block else SalaryParseResult("", None, None, None, None)

                if jid not in all_jobs:
                    all_jobs[jid] = JobRecord(
                        job_id=jid,
                        title=fields["title"],
                        location=fields["location"],
                        url=fields["url"],
                        salary_text=parsed.salary_text or salary_block or "",
                        currency=parsed.currency or "",
                        salary_min=parsed.salary_min,
                        salary_max=parsed.salary_max,
                        salary_unit=parsed.salary_unit or "",
                        description_md=content_html,
                        department=fields["department"],
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
                        rec.salary_text = parsed.salary_text or salary_block or ""
                        rec.salary_min = parsed.salary_min
                        rec.salary_max = parsed.salary_max
                        rec.currency = parsed.currency or ""
                        rec.salary_unit = parsed.salary_unit or ""
                    if not rec.description_md and content_html:
                        rec.description_md = content_html

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
