import json

import db
import silver


def test_process_ashby_api_board_to_silver(tmp_path):
    bronze_dir = tmp_path / "bronze"
    silver_dir = tmp_path / "silver"
    bronze_conn = db.open_bronze("ashby", base_dir=str(bronze_dir))
    db.store_bronze(
        bronze_conn,
        company="acme",
        board="ashby",
        job_id="aaa-111",
        page_type="api_board",
        source_date="20260101",
        original_url="https://api.ashbyhq.com/posting-api/job-board/acme",
        http_status=200,
        content=json.dumps(
            {
                "id": "aaa-111",
                "title": "Senior Software Engineer",
                "department": "Software",
                "location": "Remote - US",
                "jobUrl": "https://jobs.ashbyhq.com/acme/aaa-111",
                "content": (
                    "<p>Compensation: $120,000 - $180,000 USD annually</p>"
                    "<p>Requires 5+ years of experience.</p>"
                ),
            }
        ),
        copper_id=1,
    )
    db.store_bronze(
        bronze_conn,
        company="acme",
        board="ashby",
        job_id="aaa-111",
        page_type="job_page",
        source_date="20260101",
        original_url="https://jobs.ashbyhq.com/acme/aaa-111",
        http_status=200,
        content="<html><title>Senior Software Engineer</title><body>Requires 5+ years of experience.</body></html>",
        copper_id=2,
    )

    result = silver.process(
        "ashby",
        "acme",
        bronze_base_dir=str(bronze_dir),
        silver_base_dir=str(silver_dir),
    )

    assert result == {"processed": 1, "upserted": 1, "rejected": 0}
    silver_conn = db.open_silver(base_dir=str(silver_dir))
    row = silver_conn.execute("SELECT * FROM jobs WHERE job_id='aaa-111'").fetchone()
    assert row["title"] == "Senior Software Engineer"
    assert row["department"] == "Engineering"
    assert row["seniority"] == "Senior"
    assert row["work_mode"] == "Remote-Friendly"
    assert row["salary_min"] == 120000
    assert row["salary_max"] == 180000
    assert row["yoe"] == 5
    audit = silver_conn.execute("SELECT * FROM audit_log WHERE company='acme'").fetchone()
    assert audit["rows_processed"] == 1
    assert audit["rows_upserted"] == 1
    assert audit["rows_rejected"] == 0


def test_process_rejects_unusable_bronze_group(tmp_path):
    bronze_dir = tmp_path / "bronze"
    silver_dir = tmp_path / "silver"
    bronze_conn = db.open_bronze("adhoc", base_dir=str(bronze_dir))
    db.store_bronze(
        bronze_conn,
        company="acme",
        board="adhoc",
        job_id="bad-job",
        page_type="unknown",
        source_date="20260101",
        http_status=200,
        content="{}",
        copper_id=1,
    )

    result = silver.process(
        "adhoc",
        "acme",
        bronze_base_dir=str(bronze_dir),
        silver_base_dir=str(silver_dir),
    )

    assert result == {"processed": 0, "upserted": 0, "rejected": 1}
    silver_conn = db.open_silver(base_dir=str(silver_dir))
    rejected = silver_conn.execute(
        "SELECT * FROM silver_rejected WHERE job_id='bad-job'"
    ).fetchone()
    assert rejected is not None
