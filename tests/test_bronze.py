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
