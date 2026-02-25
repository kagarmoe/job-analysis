#!/usr/bin/env python3
"""
Fetch job description content for historical content-family roles from the
Wayback Machine and add description_md to the historical CSV.

Only fetches for roles matching the content-family patterns used in
analyze_role_gap.ipynb. Respects Wayback Machine rate limits (2.5s delay).

Usage:
  python fetch_historical_descriptions.py
"""

import csv
import html
import logging
import re
import time
from pathlib import Path

import html2text
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

HIST_CSV = Path("anthropic_salaries_historical.csv")
REQUEST_DELAY = 2.5

# Same patterns as analyze_role_gap.ipynb
CONTENT_FAMILY_PATTERNS = [
    r"content.*knowledge|knowledge.*management",
    r"certification content|training content",
    r"content (designer|design|developer|engineer|lead|marketing|manager)",
    r"copy and content",
    r"technical video content",
    r"technical (documentation|writer|writing)",
    r"prompt engineer.*librarian",
    r"\bcopywriter\b",
    r"\beditorial\b|managing editor",
    r"developer education|consumer education",
]


def is_content_family(title: str) -> bool:
    if not title:
        return False
    if re.search(r"brand designer", title, re.I):
        return False
    return any(re.search(p, title, re.I) for p in CONTENT_FAMILY_PATTERNS)


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=5,
        status_forcelist=[429, 500, 502, 503, 504, 520, 521, 522, 523, 524],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "AnthropicSalaryResearch/1.0 (academic research)",
        "Accept": "text/html",
    })
    return session


def _html_to_markdown(content_html: str) -> str:
    """Convert HTML to clean markdown — same as scrape_anthropic.py."""
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


def extract_description_from_greenhouse_page(page_html: str) -> str:
    """Extract the job description from a Greenhouse job board page."""
    soup = BeautifulSoup(page_html, "html.parser")

    # Greenhouse uses div#content for the job description body
    content_div = soup.find("div", id="content")
    if content_div:
        return _html_to_markdown(str(content_div))

    # Fallback: look for the main job description section
    # New Greenhouse layout uses different class names
    for selector in [
        {"class_": re.compile(r"job[-_]?description", re.I)},
        {"class_": re.compile(r"body", re.I)},
        {"id": "app_body"},
    ]:
        el = soup.find("div", **selector)
        if el:
            return _html_to_markdown(str(el))

    # Last resort: grab everything inside the main content area
    main = soup.find("main") or soup.find("article")
    if main:
        return _html_to_markdown(str(main))

    # Very last resort: full page minus scripts/styles
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    body = soup.find("body")
    if body:
        return _html_to_markdown(str(body))

    return ""


def fetch_snapshot_raw(session: requests.Session, snapshot_url: str) -> str | None:
    """Fetch a Wayback Machine snapshot, using id_ for raw content."""
    # Convert URL to id_ format to skip Wayback toolbar
    raw_url = re.sub(
        r"(web\.archive\.org/web/\d+)/",
        r"\1id_/",
        snapshot_url,
    )
    try:
        resp = session.get(raw_url, timeout=60)
        if resp.status_code == 200:
            return resp.text
        log.warning("Got status %d for %s", resp.status_code, raw_url)
    except requests.RequestException as e:
        log.warning("Failed to fetch %s: %s", raw_url, e)
    return None


def main():
    # Read existing CSV
    rows = []
    with open(HIST_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)

    log.info("Loaded %d rows from %s", len(rows), HIST_CSV)

    # Add description_md field if not present
    if "description_md" not in fieldnames:
        fieldnames = list(fieldnames) + ["description_md"]

    # Identify content-family rows that need fetching
    to_fetch = []
    for i, row in enumerate(rows):
        if is_content_family(row.get("title", "")):
            # Skip if already has description
            if row.get("description_md", "").strip():
                continue
            if row.get("snapshot_url", "").strip():
                to_fetch.append(i)

    log.info("Content-family roles needing description: %d", len(to_fetch))

    if not to_fetch:
        log.info("Nothing to fetch.")
        return

    session = _build_session()

    for n, idx in enumerate(to_fetch):
        row = rows[idx]
        title = row.get("title", "")
        snapshot_url = row.get("snapshot_url", "")
        job_id = row.get("job_id", "")

        log.info("[%d/%d] Fetching %s — %s", n + 1, len(to_fetch), job_id, title)

        page_html = fetch_snapshot_raw(session, snapshot_url)
        if page_html:
            desc_md = extract_description_from_greenhouse_page(page_html)
            rows[idx]["description_md"] = desc_md
            if desc_md:
                log.info("  Got %d chars of description", len(desc_md))
            else:
                log.warning("  Could not extract description from page")
        else:
            rows[idx]["description_md"] = ""
            log.warning("  Failed to fetch snapshot")

        time.sleep(REQUEST_DELAY)

    # Write back
    with open(HIST_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    fetched_ok = sum(1 for i in to_fetch if rows[i].get("description_md", "").strip())
    log.info("Done. Fetched descriptions for %d / %d content-family roles.", fetched_ok, len(to_fetch))
    log.info("Updated %s with description_md column.", HIST_CSV)


if __name__ == "__main__":
    main()
