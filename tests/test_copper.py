# tests/test_copper.py
import pytest
import copper

@pytest.fixture
def db(tmp_path):
    return copper.open_db("ashby", base_dir=str(tmp_path))

def test_store_and_retrieve(db):
    copper.store(db, url="https://example.com/job/123",
                 http_status=200, content="<html>job</html>",
                 source_date="20250101120000")
    assert copper.get_content(db, "https://example.com/job/123", "20250101120000") == "<html>job</html>"

def test_duplicate_insert_ignored(db):
    copper.store(db, url="https://x.com/1", http_status=200,
                 content="original", source_date="20250101")
    copper.store(db, url="https://x.com/1", http_status=200,
                 content="duplicate", source_date="20250101")
    assert copper.get_content(db, "https://x.com/1", "20250101") == "original"

def test_same_url_different_date(db):
    copper.store(db, url="https://x.com/1", http_status=200,
                 content="v1", source_date="20250101")
    copper.store(db, url="https://x.com/1", http_status=200,
                 content="v2", source_date="20250201")
    assert copper.get_content(db, "https://x.com/1", "20250101") == "v1"
    assert copper.get_content(db, "https://x.com/1", "20250201") == "v2"

def test_missing_returns_none(db):
    assert copper.get_content(db, "https://x.com/missing", "20250101") is None

def test_db_created_in_board_subdir(tmp_path):
    copper.open_db("greenhouse", base_dir=str(tmp_path))
    assert (tmp_path / "greenhouse.db").exists()

def test_adhoc_db_supported(tmp_path):
    db = copper.open_db("adhoc", base_dir=str(tmp_path))
    copper.store(db, url="https://jobs.lever.co/acme/abc",
                 http_status=200, content="<html/>", source_date="20250101")
    assert copper.get_content(db, "https://jobs.lever.co/acme/abc", "20250101") == "<html/>"

def test_http_status_stored(tmp_path):
    db = copper.open_db("ashby", base_dir=str(tmp_path))
    copper.store(db, url="https://x.com/404", http_status=404,
                 content="", source_date="20250101")
    row = db.execute(
        "SELECT http_status FROM snapshots WHERE url='https://x.com/404'"
    ).fetchone()
    assert row["http_status"] == 404

def test_duplicate_preserves_all_columns(tmp_path):
    db = copper.open_db("ashby", base_dir=str(tmp_path))
    copper.store(db, url="https://x.com/1", http_status=200,
                 content="original", source_date="20250101")
    copper.store(db, url="https://x.com/1", http_status=404,
                 content="overwrite attempt", source_date="20250101")
    row = db.execute(
        "SELECT content, http_status FROM snapshots WHERE url='https://x.com/1'"
    ).fetchone()
    assert row["content"] == "original"
    assert row["http_status"] == 200
