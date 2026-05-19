"""
Migrate live {company}_salaries.csv files into copper as synthetic api_board snapshots.

Historical CSVs are already covered by the Wayback scraper — this handles only the
live scrape CSVs that predate the medallion architecture.

Each CSV becomes one copper record: a synthetic API board response (JSON with a
"jobs" array) stored at the canonical API URL with source_date = max(updated_at).
The salary_text is embedded in the JSON "content" field as HTML so that
silver.ipynb's extract_salary_block_from_html can read it unchanged.
"""

import csv
import json
import logging
import pathlib
import sys

import copper

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

_SOURCES = [
    {
        "company": "crusoe",
        "board": "ashby",
        "csv": "crusoe_salaries.csv",
        "url": "https://api.ashbyhq.com/posting-api/job-board/Crusoe",
    },
    {
        "company": "launchdarkly",
        "board": "greenhouse",
        "csv": "launchdarkly_salaries.csv",
        "url": "https://boards-api.greenhouse.io/v1/boards/launchdarkly/jobs",
    },
    {
        "company": "redpandadata",
        "board": "greenhouse",
        "csv": "redpandadata_salaries.csv",
        "url": "https://boards-api.greenhouse.io/v1/boards/redpandadata/jobs",
    },
    {
        "company": "anthropic",
        "board": "greenhouse",
        "csv": "anthropic_salaries.csv",
        "url": "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
    },
]


def _salary_html(row: dict) -> str:
    # Prefer generating from parsed numbers — salary_text may be a large description block.
    sal_min = row.get("salary_min", "").strip()
    sal_max = row.get("salary_max", "").strip()
    currency = row.get("currency", "USD").strip() or "USD"
    unit = row.get("salary_unit", "").strip()
    if sal_min:
        parts = f"${int(float(sal_min)):,}"
        if sal_max:
            parts += f" - ${int(float(sal_max)):,}"
        parts += f" {currency}"
        if unit:
            parts += f" per {unit}"
        return f"<p>Salary: {parts}</p>"
    text = row.get("salary_text", "").strip()
    return f"<p>{text}</p>" if text else ""


def _to_ashby_job(row: dict) -> dict:
    return {
        "id": row["job_id"],
        "title": row.get("title", ""),
        "department": row.get("department_raw", ""),
        "location": row.get("location", ""),
        "publishedAt": row.get("updated_at", ""),
        "jobUrl": row.get("url", ""),
        "content": _salary_html(row),
    }


def _to_greenhouse_job(row: dict) -> dict:
    dept = row.get("department_raw", "")
    return {
        "id": row["job_id"],
        "title": row.get("title", ""),
        "location": {"name": row.get("location", "")},
        "updated_at": row.get("updated_at", ""),
        "departments": [{"id": 1, "name": dept}] if dept else [],
        "content": _salary_html(row),
        "absolute_url": row.get("url", ""),
    }


def migrate(source: dict, dry_run: bool = False) -> int:
    csv_path = pathlib.Path(source["csv"])
    if not csv_path.exists():
        log.warning("CSV not found: %s — skipping", csv_path)
        return 0

    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        log.warning("%s: empty — skipping", csv_path)
        return 0

    # source_date: max updated_at as YYYYMMDD (approximates the scrape date)
    dates = [r.get("updated_at", "")[:10].replace("-", "") for r in rows if r.get("updated_at", "").strip()]
    source_date = max(dates) if dates else "19700101"

    if source["board"] == "ashby":
        jobs = [_to_ashby_job(r) for r in rows]
    else:
        jobs = [_to_greenhouse_job(r) for r in rows]

    content = json.dumps({"jobs": jobs})

    log.info(
        "%s (%s): %d jobs → source_date=%s url=%s",
        source["company"], source["board"], len(jobs), source_date, source["url"],
    )

    if dry_run:
        log.info("  DRY RUN — not writing to copper")
        return len(jobs)

    db = copper.open_db(source["board"])
    existing = copper.get_content(db, source["url"], source_date)
    if existing is not None:
        log.info("  Already in copper — skipping (INSERT OR IGNORE would no-op)")
        db.close()
        return 0

    copper.store(db, url=source["url"], http_status=200, content=content, source_date=source_date)
    db.close()
    log.info("  Stored.")
    return len(jobs)


def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        log.info("DRY RUN mode")

    total = 0
    for source in _SOURCES:
        total += migrate(source, dry_run=dry_run)

    log.info("Done. Total jobs written: %d", total)


if __name__ == "__main__":
    main()
