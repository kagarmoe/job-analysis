#!/usr/bin/env python3
"""Bronze layer derivation from copper snapshots."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3

import db

_ASHBY_JOB_URL_RE = re.compile(
    r"jobs\.ashbyhq\.com/([^/]+)"
    r"/([0-9a-zA-Z][0-9a-zA-Z\-]+)"
    r"(/application)?$",
)
_ASHBY_API_BOARD_RE = re.compile(
    r"api\.ashbyhq\.com/posting-api/job-board/([^/]+)$"
)
_ASHBY_INDIVIDUAL_JOB_RE = re.compile(
    r"api\.ashbyhq\.com/posting-api/job-board/[^/]+/job/"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
)
_GH_API_RE = re.compile(r"boards-api\.greenhouse\.io/v1/boards/([^/]+)/jobs")


def derive_ashby(
    copper_conn: sqlite3.Connection,
    bronze_conn: sqlite3.Connection,
    company: str,
) -> int:
    """Derive per-job bronze records from copper for an Ashby company."""
    rows = copper_conn.execute(
        "SELECT id, url, content, source_date FROM snapshots "
        "WHERE url LIKE ? OR url LIKE ? OR url LIKE ?",
        (
            f"%jobs.ashbyhq.com/{company}/%",
            f"%api.ashbyhq.com/posting-api/job-board/{company}%",
            f"%api.ashbyhq.com/posting-api/job-board/{company}/job/%",
        ),
    ).fetchall()

    count = 0
    for row in rows:
        url = row["url"]
        content = row["content"] or ""

        if _ASHBY_API_BOARD_RE.search(url):
            try:
                jobs = json.loads(content).get("jobs", [])
            except json.JSONDecodeError:
                continue
            for job in jobs:
                job_id = str(job.get("id", ""))
                if not job_id:
                    continue
                db.store_bronze(
                    bronze_conn,
                    company=company,
                    board="ashby",
                    job_id=job_id,
                    page_type="api_board",
                    source_date=row["source_date"],
                    original_url=url,
                    http_status=200,
                    content=json.dumps(job),
                    copper_id=row["id"],
                )
                count += 1
            continue

        individual_match = _ASHBY_INDIVIDUAL_JOB_RE.search(url)
        if individual_match:
            job_id = individual_match.group(1)
            db.store_bronze(
                bronze_conn,
                company=company,
                board="ashby",
                job_id=job_id,
                page_type="api_board",
                source_date=row["source_date"],
                original_url=url,
                http_status=200,
                content=content,
                copper_id=row["id"],
            )
            count += 1
            continue

        page_match = _ASHBY_JOB_URL_RE.search(url)
        if not page_match:
            continue
        job_id = page_match.group(2)
        is_application = bool(page_match.group(3))
        page_type = "application" if is_application else "job_page"

        if is_application and content:
            parsed = db.parse_json_ld_job_posting(content)
            content = json.dumps(parsed) if parsed else content

        db.store_bronze(
            bronze_conn,
            company=company,
            board="ashby",
            job_id=job_id,
            page_type=page_type,
            source_date=row["source_date"],
            original_url=url,
            http_status=200,
            content=content,
            copper_id=row["id"],
        )
        count += 1
    return count


def derive_greenhouse(
    copper_conn: sqlite3.Connection,
    bronze_conn: sqlite3.Connection,
    company: str,
) -> int:
    """Derive per-job bronze records from copper for a Greenhouse company."""
    rows = copper_conn.execute(
        "SELECT id, url, content, source_date FROM snapshots WHERE url LIKE ?",
        (f"%greenhouse.io%boards/{company}%",),
    ).fetchall()

    count = 0
    for row in rows:
        if not _GH_API_RE.search(row["url"]):
            continue
        try:
            jobs = json.loads(row["content"] or "{}").get("jobs", [])
        except json.JSONDecodeError:
            continue
        for job in jobs:
            job_id = str(job.get("id", ""))
            if not job_id:
                continue
            db.store_bronze(
                bronze_conn,
                company=company,
                board="greenhouse",
                job_id=job_id,
                page_type="api_board",
                source_date=row["source_date"],
                original_url=row["url"],
                http_status=200,
                content=json.dumps(job),
                copper_id=row["id"],
            )
            count += 1
    return count


def derive_adhoc(
    copper_conn: sqlite3.Connection,
    bronze_conn: sqlite3.Connection,
    company: str,
    job_id: str,
    url: str = "",
) -> int:
    """Derive bronze records for an adhoc job."""
    if url:
        rows = copper_conn.execute(
            "SELECT id, url, content, source_date FROM snapshots "
            "WHERE url=? ORDER BY source_date",
            (url,),
        ).fetchall()
    else:
        rows = copper_conn.execute(
            "SELECT id, url, content, source_date FROM snapshots "
            "WHERE url LIKE ? ORDER BY source_date",
            (f"%{job_id}%",),
        ).fetchall()

    count = 0
    for row in rows:
        db.store_bronze(
            bronze_conn,
            company=company,
            board="adhoc",
            job_id=job_id,
            page_type="job_page",
            source_date=row["source_date"],
            original_url=row["url"],
            http_status=200,
            content=row["content"] or "",
            copper_id=row["id"],
        )
        count += 1
    return count


def derive(
    board: str,
    company: str,
    job_id: str | None = None,
    *,
    copper_base_dir: str = "copper",
    bronze_base_dir: str = "bronze",
) -> int:
    """Derive bronze records for one board/company from copper snapshots."""
    copper_conn = db.open_copper(board, base_dir=copper_base_dir)
    bronze_conn = db.open_bronze(board, base_dir=bronze_base_dir)

    if board == "ashby":
        return derive_ashby(copper_conn, bronze_conn, company)
    if board == "greenhouse":
        return derive_greenhouse(copper_conn, bronze_conn, company)
    if board == "adhoc":
        if not job_id:
            raise ValueError("job_id is required for adhoc bronze derivation")
        return derive_adhoc(copper_conn, bronze_conn, company, job_id)

    raise ValueError(f"Unsupported board: {board}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive bronze records from copper")
    parser.add_argument("--board", required=True, choices=["ashby", "greenhouse", "adhoc"])
    parser.add_argument("--company", required=True)
    parser.add_argument("--job-id", default=None)
    args = parser.parse_args()

    count = derive(args.board, args.company, args.job_id)
    print(f"Bronze derivation complete: {count} records for {args.company}/{args.board}")


if __name__ == "__main__":
    main()
