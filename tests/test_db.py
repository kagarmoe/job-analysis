import sqlite3
import pytest
import db


def test_open_copper_creates_schema(tmp_path):
    conn = db.open_copper("ashby", base_dir=str(tmp_path))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "snapshots" in tables


def test_store_copper_idempotent(tmp_path):
    conn = db.open_copper("ashby", base_dir=str(tmp_path))
    db.store_copper(conn, url="https://example.com", http_status=200,
                    content="hello", source_date="20260101")
    db.store_copper(conn, url="https://example.com", http_status=200,
                    content="hello", source_date="20260101")
    count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    assert count == 1


def test_open_bronze_creates_schema(tmp_path):
    conn = db.open_bronze("ashby", base_dir=str(tmp_path))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "snapshots" in tables


def test_store_bronze_idempotent(tmp_path):
    conn = db.open_bronze("ashby", base_dir=str(tmp_path))
    db.store_bronze(conn, company="acme", board="ashby", job_id="abc123",
                    page_type="api_board", source_date="20260101",
                    http_status=200, content="{}", copper_id=None)
    db.store_bronze(conn, company="acme", board="ashby", job_id="abc123",
                    page_type="api_board", source_date="20260101",
                    http_status=200, content="{}", copper_id=None)
    count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    assert count == 1


def test_db_does_not_own_board_derivation():
    assert not hasattr(db, "derive_ashby")
    assert not hasattr(db, "derive_greenhouse")
    assert not hasattr(db, "derive_adhoc")


def test_open_silver_creates_schema(tmp_path):
    conn = db.open_silver(base_dir=str(tmp_path))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "jobs" in tables
    assert "silver_rejected" in tables
    assert "audit_log" in tables


def test_open_silver_adds_yoe_column(tmp_path):
    conn = db.open_silver(base_dir=str(tmp_path))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "yoe" in cols


def test_upsert_job_success(tmp_path):
    conn = db.open_silver(base_dir=str(tmp_path))
    ok = db.upsert_job(conn, {
        "company": "acme", "board": "ashby", "job_id": "j1",
        "source_date": "20260101", "title": "Engineer",
    })
    assert ok is True
    row = conn.execute("SELECT title FROM jobs WHERE job_id='j1'").fetchone()
    assert row["title"] == "Engineer"


def test_upsert_job_missing_required(tmp_path):
    conn = db.open_silver(base_dir=str(tmp_path))
    ok = db.upsert_job(conn, {"company": "acme", "job_id": "j2"})
    assert ok is False
    rejected = conn.execute("SELECT * FROM silver_rejected WHERE job_id='j2'").fetchone()
    assert rejected is not None


def test_log_run(tmp_path):
    conn = db.open_silver(base_dir=str(tmp_path))
    db.log_run(conn, "acme", "ashby", rows_processed=10, rows_upserted=9, rows_rejected=1)
    row = conn.execute("SELECT * FROM audit_log WHERE company='acme'").fetchone()
    assert row["rows_processed"] == 10


def test_parse_salary_range():
    result = db.parse_salary_text("$120,000 – $180,000 USD annually")
    assert result.salary_min == 120000
    assert result.salary_max == 180000
    assert result.currency == "USD"


def test_extract_salary_block_finds_range():
    html = "<p>Compensation: $150,000–$200,000 per year</p>"
    block = db.extract_salary_block_from_html(html)
    assert block is not None
    assert "150" in block


def test_parse_salary_text_none_input():
    result = db.parse_salary_text(None)
    assert result.salary_min is None


def test_parse_salary_text_swaps_reversed_range():
    result = db.parse_salary_text("$200,000 – $100,000")
    assert result.salary_min <= result.salary_max


def test_parse_json_ld_none_input():
    result = db.parse_json_ld_job_posting(None)
    assert result is None


def test_upsert_job_updates_on_conflict(tmp_path):
    conn = db.open_silver(base_dir=str(tmp_path))
    db.upsert_job(conn, {
        "company": "acme", "board": "ashby", "job_id": "j3",
        "source_date": "20260101", "title": "Engineer",
    })
    db.upsert_job(conn, {
        "company": "acme", "board": "ashby", "job_id": "j3",
        "source_date": "20260101", "title": "Senior Engineer",
    })
    row = conn.execute("SELECT title FROM jobs WHERE job_id='j3'").fetchone()
    assert row["title"] == "Senior Engineer"
