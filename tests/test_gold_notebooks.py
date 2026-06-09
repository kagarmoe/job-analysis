import json
from pathlib import Path


GOLD_NOTEBOOKS = [
    "analyze_salaries.ipynb",
    "analyze_nlp.ipynb",
    "analyze_historical.ipynb",
    "analyze_role_gap.ipynb",
]


def _notebook_source(path: str) -> str:
    notebook = json.loads(Path(path).read_text())
    return "\n\n".join(
        "".join(cell.get("source", [])) if isinstance(cell.get("source"), list) else cell.get("source", "")
        for cell in notebook["cells"]
    )


def test_gold_notebook_code_cells_are_syntactically_valid():
    for path in GOLD_NOTEBOOKS:
        notebook = json.loads(Path(path).read_text())
        for index, cell in enumerate(notebook["cells"]):
            if cell.get("cell_type") != "code":
                continue
            source = cell.get("source", "")
            if isinstance(source, list):
                source = "".join(source)
            compile(source, f"{path}:cell-{index}", "exec")


def test_salary_notebook_uses_shared_location_helper_and_generic_labels():
    source = _notebook_source("analyze_salaries.ipynb")
    assert "from gold_analysis import split_locations" in source
    assert "# Anthropic Salary Analysis" not in source
    assert "Anthropic Salary Dashboard" not in source
    assert "def split_locations" not in source


def test_nlp_notebook_uses_shared_gold_helpers():
    source = _notebook_source("analyze_nlp.ipynb")
    assert (
        "from gold_analysis import build_cluster_profiles, build_department_skill_matrix, build_education_requirement_summary, build_skill_mention_counts, build_tfidf_cluster_projection, build_yoe_dataset, summarize_yoe_by_department"
        in source
    )
    assert "def extract_yoe" not in source
    assert "SKILL_KEYWORDS = {" not in source
    assert "EDU_PATTERNS = {" not in source
    assert "skill_counts = {}" not in source
    assert "for skill, pattern in SKILL_KEYWORDS.items()" not in source
    assert "dept_skill_matrix = pd.DataFrame" not in source
    assert "df_nlp[\"yoe\"] = df_nlp[\"description_md\"].apply(extract_required_yoe)" not in source
    assert "dept_yoe = df_nlp_yoe.groupby(\"department\")[\"yoe\"].agg" not in source
    assert "edu_counts = {}" not in source
    assert "for label, pattern in EDU_PATTERNS.items()" not in source
    assert "edu_dept = pd.DataFrame" not in source
    assert "from sklearn.feature_extraction.text import TfidfVectorizer" not in source
    assert "from sklearn.decomposition import TruncatedSVD" not in source
    assert "from sklearn.cluster import KMeans" not in source
    assert "df_cluster = df_nlp.dropna(subset=[\"description_md\"]).copy()" not in source
    assert "tfidf.fit_transform" not in source
    assert "svd.fit_transform" not in source
    assert "KMeans(n_clusters=" not in source
    assert "km.fit_predict" not in source
    assert "km.cluster_centers_" not in source
    assert "retrying with min_df=1, max_df=1.0" in source
    assert "TF-IDF unavailable after retry" in source
    assert "cluster_result = build_tfidf_cluster_projection(df_nlp)" in source
    assert "cluster_profiles = build_cluster_profiles(cluster_result)" in source


def test_role_gap_notebook_uses_shared_scope_and_yoe_helpers():
    source = _notebook_source("analyze_role_gap.ipynb")
    assert (
        "from gold_analysis import build_skill_overlap_matrix, extract_required_yoe, extract_skill_phrases, score_scope, select_role_gap_comparables"
        in source
    )
    assert "def score_scope" not in source
    assert "BUILDER_PATTERNS" not in source
    assert "def extract_yoe" not in source
    assert "def extract_skill_phrases" not in source


def test_historical_notebook_uses_shared_temporal_helpers():
    source = _notebook_source("analyze_historical.ipynb")
    assert (
        "from gold_analysis import build_active_role_timeseries, build_active_closed_comparison, build_department_quarterly_salary_trends, build_historical_dataset, build_monthly_hiring_activity, build_quarterly_salary_stats, build_time_to_fill_dataset, summarize_recurring_roles"
        in source
    )
    assert "temporal = df.groupby(\"job_id\")" not in source
    assert "for d in date_range:" not in source
    assert "closed = hist[~hist[\"is_active\"]].copy()" not in source
    assert "closed[\"days_open\"] = (closed[\"last_seen\"] - closed[\"first_seen\"]).dt.days" not in source
    assert "dept_status = hist.groupby([\"department\", \"is_active\"])" not in source
    assert "sen_status = hist.groupby([\"seniority\", \"is_active\"])" not in source
    assert "hist_salary[\"status\"] = hist_salary[\"is_active\"].map" not in source
    assert "title_counts = hist_salary.groupby(\"title_norm\")" not in source
    assert "hist_salary.groupby(\"quarter\")[\"mid_usd\"].agg" not in source
    assert "dept_qtr_counts = hist_salary.groupby([\"quarter\", \"department\"])" not in source
    assert "No salary data available - skipping quarterly salary trend charts." in source
    assert "if qtr_stats.empty:" in source


def test_role_gap_notebook_handles_missing_salary_data():
    source = _notebook_source("analyze_role_gap.ipynb")
    assert "if df.empty:" in source
    assert "No salaried roles available for comparable salary analysis." in source
    assert "No salary ranges available for salary comparison chart." in source
    assert "No salary data available - skipping scope vs salary scatter." in source
