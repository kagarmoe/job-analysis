"""Tests for run_pipeline URL parsing."""
from run_pipeline import parse_job_url


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
