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
from bs4 import BeautifulSoup
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


def fetch_snapshot(url: str, timestamp: str) -> str | None:
    """Fetch a specific Wayback Machine snapshot."""
    snapshot_url = f"{WEB_URL}/{timestamp}id_/{url}"
    try:
        resp = SESSION.get(snapshot_url, timeout=60)
        if resp.status_code == 200:
            return resp.text
        log.warning("Got status %d for %s", resp.status_code, snapshot_url)
    except requests.RequestException as e:
        log.warning("Failed to fetch %s: %s", snapshot_url, e)
    return None


def parse_job_page(html: str) -> dict:
    """Parse a Greenhouse job page for details."""
    soup = BeautifulSoup(html, "html.parser")
    result = {
        "title": "", "location": "", "department": "",
        "salary_text": "", "salary_min": None, "salary_max": None,
        "currency": "", "salary_unit": "",
    }

    # Title
    h1 = soup.find("h1")
    if h1:
        result["title"] = h1.get_text(strip=True)

    # Location
    loc_el = soup.find("div", class_=lambda c: c and "location" in c.lower())
    if loc_el:
        result["location"] = loc_el.get_text(strip=True)

    # Department
    dept_el = soup.find("div", class_=lambda c: c and "department" in c.lower())
    if dept_el:
        result["department"] = dept_el.get_text(strip=True)

    # Salary
    pay_el = soup.find("div", class_=lambda c: c and (
        "pay" in c.lower() or "salary" in c.lower() or "compensation" in c.lower()
    ))
    if pay_el:
        result["salary_text"] = pay_el.get_text(" ", strip=True)
    else:
        text = soup.get_text(" ", strip=True)
        m = re.search(r'(Annual Salary|compensation).{0,20}[\$€£][\d,.\s]+', text, re.I)
        if m:
            result["salary_text"] = text[max(0, m.start()):min(len(text), m.end() + 80)]

    if result["salary_text"]:
        _parse_salary_numbers(result)

    return result


def parse_ashby_page(html_text: str) -> dict:
    """Parse an Ashby job page for details (React SPA, try JSON-LD first)."""
    result = {
        "title": "", "location": "", "department": "",
        "salary_text": "", "salary_min": None, "salary_max": None,
        "currency": "", "salary_unit": "",
    }
    soup = BeautifulSoup(html_text, "html.parser")

    # Try JSON-LD first (structured data, most reliable)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if data.get("@type") == "JobPosting":
                result["title"] = data.get("title", "")
                loc = data.get("jobLocation", {})
                if isinstance(loc, dict):
                    addr = loc.get("address", {})
                    result["location"] = f"{addr.get('addressLocality', '')}, {addr.get('addressRegion', '')}"
                break
        except (json.JSONDecodeError, TypeError):
            continue

    # Fall back to HTML text for salary
    text = soup.get_text(" ", strip=True)
    m = re.search(r"Compensation will be[^.]*\$[^.]+\.", text, re.I)
    if m:
        result["salary_text"] = m.group(0)

    if result["salary_text"]:
        _parse_salary_numbers(result)

    return result


def _parse_salary_numbers(result: dict) -> None:
    text = result["salary_text"]

    if re.search(r"\bAnnual\b|\bper year\b|\byearly\b", text, re.I):
        result["salary_unit"] = "annual"
    elif re.search(r"\bhour\b|\bhourly\b", text, re.I):
        result["salary_unit"] = "hourly"

    m_code = re.search(r"\b(USD|EUR|GBP|CAD|AUD)\b", text)
    if m_code:
        result["currency"] = m_code.group(1)

    sym_match = re.search(r"[\$£€]", text)
    sym = sym_match.group(0) if sym_match else None
    if not result["currency"] and sym:
        result["currency"] = {"$": "USD", "€": "EUR", "£": "GBP"}.get(sym, "")

    dash = r"(?:\u2013|\u2014|-|\s+to\s+)"

    m = re.search(
        rf"[\$£€]\s*(\d{{1,3}}(?:,\d{{3}})+)\s*{dash}\s*[\$£€]?\s*(\d{{1,3}}(?:,\d{{3}})+)",
        text,
    )
    if m:
        result["salary_min"] = int(m.group(1).replace(",", ""))
        result["salary_max"] = int(m.group(2).replace(",", ""))
        return

    m2 = re.search(
        rf"[\$£€]\s*(\d{{1,3}}(?:\.\d{{3}})+)\s*{dash}\s*[\$£€]?\s*(\d{{1,3}}(?:\.\d{{3}})+)",
        text,
    )
    if m2:
        result["salary_min"] = int(m2.group(1).replace(".", ""))
        result["salary_max"] = int(m2.group(2).replace(".", ""))


def load_progress(progress_file: Path) -> dict:
    if progress_file.exists():
        return json.loads(progress_file.read_text())
    return {"fetched_jobs": {}, "job_index": None}


def save_progress(state: dict, progress_file: Path) -> None:
    progress_file.write_text(json.dumps(state, default=str))


def step1_build_job_index(job_url_patterns: list[str], board: str) -> dict[str, dict]:
    """
    Query CDX for all archived individual job page URLs.
    Returns: {job_id: {"url": clean_url, "first_seen": ts, "last_seen": ts}}
    No page fetching — only CDX API calls.
    """
    log.info("Step 1: Building job index from CDX (no page fetches)...")
    job_index: dict[str, dict] = {}

    for pattern in job_url_patterns:
        log.info("  Querying CDX for %s", pattern)
        results = cdx_query(pattern, filter="statuscode:200")
        log.info("  Found %d archived page hits", len(results))

        for row in results:
            if board == "greenhouse":
                m = re.search(r"/jobs/(\d+)", row["original"])
            elif board == "ashby":
                m = re.search(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", row["original"])
            else:
                m = None

            if not m:
                continue
            jid = m.group(1)
            clean_url = re.sub(r"\?.*$", "", row["original"])
            ts = row["timestamp"]

            if jid not in job_index:
                job_index[jid] = {
                    "url": clean_url,
                    "first_seen": ts[:8],
                    "last_seen": ts[:8],
                    "best_timestamp": ts,
                }
            else:
                if ts[:8] < job_index[jid]["first_seen"]:
                    job_index[jid]["first_seen"] = ts[:8]
                    job_index[jid]["best_timestamp"] = ts  # prefer earliest
                if ts[:8] > job_index[jid]["last_seen"]:
                    job_index[jid]["last_seen"] = ts[:8]

    log.info("Step 1 complete: %d unique job IDs", len(job_index))
    return job_index


def step2_fetch_job_details(
    job_index: dict[str, dict],
    progress: dict,
    board: str,
    progress_file: Path,
) -> list[JobRecord]:
    """Fetch one snapshot per job to extract details."""
    fetched: dict = progress.get("fetched_jobs", {})
    records: list[JobRecord] = []
    to_fetch = sorted(set(job_index.keys()) - set(fetched.keys()))

    log.info("Step 2: Fetching details for %d jobs (%d already done)...",
             len(to_fetch), len(fetched))

    # Reconstruct already-fetched records
    for jid, data in fetched.items():
        rec = JobRecord(job_id=jid, **data)
        idx = job_index.get(jid, {})
        rec.first_seen = idx.get("first_seen", rec.first_seen)
        rec.last_seen = idx.get("last_seen", rec.last_seen)
        records.append(rec)

    for i, jid in enumerate(to_fetch):
        idx = job_index[jid]
        url = idx["url"]
        ts = idx["best_timestamp"]

        log.info("  [%d/%d] Fetching job %s", i + 1, len(to_fetch), jid)
        html = fetch_snapshot(url, ts)

        rec = JobRecord(job_id=jid, first_seen=idx["first_seen"], last_seen=idx["last_seen"])

        if html:
            if board == "greenhouse":
                details = parse_job_page(html)
            elif board == "ashby":
                details = parse_ashby_page(html)
            else:
                details = parse_job_page(html)

            rec.title = details["title"]
            rec.location = details["location"]
            rec.department = details["department"]
            rec.salary_text = details["salary_text"]
            rec.salary_min = details["salary_min"]
            rec.salary_max = details["salary_max"]
            rec.currency = details["currency"]
            rec.salary_unit = details["salary_unit"]
            rec.snapshot_url = f"{WEB_URL}/{ts}/{url}"
        else:
            log.warning("    Could not fetch job %s", jid)

        records.append(rec)

        # Save progress
        fetched[jid] = {
            "title": rec.title, "location": rec.location, "department": rec.department,
            "salary_text": rec.salary_text, "salary_min": rec.salary_min,
            "salary_max": rec.salary_max, "currency": rec.currency,
            "salary_unit": rec.salary_unit, "first_seen": rec.first_seen,
            "last_seen": rec.last_seen, "snapshot_url": rec.snapshot_url,
        }
        if (i + 1) % 10 == 0:
            progress["fetched_jobs"] = fetched
            save_progress(progress, progress_file)
            log.info("    Progress saved (%d/%d)", i + 1, len(to_fetch))

        time.sleep(REQUEST_DELAY)

    # Final save
    progress["fetched_jobs"] = fetched
    save_progress(progress, progress_file)

    return records


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


def main():
    ap = argparse.ArgumentParser(description="Scrape historical job postings from the Wayback Machine")
    ap.add_argument("--board", required=True, choices=["greenhouse", "ashby"])
    ap.add_argument("--company", required=True, help="Company slug")
    ap.add_argument("--out", default=None, help="Output CSV path")
    args = ap.parse_args()

    out_path = Path(args.out or f"{args.company}_salaries_historical.csv")
    current_csv = Path(f"{args.company}_salaries.csv")
    progress_file = Path(f".wayback_progress_{args.company}.json")

    if args.board == "greenhouse":
        job_url_patterns = [
            f"boards.greenhouse.io/{args.company}/jobs/*",
            f"job-boards.greenhouse.io/{args.company}/jobs/*",
        ]
    elif args.board == "ashby":
        job_url_patterns = [
            f"jobs.ashbyhq.com/{args.company}/*",
        ]

    progress = load_progress(progress_file)

    # Step 1: Build index from CDX (fast, no page fetches)
    if progress.get("job_index"):
        job_index = progress["job_index"]
        log.info("Loaded job index from progress: %d jobs", len(job_index))
    else:
        job_index = step1_build_job_index(job_url_patterns, args.board)
        progress["job_index"] = job_index
        save_progress(progress, progress_file)

    # Step 2: Fetch individual job details (resumable)
    records = step2_fetch_job_details(job_index, progress, args.board, progress_file)

    # Mark active vs closed
    mark_active_jobs(records, current_csv)

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
