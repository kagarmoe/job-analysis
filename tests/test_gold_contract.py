import json

import bronze
import db
import silver


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


def _description(skill="Python", yoe="5+ years"):
    return f"""
    <section>
      <p>Annual Salary Range: $120,000 - $180,000 USD annually</p>
      <p>Build services from scratch and own the roadmap.</p>
      <p>Requires {yoe} of experience with {skill}, Kubernetes, and SQL.</p>
      <ul>
        <li>Bachelor's degree in Computer Science or equivalent experience.</li>
        <li>Cross-functional stakeholder management.</li>
      </ul>
    </section>
    """


def _ashby_job(job_id, title, department="Software", location="Remote - US", yoe="5+ years"):
    return {
        "id": job_id,
        "title": title,
        "department": department,
        "location": location,
        "jobUrl": f"https://jobs.ashbyhq.com/acme/{job_id}",
        "content": _description(yoe=yoe),
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

    for conn, job_id in [
        (ashby_layers["silver"], "ashby-1"),
        (greenhouse_layers["silver"], "12345"),
    ]:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        assert row["salary_min"] == 120000
        assert row["salary_max"] == 180000
        assert row["currency"] == "USD"
        assert row["salary_unit"] == "annual"
        assert row["has_salary"] == 1
        assert row["department"]
        assert row["seniority"]
        assert row["work_mode"]
        assert row["location"]


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


def test_gold_role_gap_contract_has_target_and_comparables(tmp_path):
    jobs = [
        _ashby_job("target-1", "Senior Software Engineer", yoe="5+ years"),
        _ashby_job("comp-1", "Senior Backend Engineer", yoe="5+ years"),
        _ashby_job("comp-2", "Staff Software Engineer", yoe="7+ years"),
        _ashby_job("comp-3", "Engineering Manager", yoe="8+ years"),
        _ashby_job("fallback-1", "Senior Product Manager", department="Product", yoe="5+ years"),
    ]
    _store_ashby_board(tmp_path / "copper", "acme", "20260101", jobs)
    layers = _run_layers("ashby", "acme", tmp_path)

    rows = layers["silver"].execute(
        "SELECT * FROM jobs WHERE company='acme' AND board='ashby'"
    ).fetchall()
    target = [row for row in rows if row["job_id"] == "target-1"][0]
    same_department = [
        row for row in rows
        if row["job_id"] != "target-1" and row["department"] == target["department"]
    ]
    fallback = [
        row for row in rows
        if row["job_id"] != "target-1" and row["department"] != target["department"]
    ]

    assert target["salary_min"] is not None
    assert target["salary_max"] is not None
    assert target["description_md"]
    assert target["department"]
    assert same_department
    assert fallback
    for row in same_department + fallback:
        assert isinstance(row["job_id"], str)
        assert row["description_md"]
        assert row["salary_min"] is not None
        assert row["salary_max"] is not None


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
