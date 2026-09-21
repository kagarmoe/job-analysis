"""Tests for run_pipeline URL parsing."""
import json

import db
import bronze
import silver
from run_pipeline import parse_job_url
import run_pipeline


def test_ashby_url():
    result = parse_job_url("https://jobs.ashbyhq.com/Crusoe/2689707b-7314-4246-ac95-1e6466970ba3")
    assert result == {
        "board": "ashby",
        "company": "crusoe",
        "job_id": "2689707b-7314-4246-ac95-1e6466970ba3",
    }


def test_ashby_url_with_query_params():
    result = parse_job_url(
        "https://jobs.ashbyhq.com/Crusoe/2689707b-7314-4246-ac95-1e6466970ba3?departmentId=abc"
    )
    assert result == {
        "board": "ashby",
        "company": "crusoe",
        "job_id": "2689707b-7314-4246-ac95-1e6466970ba3",
    }


def test_greenhouse_url():
    result = parse_job_url("https://job-boards.greenhouse.io/anthropic/jobs/5080929008")
    assert result == {
        "board": "greenhouse",
        "company": "anthropic",
        "job_id": "5080929008",
    }


def test_unknown_board_routes_to_adhoc():
    result = parse_job_url("https://linkedin.com/jobs/12345")
    assert result["board"] == "adhoc"
    assert result["company"] == "linkedin"
    assert result["job_id"] == "12345"


def test_pipeline_smoke_runs_without_jupyter_or_network(tmp_path, monkeypatch):
    copper_dir = tmp_path / "copper"
    bronze_dir = tmp_path / "bronze"
    silver_dir = tmp_path / "silver"

    def fake_run_scraper(board, company, *, copper_base_dir="copper"):
        assert board == "ashby"
        assert company == "acme"
        copper_conn = db.open_copper(board, base_dir=copper_base_dir)
        db.store_copper(
            copper_conn,
            url="https://api.ashbyhq.com/posting-api/job-board/acme",
            http_status=200,
            content=json.dumps(
                {
                    "jobs": [
                        {
                            "id": "aaa-111",
                            "title": "Senior Software Engineer",
                            "department": "Software",
                            "location": "Remote - US",
                            "jobUrl": "https://jobs.ashbyhq.com/acme/aaa-111",
                            "content": "<p>Compensation: $120,000 - $180,000 USD annually</p>",
                        }
                    ]
                }
            ),
            source_date="20260101",
        )

    monkeypatch.setattr(run_pipeline, "run_scraper", fake_run_scraper)
    monkeypatch.setattr(run_pipeline, "run_wayback", lambda *args, **kwargs: None)
    monkeypatch.setattr(bronze, "derive", bronze.derive)
    monkeypatch.setattr(silver, "process", silver.process)

    summary = run_pipeline.run_pipeline(
        "https://jobs.ashbyhq.com/acme/aaa-111",
        run_notebooks=False,
        copper_base_dir=str(copper_dir),
        bronze_base_dir=str(bronze_dir),
        silver_base_dir=str(silver_dir),
    )

    assert summary["title"] == "Senior Software Engineer"
    assert summary["company"] == "acme"
    assert summary["department"] == "Engineering"
    assert summary["salary_min"] == 120000
    assert summary["salary_max"] == 180000
    assert summary["location"] == "Remote - US"

    silver_conn = db.open_silver(base_dir=str(silver_dir))
    row = silver_conn.execute("SELECT * FROM jobs WHERE job_id='aaa-111'").fetchone()
    assert row is not None


def test_main_json_flag_prints_machine_readable_last_line(monkeypatch, capsys):
    summary = {"title": "Staff Technical Writer", "company": "acme", "department": None,
               "salary_min": 120000, "salary_max": 180000, "location": "Remote"}
    monkeypatch.setattr(run_pipeline, "run_pipeline", lambda url, run_notebooks=False: summary)
    monkeypatch.setattr("sys.argv", ["run_pipeline.py", "https://jobs.ashbyhq.com/Acme/aaa-111", "--json"])

    run_pipeline.main()

    last_line = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(last_line) == {
        "job": {"board": "ashby", "company": "acme", "job_id": "aaa-111"},
        "summary": summary,
    }
