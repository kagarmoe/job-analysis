import json

from job_analysis import db
from job_analysis import bronze


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


def test_derive_ashby_takes_newest_same_day_board_snapshot(tmp_path):
    copper_dir, bronze_dir = tmp_path / "copper", tmp_path / "bronze"
    copper_conn = db.open_copper("ashby", base_dir=str(copper_dir))
    base = "https://api.ashbyhq.com/posting-api/job-board/acme"
    for url, job in [
        (base, {"id": "aaa-111", "title": "Engineer"}),
        (base + "?includeCompensation=true", {"id": "aaa-111", "title": "Engineer", "compensation": {"x": 1}}),
    ]:
        db.store_copper(copper_conn, url=url, http_status=200,
                        content=json.dumps({"jobs": [job]}), source_date="20260101")

    bronze.derive("ashby", "acme", copper_base_dir=str(copper_dir), bronze_base_dir=str(bronze_dir))

    bronze_conn = db.open_bronze("ashby", base_dir=str(bronze_dir))
    (content,) = bronze_conn.execute(
        "SELECT content FROM snapshots WHERE job_id='aaa-111' AND page_type='api_board'").fetchone()
    assert json.loads(content)["compensation"] == {"x": 1}


def test_workday_copper_to_silver_takes_department_from_the_job_category_page(tmp_path):
    from job_analysis import silver

    copper_dir, bronze_dir, silver_dir = (str(tmp_path / d) for d in ("copper", "bronze", "silver"))
    api = "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/Careers"
    path = "/job/US-CA-Santa-Clara/Technical-Writer_JR1"
    copper_conn = db.open_copper("workday", base_dir=copper_dir)
    facets = [{"facetParameter": "jobFamilyGroup",
               "values": [{"id": "f1", "descriptor": "Engineering"}, {"id": "f2", "descriptor": "Marketing"}]}]
    # Workday returns facets (category id -> name) only on offset-0 pages.
    db.store_copper(copper_conn, url=f"{api}/jobs?offset=0", http_status=200, source_date="20260101",
                    content=json.dumps({"facets": facets, "jobPostings": []}))
    db.store_copper(copper_conn, url=f"{api}/jobs?jobFamilyGroup=f1&offset=20", http_status=200,
                    source_date="20260101", content=json.dumps({"jobPostings": [{"externalPath": path}]}))
    db.store_copper(copper_conn, url=f"{api}{path}", http_status=200, source_date="20260101",
                    content=json.dumps({"jobPostingInfo": {
                        "title": "Senior Technical Writer", "jobReqId": "JR1",
                        "location": "US, CA, Santa Clara", "additionalLocations": ["US, Remote"],
                        "externalUrl": "https://acme.wd1.myworkdayjobs.com/Careers/job/x_JR1",
                        "jobDescription": "<p>5+ years of experience.</p>"
                                          "<p>The base salary range is 184,000 USD - 287,500 USD.</p>",
                    }}))

    assert bronze.derive("workday", "acme", copper_base_dir=copper_dir, bronze_base_dir=bronze_dir) == 1
    silver.process("workday", "acme", bronze_base_dir=bronze_dir, silver_base_dir=silver_dir)

    row = db.open_silver(base_dir=silver_dir).execute("SELECT * FROM jobs WHERE job_id='JR1'").fetchone()
    assert (row["title"], row["department_raw"]) == ("Senior Technical Writer", "Engineering")
    assert (row["location"], row["work_mode"]) == ("US, CA, Santa Clara | US, Remote", "Remote-Friendly")
    assert (row["salary_min"], row["salary_max"], row["currency"]) == (184000, 287500, "USD")
    assert row["url"] == "https://acme.wd1.myworkdayjobs.com/Careers/job/x_JR1"
    assert row["yoe"] == 5
