import json
from job_analysis import db


def test_store_copper_idempotent(tmp_path):
    conn = db.open_copper("ashby", base_dir=str(tmp_path))
    db.store_copper(conn, url="https://example.com", http_status=200,
                    content="hello", source_date="20260101")
    db.store_copper(conn, url="https://example.com", http_status=200,
                    content="hello", source_date="20260101")
    count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    assert count == 1


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


def test_parse_salary_european_thousands_separator():
    # Anthropic's EU postings; previously parsed as 235
    result = db.parse_salary_text("Annual Salary: €235.000 — €295.000 EUR")
    assert (result.salary_min, result.salary_max, result.currency) == (235000, 295000, "EUR")


def test_parse_salary_text_expands_k_suffix():
    # Ashby's compensation summary; previously parsed as 180–250
    result = db.parse_salary_text("$180K – $250K • Offers Equity")
    assert (result.salary_min, result.salary_max, result.currency) == (180000, 250000, "USD")


def test_parse_ashby_app_data_tells_posting_shell_and_other_pages_apart():
    posting = {"title": "Documentation Engineer", "departmentName": "Engineering"}
    page = '<script>window.__appData = {"posting": %s, "x": 1};</script>' % json.dumps(posting)
    shell = '<title>Jobs</title><script>window.__appData = {"posting": null};</script>'
    assert db.parse_ashby_app_data(page) == posting
    assert db.parse_ashby_app_data(shell) == {}
    assert db.parse_ashby_app_data("<html><title>Engineer</title></html>") is None
