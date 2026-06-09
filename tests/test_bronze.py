import json

import db
import bronze


def test_derive_ashby_board_api_from_copper(tmp_path):
    copper_dir = tmp_path / "copper"
    bronze_dir = tmp_path / "bronze"
    copper_conn = db.open_copper("ashby", base_dir=str(copper_dir))
    jobs_payload = json.dumps(
        {
            "jobs": [
                {
                    "id": "aaa-111",
                    "title": "Senior Engineer",
                    "department": "Software",
                }
            ]
        }
    )
    db.store_copper(
        copper_conn,
        url="https://api.ashbyhq.com/posting-api/job-board/acme",
        http_status=200,
        content=jobs_payload,
        source_date="20260101",
    )

    count = bronze.derive(
        "ashby",
        "acme",
        copper_base_dir=str(copper_dir),
        bronze_base_dir=str(bronze_dir),
    )

    assert count == 1
    bronze_conn = db.open_bronze("ashby", base_dir=str(bronze_dir))
    row = bronze_conn.execute(
        "SELECT * FROM snapshots WHERE company='acme' AND job_id='aaa-111'"
    ).fetchone()
    assert row is not None
    assert row["page_type"] == "api_board"
    assert row["copper_id"] is not None


def test_derive_greenhouse_board_api_from_copper(tmp_path):
    copper_dir = tmp_path / "copper"
    bronze_dir = tmp_path / "bronze"
    copper_conn = db.open_copper("greenhouse", base_dir=str(copper_dir))
    jobs_payload = json.dumps(
        {
            "jobs": [
                {
                    "id": 12345,
                    "title": "Product Engineer",
                    "departments": [{"name": "Engineering"}],
                }
            ]
        }
    )
    db.store_copper(
        copper_conn,
        url="https://boards-api.greenhouse.io/v1/boards/acme/jobs",
        http_status=200,
        content=jobs_payload,
        source_date="20260101",
    )

    count = bronze.derive(
        "greenhouse",
        "acme",
        copper_base_dir=str(copper_dir),
        bronze_base_dir=str(bronze_dir),
    )

    assert count == 1
    bronze_conn = db.open_bronze("greenhouse", base_dir=str(bronze_dir))
    row = bronze_conn.execute(
        "SELECT * FROM snapshots WHERE company='acme' AND job_id='12345'"
    ).fetchone()
    assert row is not None
    assert row["page_type"] == "api_board"


def test_derive_adhoc_requires_job_id(tmp_path):
    copper_dir = tmp_path / "copper"
    bronze_dir = tmp_path / "bronze"
    copper_conn = db.open_copper("adhoc", base_dir=str(copper_dir))
    db.store_copper(
        copper_conn,
        url="https://jobs.example.com/acme/abc123",
        http_status=200,
        content="<html><h1>Engineer</h1></html>",
        source_date="20260101",
    )

    count = bronze.derive(
        "adhoc",
        "acme",
        job_id="abc123",
        copper_base_dir=str(copper_dir),
        bronze_base_dir=str(bronze_dir),
    )

    assert count == 1
    bronze_conn = db.open_bronze("adhoc", base_dir=str(bronze_dir))
    row = bronze_conn.execute(
        "SELECT * FROM snapshots WHERE company='acme' AND job_id='abc123'"
    ).fetchone()
    assert row is not None
    assert row["page_type"] == "job_page"
