# tests/test_silver.py
import pytest
import silver

@pytest.fixture
def db(tmp_path):
    return silver.open_db(base_dir=str(tmp_path))

def test_tables_created(db):
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    assert "jobs" in tables
    assert "silver_rejected" in tables
    assert "audit_log" in tables

def test_upsert_job(db):
    silver.upsert_job(db, {
        "company": "pinecone", "board": "ashby", "job_id": "abc-123",
        "source_date": "20250101", "title": "ML Engineer",
        "salary_min": 150000, "salary_max": 200000, "bronze_id": 1,
    })
    row = db.execute("SELECT title, salary_min FROM jobs WHERE job_id='abc-123'").fetchone()
    assert row["title"] == "ML Engineer"
    assert row["salary_min"] == 150000

def test_upsert_updates_all_fields_on_conflict(db):
    silver.upsert_job(db, {
        "company": "pinecone", "board": "ashby", "job_id": "abc-123",
        "source_date": "20250101", "title": "Old Title", "location": "",
        "salary_min": None, "bronze_id": 1,
    })
    silver.upsert_job(db, {
        "company": "pinecone", "board": "ashby", "job_id": "abc-123",
        "source_date": "20250101", "title": "New Title", "location": "Remote",
        "salary_min": 150000, "department": "Engineering", "bronze_id": 2,
    })
    row = db.execute("SELECT title, location, department FROM jobs WHERE job_id='abc-123'").fetchone()
    assert row["title"] == "New Title"
    assert row["location"] == "Remote"
    assert row["department"] == "Engineering"

def test_reject_missing_job_id(db):
    silver.upsert_job(db, {"company": "x", "board": "ashby", "source_date": "20250101"})
    count = db.execute("SELECT count(*) FROM silver_rejected").fetchone()[0]
    assert count == 1

def test_completeness_score(db):
    silver.upsert_job(db, {
        "company": "pinecone", "board": "ashby", "job_id": "abc-456",
        "source_date": "20250101", "title": "Engineer",
        "salary_min": 100000, "location": "Remote", "bronze_id": 2,
    })
    row = db.execute("SELECT completeness FROM jobs WHERE job_id='abc-456'").fetchone()
    assert row["completeness"] == 3

def test_adhoc_board_accepted(db):
    result = silver.upsert_job(db, {
        "company": "acme", "board": "adhoc", "job_id": "role-eng",
        "source_date": "20250101", "title": "Engineer", "bronze_id": 5,
    })
    assert result is True

def test_log_run(db):
    silver.log_run(db, company="pinecone", board="ashby",
                   rows_processed=10, rows_upserted=8, rows_rejected=2)
    row = db.execute("SELECT * FROM audit_log").fetchone()
    assert row["company"] == "pinecone"
    assert row["rows_processed"] == 10
    assert row["rows_upserted"] == 8
    assert row["rows_rejected"] == 2

def test_rejected_raw_content(db):
    silver.upsert_job(db, {"company": "x", "board": "ashby",
                           "source_date": "20250101", "title": "Eng"})
    row = db.execute("SELECT raw_content FROM silver_rejected").fetchone()
    assert row["raw_content"] is not None
    assert "Eng" in row["raw_content"]
