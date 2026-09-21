import pandas as pd

from gold_analysis import (
    build_active_role_timeseries,
    build_active_closed_comparison,
    build_department_quarterly_salary_trends,
    build_department_skill_matrix,
    build_education_requirement_summary,
    build_historical_dataset,
    build_monthly_hiring_activity,
    build_quarterly_salary_stats,
    build_cluster_profiles,
    build_description_length_analysis,
    build_skill_overlap_matrix,
    build_skill_mention_counts,
    build_tfidf_cluster_projection,
    build_time_to_fill_dataset,
    build_yoe_dataset,
    extract_required_yoe,
    extract_skill_phrases,
    score_scope,
    select_role_gap_comparables,
    split_locations,
    summarize_yoe_by_department,
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


def test_build_skill_mention_counts_counts_matching_descriptions_once_per_role():
    jobs = pd.DataFrame(
        [
            {"description_md": "Python Python and SQL", "department": "Engineering"},
            {"description_md": "Java services", "department": "Engineering"},
            {"description_md": "No listed tools", "department": "Product"},
            {"description_md": None, "department": "Product"},
        ]
    )

    counts = build_skill_mention_counts(
        jobs,
        skill_patterns={
            "Python": r"\bPython\b",
            "SQL": r"\bSQL\b",
            "Java": r"\bJava\b",
            "Rust": r"\bRust\b",
        },
    )

    assert counts.to_dict() == {"Java": 1, "Python": 1, "SQL": 1}


def test_build_department_skill_matrix_returns_department_percentages():
    jobs = pd.DataFrame(
        [
            {"description_md": "Python and SQL", "department": "Engineering"},
            {"description_md": "Python", "department": "Engineering"},
            {"description_md": "SQL", "department": "Product"},
            {"description_md": None, "department": "Product"},
            {"description_md": "Python", "department": "Other"},
        ]
    )

    matrix = build_department_skill_matrix(
        jobs,
        ["Python", "SQL"],
        skill_patterns={"Python": r"\bPython\b", "SQL": r"\bSQL\b"},
    )

    assert list(matrix.index) == ["Engineering", "Product"]
    assert list(matrix.columns) == ["Python", "SQL"]
    assert matrix.loc["Engineering", "Python"] == 100
    assert matrix.loc["Engineering", "SQL"] == 50
    assert matrix.loc["Product", "Python"] == 0
    assert matrix.loc["Product", "SQL"] == 50


def test_build_yoe_dataset_and_department_summary():
    jobs = pd.DataFrame(
        [
            {"description_md": "Requires 3+ years of experience", "department": "Engineering"},
            {"description_md": "Requires 5+ years of experience", "department": "Engineering"},
            {"description_md": "Requires 7+ years of experience", "department": "Engineering"},
            {"description_md": "Requires 2+ years of experience", "department": "Product"},
            {"description_md": "No explicit requirement", "department": "Product"},
        ]
    )

    with_yoe = build_yoe_dataset(jobs)
    yoe_jobs = with_yoe.dropna(subset=["yoe"])
    summary = summarize_yoe_by_department(yoe_jobs, min_count=2)

    assert list(with_yoe["yoe"])[:4] == [3, 5, 7, 2]
    assert pd.isna(with_yoe.loc[4, "yoe"])
    assert list(summary.index) == ["Engineering"]
    assert summary.loc["Engineering", "median"] == 5
    assert summary.loc["Engineering", "mean"] == 5
    assert summary.loc["Engineering", "count"] == 3


def test_build_education_requirement_summary_counts_overall_and_by_department():
    jobs = pd.DataFrame(
        [
            {"description_md": "Bachelor's degree in computer science", "department": "Engineering"},
            {"description_md": "Master's degree preferred", "department": "Engineering"},
            {"description_md": "No degree required", "department": "Product"},
            {"description_md": "PhD required", "department": "Other"},
        ]
    )

    edu_series, edu_dept = build_education_requirement_summary(
        jobs,
        education_patterns={
            "PhD": r"\bPhD\b",
            "Master": r"\bMaster'?s?\b",
            "Bachelor": r"\bBachelor'?s?\b",
        },
    )

    assert edu_series.to_dict() == {"Bachelor": 1, "Master": 1, "PhD": 1}
    assert list(edu_dept.index) == ["Engineering", "Product"]
    assert list(edu_dept.columns) == ["Bachelor", "Master", "PhD"]
    assert edu_dept.loc["Engineering", "Bachelor"] == 50
    assert edu_dept.loc["Engineering", "Master"] == 50
    assert edu_dept.loc["Product", "Bachelor"] == 0


def test_build_tfidf_cluster_projection_skips_small_corpus():
    jobs = pd.DataFrame(
        [
            {"description_md": "python platform systems", "department": "Engineering"},
            {"description_md": "product research strategy", "department": "Product"},
        ]
    )

    result = build_tfidf_cluster_projection(jobs, min_documents=3)

    assert len(result.df_cluster) == 2
    assert result.tfidf is None
    assert result.km is None
    assert result.skipped_reason == "Not enough job descriptions for clustering (2 available, need 3+). Skipping."


def test_build_tfidf_cluster_projection_retries_then_clusters_sparse_corpus():
    jobs = pd.DataFrame(
        [
            {"description_md": f"uniquealpha{i} uniquebeta{i}", "department": "Engineering", "mid_usd": 100000 + i}
            for i in range(10)
        ]
    )

    result = build_tfidf_cluster_projection(jobs, min_documents=10, max_clusters=4)

    assert result.initial_error is not None
    assert "After pruning, no terms remain" in result.initial_error
    assert result.skipped_reason is None
    assert result.tfidf is not None
    assert result.tfidf_matrix is not None
    assert result.svd is not None
    assert result.km is not None
    assert result.tfidf_matrix.shape[0] == 10
    assert {"x", "y", "cluster"}.issubset(result.df_cluster.columns)
    assert result.df_cluster["cluster"].nunique() <= 4
    assert result.svd_explained_variance_pct >= 0


def test_build_tfidf_cluster_projection_reports_retry_failure():
    jobs = pd.DataFrame(
        [
            {"description_md": "and the or but", "department": "Engineering"}
            for _ in range(10)
        ]
    )

    result = build_tfidf_cluster_projection(jobs, min_documents=10)

    assert result.initial_error is not None
    assert result.retry_error is not None
    assert result.tfidf is None
    assert result.km is None
    assert result.skipped_reason is not None
    assert result.skipped_reason.startswith("TF-IDF unavailable after retry")


def test_build_cluster_profiles_summarizes_terms_departments_and_salary():
    jobs = pd.DataFrame(
        [
            {"description_md": f"uniquealpha{i} uniquebeta{i}", "department": "Engineering", "mid_usd": 100000 + i}
            for i in range(10)
        ]
    )
    result = build_tfidf_cluster_projection(jobs, min_documents=10, max_clusters=3)

    profiles = build_cluster_profiles(result, top_terms=3)

    assert not profiles.empty
    assert set(profiles.columns) == {
        "cluster",
        "role_count",
        "top_terms",
        "top_departments",
        "median_salary",
    }
    assert profiles["role_count"].sum() == len(result.df_cluster)
    assert all(isinstance(terms, list) for terms in profiles["top_terms"])
    assert all(isinstance(departments, str) for departments in profiles["top_departments"])


def test_build_description_length_analysis_derives_metrics_and_salary_relationships():
    jobs = pd.DataFrame(
        [
            {
                "description_md": "alpha\n- build",
                "department": "Engineering",
                "mid_usd": 100000,
            },
            {
                "description_md": "alpha beta gamma delta",
                "department": "Engineering",
                "mid_usd": 150000,
            },
            {
                "description_md": "alpha beta gamma delta epsilon zeta",
                "department": "Product",
                "mid_usd": 200000,
            },
            {
                "description_md": "alpha beta",
                "department": "Product",
                "mid_usd": None,
            },
        ]
    )

    analysis = build_description_length_analysis(jobs)

    assert {"desc_len", "desc_words", "n_bullets"}.issubset(analysis.df.columns)
    assert analysis.df.loc[0, "desc_words"] == 3
    assert analysis.df.loc[0, "n_bullets"] == 1
    assert list(analysis.df_len_sal.index) == [0, 1, 2]
    assert list(analysis.department_median_words.index) == ["Engineering", "Product"]
    assert analysis.department_median_words.loc["Engineering"] == 3.5
    assert analysis.correlations is not None
    assert set(analysis.correlations.columns) == {"desc_words", "n_bullets", "mid_usd"}
    assert analysis.word_salary_trend is not None
    slope, intercept = analysis.word_salary_trend
    assert slope > 0
    assert intercept < 100000


def test_build_description_length_analysis_handles_insufficient_salary_data():
    jobs = pd.DataFrame(
        [
            {"description_md": "alpha beta", "department": "Engineering", "mid_usd": 100000},
            {"description_md": "alpha beta gamma", "department": "Product", "mid_usd": None},
        ]
    )

    analysis = build_description_length_analysis(jobs, min_salary_rows=3)

    assert len(analysis.df_len_sal) == 1
    assert analysis.correlations is None
    assert analysis.word_salary_trend is None
    assert not analysis.department_median_words.empty


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


def test_build_quarterly_salary_stats_returns_empty_contract_without_salary_data():
    hist_salary = pd.DataFrame(columns=["first_seen", "mid_usd"])

    salary_with_quarter, qtr_stats = build_quarterly_salary_stats(hist_salary)

    assert salary_with_quarter.empty
    assert list(qtr_stats.columns) == ["median", "mean", "count", "std"]
    assert qtr_stats.empty


def test_build_quarterly_salary_stats_derives_timestamp_index_and_numeric_stats():
    hist_salary = pd.DataFrame(
        [
            {"job_id": "1", "first_seen": pd.Timestamp("2026-01-05"), "mid_usd": 100000},
            {"job_id": "2", "first_seen": pd.Timestamp("2026-02-10"), "mid_usd": 140000},
            {"job_id": "3", "first_seen": pd.Timestamp("2026-04-01"), "mid_usd": 180000},
        ]
    )

    salary_with_quarter, qtr_stats = build_quarterly_salary_stats(hist_salary)

    assert "quarter" in salary_with_quarter.columns
    assert "quarter" not in hist_salary.columns
    assert list(salary_with_quarter["quarter"]) == [
        pd.Period("2026Q1", freq="Q-DEC"),
        pd.Period("2026Q1", freq="Q-DEC"),
        pd.Period("2026Q2", freq="Q-DEC"),
    ]
    assert list(qtr_stats.index) == [
        pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-04-01"),
    ]
    assert qtr_stats.loc[pd.Timestamp("2026-01-01"), "median"] == 120000
    assert qtr_stats.loc[pd.Timestamp("2026-01-01"), "mean"] == 120000
    assert qtr_stats.loc[pd.Timestamp("2026-01-01"), "count"] == 2
    assert qtr_stats["median"].dtype.kind in {"f", "i"}


def test_build_department_quarterly_salary_trends_filters_for_meaningful_data():
    hist_salary = pd.DataFrame(
        [
            {"job_id": "eng-q1-1", "first_seen": pd.Timestamp("2026-01-05"), "department": "Engineering", "mid_usd": 100000},
            {"job_id": "eng-q1-2", "first_seen": pd.Timestamp("2026-01-10"), "department": "Engineering", "mid_usd": 120000},
            {"job_id": "eng-q1-3", "first_seen": pd.Timestamp("2026-02-01"), "department": "Engineering", "mid_usd": 140000},
            {"job_id": "eng-q2-1", "first_seen": pd.Timestamp("2026-04-01"), "department": "Engineering", "mid_usd": 160000},
            {"job_id": "eng-q2-2", "first_seen": pd.Timestamp("2026-04-10"), "department": "Engineering", "mid_usd": 180000},
            {"job_id": "eng-q2-3", "first_seen": pd.Timestamp("2026-05-01"), "department": "Engineering", "mid_usd": 200000},
            {"job_id": "prod-q1-1", "first_seen": pd.Timestamp("2026-01-05"), "department": "Product", "mid_usd": 150000},
            {"job_id": "prod-q1-2", "first_seen": pd.Timestamp("2026-01-10"), "department": "Product", "mid_usd": 160000},
            {"job_id": "prod-q1-3", "first_seen": pd.Timestamp("2026-02-01"), "department": "Product", "mid_usd": 170000},
            {"job_id": "other-q1-1", "first_seen": pd.Timestamp("2026-01-05"), "department": "Other", "mid_usd": 110000},
            {"job_id": "other-q1-2", "first_seen": pd.Timestamp("2026-01-10"), "department": "Other", "mid_usd": 120000},
            {"job_id": "other-q1-3", "first_seen": pd.Timestamp("2026-02-01"), "department": "Other", "mid_usd": 130000},
            {"job_id": "other-q2-1", "first_seen": pd.Timestamp("2026-04-01"), "department": "Other", "mid_usd": 140000},
            {"job_id": "other-q2-2", "first_seen": pd.Timestamp("2026-04-10"), "department": "Other", "mid_usd": 150000},
            {"job_id": "other-q2-3", "first_seen": pd.Timestamp("2026-05-01"), "department": "Other", "mid_usd": 160000},
        ]
    )

    dept_qtr = build_department_quarterly_salary_trends(hist_salary)

    assert list(dept_qtr.columns) == ["Engineering"]
    assert list(dept_qtr.index) == [
        pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-04-01"),
    ]
    assert dept_qtr.loc[pd.Timestamp("2026-01-01"), "Engineering"] == 120000
    assert dept_qtr.loc[pd.Timestamp("2026-04-01"), "Engineering"] == 180000


def test_build_department_quarterly_salary_trends_handles_no_salary_data():
    assert build_department_quarterly_salary_trends(pd.DataFrame()).empty


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


def test_latest_per_job_keeps_newest_snapshot_per_job():
    from gold_analysis import latest_per_job

    # silver is keyed on (company, board, job_id, source_date): one row per snapshot
    df = pd.DataFrame({
        "job_id": ["a", "a", "b", "a"],
        "source_date": ["20260325", "20210707042647", "20260101", "20260609"],
        "title": ["mid", "oldest", "only", "newest"],
    })
    latest = latest_per_job(df)

    assert sorted(latest["title"]) == ["newest", "only"]


def test_build_historical_dataset_keeps_latest_snapshot_row():
    df = pd.DataFrame({
        "job_id": ["a", "a"],
        "source_date": ["20260101", "20260609"],
        "title": ["Writer", "Staff Writer"],
        "salary_min": [100000, 150000],
        "salary_max": [120000, 170000],
        "currency": ["USD", "USD"],
        "salary_unit": ["annual", "annual"],
    })
    hist, _ = build_historical_dataset(df)

    assert hist["title"].tolist() == ["Staff Writer"]
    assert hist["salary_min"].tolist() == [150000]


def test_coverage_label_reports_n_and_disclosure_rate():
    from gold_analysis import coverage_label

    df_all = pd.DataFrame({"job_id": ["a", "b", "c", "d"]})
    df_salary = df_all.iloc[:1]
    assert coverage_label(df_all, df_salary) == "n=1 of 4 jobs (25%) disclose salary"
    assert coverage_label(df_all.iloc[:0], df_salary.iloc[:0]) == "n=0 of 0 jobs disclose salary"


def test_build_relative_position_uses_same_seniority_peers_and_flags_thin_pools():
    from gold_analysis import build_relative_position

    df = pd.DataFrame({
        "job_id": ["tw", "a", "b", "c", "d", "e", "x"],
        "title": ["Senior TW", "a", "b", "c", "d", "e", "Staff x"],
        "seniority": ["Senior"] * 6 + ["Staff / Principal"],
        "mid_usd": [150.0, 100.0, 200.0, 300.0, 400.0, 500.0, 999.0],
        "location": ["Remote"] * 7,
    })
    pos = build_relative_position(df, "tw")

    assert pos["n"] == 5 and pos["comp_median"] == 300.0
    assert (pos["q1"], pos["q3"]) == (200.0, 400.0)
    assert pos["gap_pct"] == -50.0
    assert pos["percentile"] == 20.0  # one of five peers is below the target
    assert pos["thin"] is False

    thin = build_relative_position(df.iloc[:3], "tw")
    assert thin["n"] == 2 and thin["thin"] is True


def test_data_quality_summarises_coverage_and_snapshot_range():
    from gold_analysis import data_quality

    df = pd.DataFrame({
        "job_id": ["a", "b"],
        "salary_min": [1.0, None],
        "salary_max": [2.0, None],
        "description_md": ["text", None],
        "source_date": ["20260101", "20260609120000"],
    })
    assert data_quality(df) == (
        "DATA QUALITY: 2 jobs | salary disclosed: 1 (50%) | descriptions: 1 (50%) | "
        "snapshots 2026-01-01 to 2026-06-09"
    )
