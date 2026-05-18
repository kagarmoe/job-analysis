# tests/test_bronze.py
import pytest
import bronze

@pytest.fixture
def db(tmp_path):
    return bronze.open_db("ashby", base_dir=str(tmp_path))

def test_store_requires_copper_id(db):
    # store() must accept copper_id — this fails before the change
    bronze.store(db, company="pinecone", board="ashby", job_id="abc-123",
                 source_date="20250101", page_type="job_page",
                 original_url="https://jobs.ashbyhq.com/pinecone/abc-123",
                 http_status=200, content="<html>job</html>", copper_id=1)
    content = bronze.get_content(db, "pinecone", "abc-123", "20250101", "job_page")
    assert content == "<html>job</html>"

def test_copper_id_stored(db):
    bronze.store(db, company="pinecone", board="ashby", job_id="abc-123",
                 source_date="20250101", page_type="job_page",
                 original_url="https://jobs.ashbyhq.com/pinecone/abc-123",
                 http_status=200, content="<html/>", copper_id=42)
    row = db.execute("SELECT copper_id FROM snapshots WHERE job_id='abc-123'").fetchone()
    assert row["copper_id"] == 42

def test_copper_id_nullable(db):
    bronze.store(db, company="pinecone", board="ashby", job_id="no-copper",
                 source_date="20250101", page_type="job_page",
                 original_url=None, http_status=200, content="x")
    row = db.execute("SELECT copper_id FROM snapshots WHERE job_id='no-copper'").fetchone()
    assert row["copper_id"] is None

def test_no_wayback_url_column(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(snapshots)").fetchall()]
    assert "wayback_url" not in cols
    assert "wayback_ts" not in cols

def test_adhoc_board_supported(tmp_path):
    db = bronze.open_db("adhoc", base_dir=str(tmp_path))
    bronze.store(db, company="acme", board="adhoc", job_id="role-eng",
                 source_date="20250101", page_type="job_page",
                 original_url="https://jobs.lever.co/acme/role-eng",
                 http_status=200, content="<html/>", copper_id=1)
    assert bronze.get_content(db, "acme", "role-eng", "20250101", "job_page") == "<html/>"


# Task 6: derive_ashby tests
import copper as _copper
import json

@pytest.fixture
def copper_db(tmp_path):
    return _copper.open_db("ashby", base_dir=str(tmp_path / "copper"))

@pytest.fixture
def bronze_db(tmp_path):
    return bronze.open_db("ashby", base_dir=str(tmp_path / "bronze"))

def test_derive_ashby_job_page(copper_db, bronze_db):
    _copper.store(copper_db,
                  url="https://jobs.ashbyhq.com/pinecone/abc-def-123",
                  http_status=200, content="<html>job</html>", source_date="20250101")
    bronze.derive_ashby(copper_db, bronze_db, company="pinecone")
    content = bronze.get_content(bronze_db, "pinecone", "abc-def-123", "20250101", "job_page")
    assert content == "<html>job</html>"

def test_derive_ashby_application_extracts_json_ld(copper_db, bronze_db):
    html = '<html><script type="application/ld+json">{"@type":"JobPosting","title":"ML Eng","baseSalary":{"@type":"MonetaryAmount","currency":"USD","value":{"@type":"QuantitativeValue","minValue":150000,"maxValue":200000,"unitText":"YEAR"}}}</script></html>'
    _copper.store(copper_db,
                  url="https://jobs.ashbyhq.com/pinecone/abc-def-123/application",
                  http_status=200, content=html, source_date="20250101")
    bronze.derive_ashby(copper_db, bronze_db, company="pinecone")
    raw = bronze.get_content(bronze_db, "pinecone", "abc-def-123", "20250101", "application")
    parsed = json.loads(raw)
    assert parsed["salary_min"] == 150000
    assert parsed["title"] == "ML Eng"

def test_derive_ashby_api_board_splits_jobs(copper_db, bronze_db):
    api_json = json.dumps({"jobs": [
        {"id": "uuid-1", "title": "SWE", "department": "Engineering", "descriptionHtml": ""},
        {"id": "uuid-2", "title": "PM", "department": "Product", "descriptionHtml": ""},
    ]})
    _copper.store(copper_db,
                  url="https://api.ashbyhq.com/posting-api/job-board/pinecone",
                  http_status=200, content=api_json, source_date="20250101")
    bronze.derive_ashby(copper_db, bronze_db, company="pinecone")
    c1 = bronze.get_content(bronze_db, "pinecone", "uuid-1", "20250101", "api_board")
    c2 = bronze.get_content(bronze_db, "pinecone", "uuid-2", "20250101", "api_board")
    assert json.loads(c1)["department"] == "Engineering"
    assert json.loads(c2)["department"] == "Product"


# Task 6b: derive_greenhouse tests
@pytest.fixture
def gh_copper_db(tmp_path):
    return _copper.open_db("greenhouse", base_dir=str(tmp_path / "copper"))

@pytest.fixture
def gh_bronze_db(tmp_path):
    return bronze.open_db("greenhouse", base_dir=str(tmp_path / "bronze"))

def test_derive_greenhouse_splits_jobs(gh_copper_db, gh_bronze_db):
    api_json = json.dumps({"jobs": [
        {"id": 101, "title": "Backend Eng",
         "departments": [{"name": "Engineering"}],
         "location": {"name": "Remote"},
         "content": "<p>Description</p>"},
        {"id": 102, "title": "Designer",
         "departments": [{"name": "Design"}],
         "location": {"name": "SF"},
         "content": "<p>Design role</p>"},
    ]})
    _copper.store(gh_copper_db,
                  url="https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true",
                  http_status=200, content=api_json, source_date="20250101")
    bronze.derive_greenhouse(gh_copper_db, gh_bronze_db, company="acme")
    c1 = bronze.get_content(gh_bronze_db, "acme", "101", "20250101", "api_board")
    assert json.loads(c1)["title"] == "Backend Eng"
    c2 = bronze.get_content(gh_bronze_db, "acme", "102", "20250101", "api_board")
    assert json.loads(c2)["title"] == "Designer"


# Task 6c: derive_adhoc tests
@pytest.fixture
def adhoc_copper_db(tmp_path):
    return _copper.open_db("adhoc", base_dir=str(tmp_path / "copper"))

@pytest.fixture
def adhoc_bronze_db(tmp_path):
    return bronze.open_db("adhoc", base_dir=str(tmp_path / "bronze"))

def test_derive_adhoc(adhoc_copper_db, adhoc_bronze_db):
    url = "https://jobs.lever.co/acme/engineer-role"
    _copper.store(adhoc_copper_db, url=url, http_status=200,
                  content="<html><title>Engineer | Acme</title></html>",
                  source_date="20250101")
    bronze.derive_adhoc(adhoc_copper_db, adhoc_bronze_db,
                        company="acme", job_id="engineer-role")
    content = bronze.get_content(adhoc_bronze_db, "acme", "engineer-role", "20250101", "job_page")
    assert "<title>Engineer" in content
