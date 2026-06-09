#!/usr/bin/env python3
"""Silver layer processing from bronze records."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import html2text

import db
from classify import (
    classify_seniority,
    classify_work_mode,
    extract_yoe,
    normalize_department,
)


def _md(html_text: str) -> str:
    if not html_text:
        return ""
    converter = html2text.HTML2Text()
    converter.body_width = 0
    converter.ignore_images = True
    converter.ignore_links = True
    return converter.handle(html_text).strip()


def _title_from_html(html_text: str) -> str:
    if not html_text:
        return ""
    match = re.search(r"<title>([^<]+)</title>", html_text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _location_name(location: Any) -> str:
    if isinstance(location, dict):
        return location.get("name", "")
    if isinstance(location, list):
        return " | ".join(
            item.get("name", "") for item in location if isinstance(item, dict)
        )
    return location or ""


def _department_raw(job: dict) -> str:
    departments = job.get("departments") or [{}]
    first_department = departments[0] if departments and isinstance(departments[0], dict) else {}
    return job.get("department") or job.get("team") or first_department.get("name", "")


def _add_salary_from_html(record: dict, content_html: str) -> None:
    if not content_html or record.get("salary_min"):
        return
    sal_block = db.extract_salary_block_from_html(content_html)
    parsed = db.parse_salary_text(sal_block) if sal_block else db.SalaryParseResult(
        "", None, None, None, None
    )
    if parsed.salary_min:
        record["salary_min"] = int(parsed.salary_min)
        record["salary_max"] = int(parsed.salary_max) if parsed.salary_max else None
        record["currency"] = parsed.currency or ""
        record["salary_unit"] = parsed.salary_unit or ""
        record["salary_text"] = parsed.salary_text or ""


def merge_to_silver(job_id: str, page_rows: dict[str, Any]) -> dict | None:
    api = page_rows.get("api_board")
    app = page_rows.get("application")
    page = page_rows.get("job_page")
    source_row = api or app or page
    if source_row is None:
        return None

    record = {
        "company": source_row["company"],
        "board": source_row["board"],
        "job_id": job_id,
        "source_date": source_row["source_date"],
        "bronze_id": source_row["id"],
        "fetched_at": source_row["fetched_at"],
    }

    if api:
        try:
            job = json.loads(api["content"] or "{}")
        except json.JSONDecodeError:
            job = {}
        record["title"] = job.get("title", "")
        record["location"] = _location_name(job.get("location"))
        record["url"] = job.get("jobUrl") or job.get("absolute_url", "")
        record["department_raw"] = _department_raw(job)
        _add_salary_from_html(record, job.get("content", ""))

    if app:
        try:
            jld = json.loads(app["content"] or "{}")
        except json.JSONDecodeError:
            jld = {}
        if jld.get("salary_min"):
            record["salary_min"] = int(jld["salary_min"])
            record["salary_max"] = int(jld["salary_max"]) if jld.get("salary_max") else None
            record["currency"] = jld.get("currency", "")
            record["salary_unit"] = jld.get("salary_unit", "")
            record["salary_text"] = jld.get("salary_text", "")
        if not record.get("title"):
            record["title"] = jld.get("title", "")
        if not record.get("location"):
            record["location"] = jld.get("location", "")

    if page:
        content = page["content"] or ""
        record["description_md"] = _md(content)
        _add_salary_from_html(record, content)
        if not record.get("title"):
            record["title"] = _title_from_html(content)

    title = record.get("title", "")
    record["seniority"] = classify_seniority(title)
    record["department"] = normalize_department(record.get("department_raw", ""))
    record["work_mode"] = classify_work_mode(record.get("location", ""))
    record["yoe"] = extract_yoe(record.get("description_md", "") or "")
    return record


def _reject_unusable(silver_conn, company: str, job_id: str) -> None:
    silver_conn.execute(
        """INSERT INTO silver_rejected
           (company, job_id, source_date, rejection_reason, rejected_at)
           VALUES (?,?,?,?,?)""",
        (
            company,
            job_id,
            None,
            "merge_to_silver returned None - no usable bronze rows",
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    silver_conn.commit()


def process(
    board: str,
    company: str,
    *,
    bronze_base_dir: str = "bronze",
    silver_base_dir: str = "silver",
) -> dict[str, int]:
    """Process bronze rows into silver for one board/company."""
    bronze_conn = db.open_bronze(board, base_dir=bronze_base_dir)
    silver_conn = db.open_silver(base_dir=silver_base_dir)
    rows = bronze_conn.execute(
        "SELECT * FROM snapshots WHERE company=? ORDER BY source_date",
        (company,),
    ).fetchall()

    by_job: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in rows:
        by_job[row["job_id"]][row["page_type"]] = row

    processed = upserted = rejected = 0
    for job_id, page_rows in by_job.items():
        record = merge_to_silver(job_id, page_rows)
        if record is None:
            _reject_unusable(silver_conn, company, job_id)
            rejected += 1
            continue
        processed += 1
        ok = db.upsert_job(silver_conn, record)
        upserted += int(ok)
        rejected += int(not ok)

    db.log_run(silver_conn, company, board, processed, upserted, rejected)
    return {"processed": processed, "upserted": upserted, "rejected": rejected}


def main() -> None:
    parser = argparse.ArgumentParser(description="Process bronze records into silver")
    parser.add_argument("--board", required=True, choices=["ashby", "greenhouse", "adhoc"])
    parser.add_argument("--company", required=True)
    args = parser.parse_args()

    result = process(args.board, args.company)
    print(
        "Processed: {processed}  Upserted: {upserted}  Rejected: {rejected}".format(
            **result
        )
    )


if __name__ == "__main__":
    main()
