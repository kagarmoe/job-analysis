import json
from pathlib import Path

import nbformat
import pytest
from nbclient import NotebookClient

from job_analysis import bronze
from job_analysis import db
from job_analysis import run_pipeline
from job_analysis import silver


def _store_ashby_board(copper_dir, company, source_date, jobs):
    conn = db.open_copper("ashby", base_dir=str(copper_dir))
    db.store_copper(
        conn,
        url=f"https://api.ashbyhq.com/posting-api/job-board/{company}",
        http_status=200,
        content=json.dumps({"jobs": jobs}),
        source_date=source_date,
    )


def _store_greenhouse_board(copper_dir, company, source_date, jobs):
    conn = db.open_copper("greenhouse", base_dir=str(copper_dir))
    db.store_copper(
        conn,
        url=f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs",
        http_status=200,
        content=json.dumps({"jobs": jobs}),
        source_date=source_date,
    )


def _run_layers(board, company, tmp_path):
    copper_dir = tmp_path / "copper"
    bronze_dir = tmp_path / "bronze"
    silver_dir = tmp_path / "silver"
    bronze.derive(
        board,
        company,
        copper_base_dir=str(copper_dir),
        bronze_base_dir=str(bronze_dir),
    )
    silver.process(
        board,
        company,
        bronze_base_dir=str(bronze_dir),
        silver_base_dir=str(silver_dir),
    )
    return {
        "copper_dir": copper_dir,
        "bronze_dir": bronze_dir,
        "silver_dir": silver_dir,
        "silver": db.open_silver(base_dir=str(silver_dir)),
    }


def _description(skill="Python", yoe="5+ years", salary="$120,000 - $180,000"):
    return f"""
    <section>
      <p>Annual Salary Range: {salary} USD annually</p>
      <p>Build services from scratch and own the roadmap.</p>
      <p>Requires {yoe} of experience with {skill}, Kubernetes, and SQL.</p>
      <ul>
        <li>Bachelor's degree in Computer Science or equivalent experience.</li>
        <li>Cross-functional stakeholder management.</li>
      </ul>
    </section>
    """


def _ashby_job(job_id, title, department="Software", location="Remote - US", yoe="5+ years",
               skill="Python", salary="$120,000 - $180,000"):
    return {
        "id": job_id,
        "title": title,
        "department": department,
        "location": location,
        "jobUrl": f"https://jobs.ashbyhq.com/acme/{job_id}",
        "content": _description(skill=skill, yoe=yoe, salary=salary),
    }


def _greenhouse_job(job_id, title, department="Engineering", location="New York, NY"):
    return {
        "id": job_id,
        "title": title,
        "absolute_url": f"https://job-boards.greenhouse.io/acme/jobs/{job_id}",
        "departments": [{"name": department}],
        "location": {"name": location},
        "content": _description(skill="Go", yoe="3+ years"),
    }


def test_gold_salary_contract_for_ashby_and_greenhouse(tmp_path):
    _store_ashby_board(
        tmp_path / "ashby" / "copper",
        "acme",
        "20260101",
        [_ashby_job("ashby-1", "Senior Software Engineer")],
    )
    ashby_layers = _run_layers("ashby", "acme", tmp_path / "ashby")

    _store_greenhouse_board(
        tmp_path / "greenhouse" / "copper",
        "acme",
        "20260101",
        [_greenhouse_job(12345, "Staff Platform Engineer")],
    )
    greenhouse_layers = _run_layers("greenhouse", "acme", tmp_path / "greenhouse")

    for conn, job_id, seniority, work_mode, location in [
        (ashby_layers["silver"], "ashby-1", "Senior", "Remote-Friendly", "Remote - US"),
        (greenhouse_layers["silver"], "12345", "Staff / Principal", "Office-Only", "New York, NY"),
    ]:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        assert row["salary_min"] == 120000
        assert row["salary_max"] == 180000
        assert row["currency"] == "USD"
        assert row["salary_unit"] == "annual"
        assert row["has_salary"] == 1
        assert row["department"] == "Engineering"
        assert row["seniority"] == seniority
        assert row["work_mode"] == work_mode
        assert row["location"] == location


def test_gold_nlp_contract_populates_description_and_yoe_from_api_content(tmp_path):
    _store_ashby_board(
        tmp_path / "copper",
        "acme",
        "20260101",
        [_ashby_job("nlp-1", "Senior Machine Learning Engineer")],
    )
    layers = _run_layers("ashby", "acme", tmp_path)

    row = layers["silver"].execute("SELECT * FROM jobs WHERE job_id='nlp-1'").fetchone()
    assert row["description_md"]
    assert "Python" in row["description_md"]
    assert "Bachelor" in row["description_md"]
    assert row["yoe"] == 5
    assert row["salary_min"] == 120000
    assert row["department"] == "Engineering"


def test_gold_historical_contract_preserves_multiple_source_dates(tmp_path):
    _store_ashby_board(
        tmp_path / "copper",
        "acme",
        "20260101",
        [_ashby_job("hist-1", "Senior Software Engineer")],
    )
    _store_ashby_board(
        tmp_path / "copper",
        "acme",
        "20260401",
        [
            _ashby_job("hist-1", "Senior Software Engineer"),
            _ashby_job("hist-2", "Engineering Manager", yoe="8+ years"),
        ],
    )
    layers = _run_layers("ashby", "acme", tmp_path)

    rows = layers["silver"].execute(
        "SELECT job_id, source_date FROM jobs ORDER BY job_id, source_date"
    ).fetchall()
    assert [(row["job_id"], row["source_date"]) for row in rows] == [
        ("hist-1", "20260101"),
        ("hist-1", "20260401"),
        ("hist-2", "20260401"),
    ]


def test_gold_cross_layer_trace_contract(tmp_path):
    _store_ashby_board(
        tmp_path / "copper",
        "acme",
        "20260101",
        [_ashby_job("trace-1", "Senior Software Engineer")],
    )
    layers = _run_layers("ashby", "acme", tmp_path)

    silver_row = layers["silver"].execute(
        "SELECT bronze_id FROM jobs WHERE job_id='trace-1'"
    ).fetchone()
    bronze_conn = db.open_bronze("ashby", base_dir=str(layers["bronze_dir"]))
    bronze_row = bronze_conn.execute(
        "SELECT copper_id FROM snapshots WHERE id=?",
        (silver_row["bronze_id"],),
    ).fetchone()
    copper_conn = db.open_copper("ashby", base_dir=str(layers["copper_dir"]))
    copper_row = copper_conn.execute(
        "SELECT content FROM snapshots WHERE id=?",
        (bronze_row["copper_id"],),
    ).fetchone()

    assert "trace-1" in copper_row["content"]


ACME = {"COMPANY": "acme", "BOARD": "ashby"}


# expected_jobs: rows the notebook reports after loading. acme has 8 distinct jobs over
# 14 snapshot rows, so 8 proves snapshot-level notebooks dedupe to the latest per job.
@pytest.mark.parametrize("notebook, config, expected_jobs", [
    pytest.param("analyze_salaries.ipynb", ACME, 8, id="salaries"),
    pytest.param("analyze_nlp.ipynb", ACME, 8, id="nlp"),
    pytest.param("analyze_historical.ipynb", ACME, 14, id="historical"),
    pytest.param("analyze_role_gap.ipynb", {**ACME, "JOB_ID": "tw-1"}, 8, id="role_gap"),
    pytest.param("analyze_role_gap.ipynb", {"COMPANY": "nopay", "BOARD": "ashby", "JOB_ID": "np-1"}, 2,
                 id="role_gap_no_salary"),
    pytest.param("analyze_cross_company.ipynb", {}, 8, id="cross_company"),
])
def test_gold_notebook_executes_on_etl_output(notebook, config, expected_jobs, tmp_path, monkeypatch):
    # Two snapshots: old-1 closes, new-1 opens; the TW role feeds role-gap and cross-company.
    first = [
        _ashby_job("tw-1", "Senior Technical Writer", skill="Markdown", salary="$140,000 - $170,000"),
        _ashby_job("eng-1", "Senior Software Engineer", skill="Python", salary="$160,000 - $210,000"),
        _ashby_job("eng-2", "Senior Backend Engineer", skill="Go", salary="$150,000 - $200,000"),
        _ashby_job("eng-3", "Staff Software Engineer", skill="Rust", yoe="8+ years", salary="$200,000 - $260,000"),
        _ashby_job("pm-1", "Senior Product Manager", department="Product and Design", skill="Roadmaps"),
        _ashby_job("mkt-1", "Marketing Manager", department="Marketing", location="New York, NY", skill="SEO"),
        _ashby_job("old-1", "Software Engineer", skill="Java", yoe="2+ years", salary="$110,000 - $140,000"),
    ]
    second = first[:-1] + [_ashby_job("new-1", "Senior Data Engineer", skill="Spark", salary="$155,000 - $205,000")]
    _store_ashby_board(tmp_path / "copper", "acme", "20010115", first)
    _store_ashby_board(tmp_path / "copper", "acme", "20010415", second)
    _run_layers("ashby", "acme", tmp_path)
    # A board that discloses no pay at all (common on Greenhouse).
    nopay = [_ashby_job("np-1", "Senior Technical Writer", salary=""), _ashby_job("np-2", "Software Engineer", salary="")]
    _store_ashby_board(tmp_path / "copper", "nopay", "20010115", nopay)
    _store_ashby_board(tmp_path / "copper", "nopay", "20010415", nopay)
    _run_layers("ashby", "nopay", tmp_path)

    # The kernel is a fresh process: it finds the fixture DBs and the package via env.
    monkeypatch.setenv("JOB_ANALYSIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PYTHONPATH", str(run_pipeline.REPO_ROOT))
    monkeypatch.setenv("MPLBACKEND", "Agg")
    injected = Path(run_pipeline.inject_notebook_config(notebook, config))
    try:
        nb = nbformat.read(injected, as_version=4)
    finally:
        injected.unlink()

    NotebookClient(
        nb, kernel_name="python3", timeout=180,
        resources={"metadata": {"path": str(run_pipeline.NOTEBOOK_DIR)}},
    ).execute()  # raises CellExecutionError on any failing cell

    printed = "".join(
        o.get("text", "") for c in nb.cells if c.cell_type == "code" for o in c.get("outputs", [])
    )
    # 2001 snapshots prove it read the fixture, not whatever is in the real data/ directory.
    assert f"DATA QUALITY: {expected_jobs} jobs" in printed
    assert "snapshots 2001-" in printed
