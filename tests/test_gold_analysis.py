import pandas as pd

from gold_analysis import (
    build_active_role_timeseries,
    build_active_closed_comparison,
    build_historical_dataset,
    build_monthly_hiring_activity,
    build_skill_overlap_matrix,
    build_time_to_fill_dataset,
    extract_required_yoe,
    extract_skill_phrases,
    score_scope,
    select_role_gap_comparables,
    split_locations,
    summarize_recurring_roles,
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


def test_build_historical_dataset_derives_first_last_and_active_flags():
    df = pd.DataFrame(
        [
            {"job_id": "1", "source_date": "20260101", "salary_min": 100000, "salary_max": 150000, "currency": "USD"},
            {"job_id": "1", "source_date": "20260215", "salary_min": 100000, "salary_max": 150000, "currency": "USD"},
            {"job_id": "2", "source_date": "20260120", "salary_min": None, "salary_max": None, "currency": None},
            {"job_id": "2", "source_date": "20260125", "salary_min": None, "salary_max": None, "currency": None},
        ]
    )

    hist, hist_salary = build_historical_dataset(df)

    assert set(hist["job_id"]) == {"1", "2"}
    row1 = hist.loc[hist["job_id"] == "1"].iloc[0]
    row2 = hist.loc[hist["job_id"] == "2"].iloc[0]
    assert row1["first_seen"].strftime("%Y-%m-%d") == "2026-01-01"
    assert row1["last_seen"].strftime("%Y-%m-%d") == "2026-02-15"
    assert row1["month_posted"] == pd.Period("2026-01", freq="M")
    assert bool(row1["is_active"]) is True
    assert bool(row2["is_active"]) is False
    assert set(hist_salary["job_id"]) == {"1"}


def test_build_active_role_timeseries_counts_open_roles_over_time():
    hist = pd.DataFrame(
        [
            {"job_id": "1", "first_seen": pd.Timestamp("2026-01-01"), "last_seen": pd.Timestamp("2026-01-15")},
            {"job_id": "2", "first_seen": pd.Timestamp("2026-01-10"), "last_seen": pd.Timestamp("2026-01-20")},
        ]
    )

    series = build_active_role_timeseries(hist, freq="5D")

    assert list(series["date"].dt.strftime("%Y-%m-%d")) == [
        "2026-01-01",
        "2026-01-06",
        "2026-01-11",
        "2026-01-16",
    ]
    assert list(series["active_roles"]) == [1, 1, 2, 1]


def test_build_monthly_hiring_activity_counts_new_and_closed_roles():
    hist = pd.DataFrame(
        [
            {"job_id": "1", "first_seen": pd.Timestamp("2026-01-01"), "last_seen": pd.Timestamp("2026-01-20"), "is_active": False},
            {"job_id": "2", "first_seen": pd.Timestamp("2026-01-15"), "last_seen": pd.Timestamp("2026-01-30"), "is_active": False},
            {"job_id": "3", "first_seen": pd.Timestamp("2026-02-10"), "last_seen": pd.Timestamp("2026-03-01"), "is_active": True},
        ]
    )

    monthly_new, monthly_closed = build_monthly_hiring_activity(hist)

    assert monthly_new.loc[pd.Period("2026-01", freq="M")] == 2
    assert monthly_new.loc[pd.Period("2026-02", freq="M")] == 1
    assert monthly_closed.loc[pd.Period("2026-01", freq="M")] == 2
    assert monthly_closed.index.dtype.name == "period[M]"


def test_build_time_to_fill_dataset_filters_zero_day_roles():
    hist = pd.DataFrame(
        [
            {"job_id": "1", "first_seen": pd.Timestamp("2026-01-01"), "last_seen": pd.Timestamp("2026-01-03"), "is_active": False},
            {"job_id": "2", "first_seen": pd.Timestamp("2026-01-02"), "last_seen": pd.Timestamp("2026-01-02"), "is_active": False},
            {"job_id": "3", "first_seen": pd.Timestamp("2026-01-03"), "last_seen": pd.Timestamp("2026-01-10"), "is_active": True},
        ]
    )

    closed_valid = build_time_to_fill_dataset(hist)

    assert list(closed_valid["job_id"]) == ["1"]
    assert int(closed_valid.iloc[0]["days_open"]) == 2


def test_build_active_closed_comparison_returns_status_summaries():
    hist = pd.DataFrame(
        [
            {"job_id": "1", "department": "Engineering", "seniority": "Senior", "is_active": True},
            {"job_id": "2", "department": "Engineering", "seniority": "Senior", "is_active": False},
            {"job_id": "3", "department": "Product", "seniority": "Manager", "is_active": False},
        ]
    )
    hist_salary = pd.DataFrame(
        [
            {"job_id": "1", "mid_usd": 220000, "is_active": True},
            {"job_id": "2", "mid_usd": 180000, "is_active": False},
            {"job_id": "3", "mid_usd": 160000, "is_active": False},
        ]
    )

    comparison = build_active_closed_comparison(
        hist,
        hist_salary,
        seniority_order=["Senior", "Manager", "Director+"],
    )

    assert list(comparison["hist_salary"]["status"]) == ["Active", "Closed", "Closed"]
    assert comparison["dept_pct"].loc["Engineering", "Active"] == 100
    assert comparison["dept_pct"].loc["Engineering", "Closed"] == 50
    assert comparison["seniority_counts"].loc["Senior", "Active"] == 1
    assert comparison["seniority_counts"].loc["Manager", "Closed"] == 1
    assert "Director+" not in comparison["seniority_counts"].index
    assert comparison["salary_summary"].loc["Active", "count"] == 1
    assert comparison["salary_summary"].loc["Closed", "median"] == 170000


def test_build_active_closed_comparison_handles_missing_salary_status():
    hist = pd.DataFrame(
        [
            {"job_id": "1", "department": "Engineering", "seniority": "Senior", "is_active": True},
            {"job_id": "2", "department": "Product", "seniority": "Manager", "is_active": False},
        ]
    )
    hist_salary = pd.DataFrame(
        [
            {"job_id": "2", "mid_usd": 180000, "is_active": False},
        ]
    )

    comparison = build_active_closed_comparison(
        hist,
        hist_salary,
        seniority_order=["Senior", "Manager"],
    )

    assert comparison["salary_summary"].loc["Active", "count"] == 0
    assert pd.isna(comparison["salary_summary"].loc["Active", "median"])
    assert comparison["salary_summary"].loc["Closed", "count"] == 1


def test_summarize_recurring_roles_tracks_salary_change_by_normalized_title():
    hist_salary = pd.DataFrame(
        [
            {"job_id": "1", "title": "Senior Engineer", "first_seen": pd.Timestamp("2026-01-01"), "mid_usd": 180000},
            {"job_id": "2", "title": " senior engineer ", "first_seen": pd.Timestamp("2026-03-01"), "mid_usd": 210000},
            {"job_id": "3", "title": "Product Manager", "first_seen": pd.Timestamp("2026-02-01"), "mid_usd": 170000},
        ]
    )

    recurring = summarize_recurring_roles(hist_salary)

    assert list(recurring.index) == ["senior engineer"]
    row = recurring.iloc[0]
    assert row["postings"] == 2
    assert row["display_title"] == "Senior Engineer"
    assert row["earliest_mid"] == 180000
    assert row["latest_mid"] == 210000
    assert round(row["salary_change_pct"], 1) == 16.7


def test_extract_skill_phrases_returns_repeated_meaningful_bigrams():
    text = """
    You will build distributed systems and improve distributed systems reliability.
    The role owns model serving and model serving performance.
    """
    phrases = extract_skill_phrases(text, top_n=5, min_count=2)
    assert phrases == {"distributed systems": 2, "model serving": 2}


def test_build_skill_overlap_matrix_scores_roles_on_target_phrases():
    roles = pd.DataFrame(
        [
            {"job_id": "1", "title": "Target Role", "description_md": "distributed systems distributed systems model serving"},
            {"job_id": "2", "title": "Comparable Role", "description_md": "model serving and distributed systems"},
            {"job_id": "3", "title": "Other Role", "description_md": "finance operations"},
        ]
    )

    overlap = build_skill_overlap_matrix(
        roles,
        {"distributed systems": 2, "model serving": 2},
    )

    assert list(overlap.index) == ["Target Role", "Comparable Role", "Other Role"]
    assert list(overlap.columns) == ["distributed systems", "model serving"]
    assert overlap.loc["Target Role", "distributed systems"] == 2
    assert overlap.loc["Comparable Role", "model serving"] == 1
    assert overlap.loc["Other Role", "distributed systems"] == 0
