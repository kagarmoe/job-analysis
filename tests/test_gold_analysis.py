import pandas as pd

from gold_analysis import (
    extract_required_yoe,
    score_scope,
    select_role_gap_comparables,
    split_locations,
)


def test_split_locations_handles_multi_value_and_missing_inputs():
    assert split_locations("New York, NY | Remote; London") == [
        "New York, NY",
        "Remote",
        "London",
    ]
    assert split_locations(None) == ["Unknown"]
    assert split_locations("") == ["Unknown"]


def test_extract_required_yoe_uses_highest_minimum_requirement():
    text = """
    Requires 3-5 years of experience building APIs.
    You should also have 7+ years of professional software engineering work.
    """
    assert extract_required_yoe(text) == 7


def test_extract_required_yoe_rejects_out_of_range_values():
    assert extract_required_yoe("Requires 30+ years of experience.") is None


def test_score_scope_rewards_builder_and_owner_language():
    assert score_scope("Build from scratch, own the roadmap, and grow the team.") > 5
    assert score_scope("Join a team and support the team on existing systems.") < 5
    assert score_scope(None) == 5


def test_select_role_gap_comparables_prefers_same_department_then_relaxes():
    df = pd.DataFrame(
        [
            {"job_id": "target", "department": "Engineering", "scope_score": 7, "mid_usd": 200000},
            {"job_id": "eng-1", "department": "Engineering", "scope_score": 6, "mid_usd": 180000},
            {"job_id": "eng-2", "department": "Engineering", "scope_score": 8, "mid_usd": 190000},
            {"job_id": "eng-3", "department": "Engineering", "scope_score": 4, "mid_usd": 175000},
            {"job_id": "prod-1", "department": "Product", "scope_score": 6, "mid_usd": 170000},
            {"job_id": "prod-2", "department": "Product", "scope_score": 7, "mid_usd": 172000},
        ]
    )

    comparables, tolerance, strategy = select_role_gap_comparables(
        df,
        target_department="Engineering",
        target_scope=7,
        target_job_id="target",
        minimum_count=3,
    )

    assert set(comparables["job_id"]) == {"eng-1", "eng-2", "eng-3"}
    assert tolerance == 3
    assert strategy == "same_department_scope_3"

    comparables, tolerance, strategy = select_role_gap_comparables(
        df,
        target_department="Engineering",
        target_scope=7,
        target_job_id="target",
        minimum_count=5,
    )

    assert set(comparables["job_id"]) == {"eng-1", "eng-2", "eng-3", "prod-1", "prod-2"}
    assert tolerance == 3
    assert strategy == "cross_department_scope_3"
