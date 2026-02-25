#!/usr/bin/env python3
"""
Scrape salary ranges from Anthropic's Greenhouse job board and export to CSV.

Usage:
  python scrape_anthropic.py --out anthropic_salaries.csv
"""

from __future__ import annotations

import argparse
import csv
import html
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

import html2text
import requests
from bs4 import BeautifulSoup


BOARD = "anthropic"
BASE_URL = f"https://boards-api.greenhouse.io/v1/boards/{BOARD}/jobs"


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


# Compile once at import time.
DASH_PATTERN = r"(?:\u2013|\u2014|-|–|—|\s+to\s+)"
CURRENCY_SYM_1 = r"(?P<sym1>\$|£|€)"
CURRENCY_SYM_2 = r"(?P<sym2>\$|£|€)"
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)"

SALARY_RANGE_RE = re.compile(
    rf"{CURRENCY_SYM_1}\s*(?P<min>{NUMBER})\s*{DASH_PATTERN}\s*"
    rf"(?:{CURRENCY_SYM_2}\s*)?(?P<max>{NUMBER})"
)


@dataclass
class SalaryParseResult:
    salary_text: str
    currency: Optional[str]
    salary_min: Optional[int]
    salary_max: Optional[int]
    salary_unit: Optional[str]  # annual, hourly, monthly, etc.


def normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def looks_like_salary_text(text: str) -> bool:
    if not text:
        return False
    if SALARY_RANGE_RE.search(text):
        return True
    # Some posts mention currency code even if the range is formatted differently
    return bool(re.search(r"\b(USD|EUR|GBP|CAD|AUD)\b", text))


def extract_salary_block_from_html(content_html: str) -> Optional[str]:
    """
    Find a salary-ish block from the job HTML content. Returns normalized text or None.
    """
    if not content_html:
        return None

    soup = BeautifulSoup(html.unescape(content_html), "html.parser")

    heading_patterns = [
        re.compile(r"\bAnnual Salary\b", re.I),
        re.compile(r"\bSalary\b", re.I),
        re.compile(r"\bCompensation\b", re.I),
        re.compile(r"\bPay\b", re.I),
    ]

    candidates = []
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "strong", "b", "p", "span", "div", "li"]):
        txt = normalize_whitespace(tag.get_text(" ", strip=True))
        if not txt:
            continue
        if any(p.search(txt) for p in heading_patterns):
            candidates.append(tag)

    for tag in candidates:
        parent = tag.parent if tag.parent else tag
        parent_txt = normalize_whitespace(parent.get_text(" ", strip=True)) if parent else ""
        if looks_like_salary_text(parent_txt):
            return parent_txt

        # look at a few next siblings
        collected = []
        sib = parent
        for _ in range(8):
            sib = sib.find_next_sibling()
            if sib is None:
                break
            t = normalize_whitespace(sib.get_text(" ", strip=True))
            if t:
                collected.append(t)
                joined = " ".join(collected)
                if looks_like_salary_text(joined):
                    return joined

    # fallback: scan whole text
    all_text = normalize_whitespace(soup.get_text(" ", strip=True))
    m = re.search(r"(Annual Salary|Salary|Compensation).{0,400}", all_text, flags=re.I)
    if m:
        window = all_text[m.start() : min(len(all_text), m.start() + 500)]
        if looks_like_salary_text(window):
            return window

    mm = SALARY_RANGE_RE.search(all_text)
    if mm:
        s = max(0, mm.start() - 80)
        e = min(len(all_text), mm.end() + 80)
        return all_text[s:e]

    return None


def parse_salary_text(block: str) -> SalaryParseResult:
    block = normalize_whitespace(html.unescape(block))

    # unit
    unit = None
    if re.search(r"\bAnnual\b|\bper year\b|\byearly\b", block, re.I):
        unit = "annual"
    elif re.search(r"\bhour\b|\bhourly\b|\bper hour\b", block, re.I):
        unit = "hourly"
    elif re.search(r"\bmonth\b|\bmonthly\b|\bper month\b", block, re.I):
        unit = "monthly"

    # currency code
    currency = None
    m_code = re.search(r"\b(USD|EUR|GBP|CAD|AUD)\b", block)
    if m_code:
        currency = m_code.group(1)

    # numeric range
    m = SALARY_RANGE_RE.search(block)
    if m:
        sym = m.group("sym1")
        min_val = int(m.group("min").replace(",", ""))
        max_val = int(m.group("max").replace(",", ""))
        if not currency:
            currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(sym)
        return SalaryParseResult(block, currency, min_val, max_val, unit)

    # secondary pattern: "131,040–165,000 USD"
    m2 = re.search(rf"(\d{{1,3}}(?:,\d{{3}})+|\d+)\s*{DASH_PATTERN}\s*(\d{{1,3}}(?:,\d{{3}})+|\d+)\s*(USD|EUR|GBP|CAD|AUD)?",
                   block)
    if m2:
        min_val = int(m2.group(1).replace(",", ""))
        max_val = int(m2.group(2).replace(",", ""))
        if not currency and m2.group(3):
            currency = m2.group(3)
        return SalaryParseResult(block, currency, min_val, max_val, unit)

    return SalaryParseResult(block, currency, None, None, unit)


def greenhouse_job_url(job_id: int) -> str:
    return f"https://job-boards.greenhouse.io/{BOARD}/jobs/{job_id}"


def scrape_all_jobs() -> List[Dict[str, Any]]:
    log.info("Fetching all jobs from Greenhouse boards API ...")
    resp = requests.get(BASE_URL, params={"content": "true"}, timeout=30)
    resp.raise_for_status()
    jobs = resp.json().get("jobs", [])
    log.info("Fetched %d jobs", len(jobs))
    return jobs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="anthropic_salaries.csv")
    args = ap.parse_args()

    jobs = scrape_all_jobs()

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

        rows.append(
            {
                "job_id": job_id,
                "title": title,
                "location": location,
                "url": greenhouse_job_url(job_id),
                "updated_at": updated_at,
                "salary_text": parsed.salary_text,
                "currency": parsed.currency,
                "salary_min": parsed.salary_min,
                "salary_max": parsed.salary_max,
                "salary_unit": parsed.salary_unit,
                "description_md": description_md,
            }
        )

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    with_salary = sum(1 for r in rows if r["salary_min"] is not None and r["salary_max"] is not None)
    log.info("Parsed salary ranges for %d / %d jobs", with_salary, len(rows))
    log.info("Wrote %s", args.out)


if __name__ == "__main__":
    main()
