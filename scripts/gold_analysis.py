from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Final

import numpy as np
import pandas as pd
from classify import add_usd_salary
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

SKILL_KEYWORDS: Final[dict[str, str]] = {
    "Python": r"\bPython\b",
    "Java": r"\bJava\b(?!Script)",
    "JavaScript": r"\bJavaScript\b",
    "TypeScript": r"\bTypeScript\b",
    "Go": r"\bGo(?:lang)?\b",
    "Rust": r"\bRust\b",
    "C/C++": r"\bC\+\+\b|\bC programming\b",
    "SQL": r"\bSQL\b",
    "R": r"\bR\b(?= programming| language| (?:and|or) )",
    "Scala": r"\bScala\b",
    "Kotlin": r"\bKotlin\b",
    "Ruby": r"\bRuby\b",
    "PyTorch": r"\bPyTorch\b",
    "TensorFlow": r"\bTensorFlow\b",
    "JAX": r"\bJAX\b",
    "LLMs": r"\bLLM[s]?\b|large language model",
    "NLP": r"\bNLP\b|natural language processing",
    "Deep Learning": r"\bdeep learning\b",
    "Machine Learning": r"\bmachine learning\b",
    "Transformers": r"\btransformer[s]?\b",
    "RLHF": r"\bRLHF\b",
    "Fine-tuning": r"\bfine[- ]?tun",
    "RAG": r"\bRAG\b",
    "AWS": r"\bAWS\b",
    "GCP": r"\bGCP\b|Google Cloud",
    "Azure": r"\bAzure\b",
    "Kubernetes": r"\bKubernetes\b|\bk8s\b",
    "Docker": r"\bDocker\b",
    "Terraform": r"\bTerraform\b",
    "Linux": r"\bLinux\b",
    "Spark": r"\bSpark\b",
    "Snowflake": r"\bSnowflake\b",
    "dbt": r"\bdbt\b",
    "Postgres": r"\bPostgres\b|\bPostgreSQL\b",
    "Redis": r"\bRedis\b",
    "Git": r"\bGit\b(?!Hub)",
    "CI/CD": r"\bCI/?CD\b",
    "Agile": r"\bAgile\b|\bScrum\b",
    "React": r"\bReact\b",
    "Node.js": r"\bNode\.?js\b",
    "APIs": r"\bAPI[s]?\b",
    "GraphQL": r"\bGraphQL\b",
    "REST": r"\bREST\b(?:ful)?",
    "Cross-functional": r"\bcross[- ]?functional\b",
    "Stakeholder mgmt": r"\bstakeholder\b",
    "AI Safety": r"\bAI safety\b|\bsafety research\b",
}

EDU_PATTERNS: Final[dict[str, str]] = {
    "PhD / Doctorate": r"\bPh\.?D\b|\bdoctora[lt]e?\b",
    "Master's": r"\bMaster'?s?\b|\bM\.?S\.?\b(?= in| degree)|\bMBA\b",
    "Bachelor's": r"\bBachelor'?s?\b|\bB\.?S\.?\b(?= in| degree)|\bB\.?A\.?\b(?= in| degree)|\bundergraduate degree\b",
    "CS / CompSci": r"\bcomputer science\b|\bCS\b(?= degree| or)",
    "Math / Statistics": r"\bmathematics\b|\bstatistics\b|\bmath\b(?= or| degree)",
    "Physics": r"\bphysics\b",
    "JD / Law": r"\bJ\.?D\.?\b|\blaw degree\b|\bbar\b(?= admission| exam)",
}

BUILDER_PATTERNS: Final[tuple[str, ...]] = (
    r"from scratch",
    r"ground up",
    r"greenfield",
    r"first hire",
    r"founding",
    r"build out",
    r"build\b.*from",
)
OWNER_PATTERNS: Final[tuple[str, ...]] = (
    r"\bown\b",
    r"define the strategy",
    r"set the vision",
    r"\broadmap\b",
    r"lead the\b",
    r"shape the",
)
LEADER_PATTERNS: Final[tuple[str, ...]] = (
    r"hire and manage",
    r"build a team",
    r"cross-functional leadership",
    r"manage a team",
    r"grow the team",
)
CONTRIBUTOR_PATTERNS: Final[tuple[str, ...]] = (
    r"contribute to",
    r"\bassist\b",
    r"join a team",
    r"report to",
    r"work under",
    r"support the team",
)

_YOE_RE = re.compile(
    r"(\d{1,2})\s*(?:\+|or more)?\s*(?:[-\u2013]\s*(\d{1,2})\s*)?(?:\+)?\s*years?\b"
    r"(?:\s+of\s+(?:relevant\s+|professional\s+|industry\s+|hands[- ]on\s+)?"
    r"(?:experience|work))?",
    re.I,
)


@dataclass
class TfidfClusterResult:
    """Container for TF-IDF projection and clustering outputs."""

    df_cluster: pd.DataFrame
    tfidf: TfidfVectorizer | None = None
    tfidf_matrix: Any | None = None
    svd: TruncatedSVD | None = None
    km: KMeans | None = None
    svd_explained_variance_pct: float | None = None
    skipped_reason: str | None = None
    initial_error: str | None = None
    retry_error: str | None = None


@dataclass
class DescriptionLengthAnalysis:
    """Container for description length metrics and salary relationships."""

    df: pd.DataFrame
    df_len_sal: pd.DataFrame
    department_median_words: pd.Series
    correlations: pd.DataFrame | None = None
    word_salary_trend: tuple[float, float] | None = None


def split_locations(location: object) -> list[str]:
    """Split multi-location strings on common delimiters for city-level analysis."""
    if location is None or pd.isna(location):
        return ["Unknown"]
    parts = [part.strip() for part in re.split(r"[|;]", str(location)) if part.strip()]
    return parts or ["Unknown"]


def extract_required_yoe(text: object) -> int | None:
    """Return the highest minimum years-of-experience requirement found in text."""
    if text is None or pd.isna(text):
        return None
    matches = _YOE_RE.findall(str(text))
    if not matches:
        return None
    minimums = [int(match[0]) for match in matches if match[0] and 1 <= int(match[0]) <= 25]
    return max(minimums) if minimums else None


def build_skill_mention_counts(
    df: pd.DataFrame,
    *,
    skill_patterns: dict[str, str] = SKILL_KEYWORDS,
    text_col: str = "description_md",
) -> pd.Series:
    """Count roles whose descriptions mention each skill pattern."""
    counts = {}
    descriptions = df[text_col] if text_col in df.columns else pd.Series(dtype=object)
    for skill, pattern in skill_patterns.items():
        count = int(descriptions.str.contains(pattern, flags=re.I, na=False).sum())
        if count > 0:
            counts[skill] = count
    return pd.Series(counts, dtype=int).sort_index().sort_values(
        ascending=False, kind="stable"
    )


def build_department_skill_matrix(
    df: pd.DataFrame,
    skills: list[str],
    *,
    skill_patterns: dict[str, str] = SKILL_KEYWORDS,
    text_col: str = "description_md",
    department_col: str = "department",
    exclude_department: str = "Other",
) -> pd.DataFrame:
    """Build department x skill percentages for descriptions mentioning each skill."""
    if not skills or text_col not in df.columns or department_col not in df.columns:
        return pd.DataFrame()

    df_with_desc = df.dropna(subset=[text_col])
    if df_with_desc.empty:
        return pd.DataFrame()

    departments = [
        department
        for department in df[department_col].value_counts().index
        if department != exclude_department
    ]
    matrix = pd.DataFrame(index=departments, columns=skills, dtype=float)
    for department in departments:
        dept_descs = df.loc[df[department_col] == department, text_col]
        n_dept = len(dept_descs)
        for skill in skills:
            pattern = skill_patterns[skill]
            count = dept_descs.str.contains(pattern, flags=re.I, na=False).sum()
            matrix.loc[department, skill] = count / n_dept * 100 if n_dept > 0 else 0
    return matrix


def build_yoe_dataset(df: pd.DataFrame, *, text_col: str = "description_md") -> pd.DataFrame:
    """Return a copy of jobs with parsed years-of-experience requirements."""
    yoe_df = df.copy()
    descriptions = (
        yoe_df[text_col]
        if text_col in yoe_df.columns
        else pd.Series(index=yoe_df.index, dtype=object)
    )
    yoe_df["yoe"] = descriptions.apply(extract_required_yoe)
    return yoe_df


def summarize_yoe_by_department(
    df_yoe: pd.DataFrame,
    *,
    min_count: int = 3,
    department_col: str = "department",
) -> pd.DataFrame:
    """Summarize parseable YoE requirements by department."""
    if df_yoe.empty or "yoe" not in df_yoe.columns or department_col not in df_yoe.columns:
        return pd.DataFrame(columns=["median", "mean", "count"])

    dept_yoe = df_yoe.groupby(department_col)["yoe"].agg(["median", "mean", "count"])
    return dept_yoe[dept_yoe["count"] >= min_count].sort_values("median", ascending=False)


def build_education_requirement_summary(
    df: pd.DataFrame,
    *,
    education_patterns: dict[str, str] = EDU_PATTERNS,
    text_col: str = "description_md",
    department_col: str = "department",
    exclude_department: str = "Other",
) -> tuple[pd.Series, pd.DataFrame]:
    """Build overall and department-level education requirement mention summaries."""
    descriptions = df[text_col] if text_col in df.columns else pd.Series(dtype=object)
    counts = {
        label: int(descriptions.str.contains(pattern, flags=re.I, na=False).sum())
        for label, pattern in education_patterns.items()
    }
    edu_series = pd.Series(counts, dtype=int).sort_index().sort_values(
        ascending=False, kind="stable"
    )

    if department_col not in df.columns or text_col not in df.columns:
        return edu_series, pd.DataFrame(columns=edu_series.index)

    departments = [
        department
        for department in df[department_col].value_counts().index
        if department != exclude_department
    ]
    edu_dept = pd.DataFrame(index=departments, columns=edu_series.index, dtype=float)
    for department in departments:
        dept_descs = df.loc[df[department_col] == department, text_col]
        for label in edu_series.index:
            pattern = education_patterns[label]
            count = dept_descs.str.contains(pattern, flags=re.I, na=False).sum()
            edu_dept.loc[department, label] = count / len(dept_descs) * 100 if len(dept_descs) > 0 else 0
    return edu_series, edu_dept


def build_tfidf_cluster_projection(
    df: pd.DataFrame,
    *,
    text_col: str = "description_md",
    min_documents: int = 10,
    max_features: int = 3000,
    max_df: float = 0.85,
    max_clusters: int = 8,
    random_state: int = 42,
) -> TfidfClusterResult:
    """Build TF-IDF features, 2D SVD coordinates, and KMeans cluster labels."""
    if text_col not in df.columns:
        df_cluster = df.iloc[0:0].copy()
    else:
        df_cluster = df.dropna(subset=[text_col]).copy()

    if len(df_cluster) < min_documents:
        return TfidfClusterResult(
            df_cluster=df_cluster,
            skipped_reason=(
                f"Not enough job descriptions for clustering "
                f"({len(df_cluster)} available, need {min_documents}+). Skipping."
            ),
        )

    n_docs = len(df_cluster)
    min_df = max(2, n_docs // 20)
    tfidf = TfidfVectorizer(
        max_features=max_features,
        stop_words="english",
        min_df=min_df,
        max_df=max_df,
        ngram_range=(1, 2),
    )

    initial_error = None
    try:
        tfidf_matrix = tfidf.fit_transform(df_cluster[text_col])
    except ValueError as e:
        initial_error = str(e)
        tfidf.set_params(min_df=1, max_df=1.0)
        try:
            tfidf_matrix = tfidf.fit_transform(df_cluster[text_col])
        except ValueError as e2:
            retry_error = str(e2)
            return TfidfClusterResult(
                df_cluster=df_cluster,
                skipped_reason=f"TF-IDF unavailable after retry ({retry_error}). Skipping clustering.",
                initial_error=initial_error,
                retry_error=retry_error,
            )

    n_components = min(2, tfidf_matrix.shape[1])
    svd = TruncatedSVD(n_components=n_components, random_state=random_state)
    coords = svd.fit_transform(tfidf_matrix)
    df_cluster["x"] = coords[:, 0]
    df_cluster["y"] = coords[:, 1] if coords.shape[1] > 1 else 0.0

    n_clusters = min(max_clusters, len(df_cluster))
    km = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
    df_cluster["cluster"] = km.fit_predict(tfidf_matrix)

    return TfidfClusterResult(
        df_cluster=df_cluster,
        tfidf=tfidf,
        tfidf_matrix=tfidf_matrix,
        svd=svd,
        km=km,
        svd_explained_variance_pct=float(svd.explained_variance_ratio_.sum() * 100),
        initial_error=initial_error,
    )


def build_cluster_profiles(
    result: TfidfClusterResult,
    *,
    top_terms: int = 8,
    top_departments: int = 3,
    department_col: str = "department",
    salary_col: str = "mid_usd",
) -> pd.DataFrame:
    """Summarize each TF-IDF cluster with terms, department mix, and median salary."""
    columns = ["cluster", "role_count", "top_terms", "top_departments", "median_salary"]
    if result.tfidf is None or result.km is None or "cluster" not in result.df_cluster.columns:
        return pd.DataFrame(columns=columns)

    feature_names = result.tfidf.get_feature_names_out()
    order = result.km.cluster_centers_.argsort()[:, ::-1]
    rows = []
    for cluster in range(result.km.n_clusters):
        cluster_rows = result.df_cluster[result.df_cluster["cluster"] == cluster]
        top_term_values = [feature_names[i] for i in order[cluster, :top_terms]]
        if department_col in cluster_rows.columns:
            top_dept = cluster_rows[department_col].value_counts().head(top_departments)
            department_summary = ", ".join(
                f"{department} ({count})" for department, count in top_dept.items()
            )
        else:
            department_summary = ""
        median_salary = (
            cluster_rows[salary_col].median()
            if salary_col in cluster_rows.columns
            else pd.NA
        )
        rows.append(
            {
                "cluster": cluster,
                "role_count": int(len(cluster_rows)),
                "top_terms": top_term_values,
                "top_departments": department_summary,
                "median_salary": median_salary,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def build_description_length_analysis(
    df: pd.DataFrame,
    *,
    text_col: str = "description_md",
    department_col: str = "department",
    salary_col: str = "mid_usd",
    top_departments: int = 10,
    min_salary_rows: int = 3,
) -> DescriptionLengthAnalysis:
    """Derive description length metrics and salary relationship summaries."""
    desc_df = df.copy()
    descriptions = (
        desc_df[text_col]
        if text_col in desc_df.columns
        else pd.Series(index=desc_df.index, dtype=object)
    )
    desc_df["desc_len"] = descriptions.str.len()
    desc_df["desc_words"] = descriptions.str.split().str.len()
    desc_df["n_bullets"] = descriptions.str.count(r"^\s*[\*\-]\s", flags=re.MULTILINE)

    subset_cols = [salary_col, "desc_words"]
    df_len_sal = (
        desc_df.dropna(subset=subset_cols).copy()
        if all(column in desc_df.columns for column in subset_cols)
        else desc_df.iloc[0:0].copy()
    )

    if department_col in desc_df.columns:
        department_median_words = (
            desc_df.groupby(department_col)["desc_words"].median().sort_values(ascending=True)
        )
        top_department_index = desc_df[department_col].value_counts().head(top_departments).index
        department_median_words = department_median_words[
            department_median_words.index.isin(top_department_index)
        ]
    else:
        department_median_words = pd.Series(dtype=float)

    correlations = None
    trend = None
    if len(df_len_sal) >= min_salary_rows:
        correlations = df_len_sal[["desc_words", "n_bullets", salary_col]].corr()
        slope, intercept = np.polyfit(df_len_sal["desc_words"], df_len_sal[salary_col], 1)
        trend = (float(slope), float(intercept))

    return DescriptionLengthAnalysis(
        df=desc_df,
        df_len_sal=df_len_sal,
        department_median_words=department_median_words,
        correlations=correlations,
        word_salary_trend=trend,
    )


def score_scope(description: object) -> int:
    """Score role ownership/scope from 0-10 using heuristic language cues."""
    if not isinstance(description, str):
        return 5

    text = description.lower()
    score = 5
    for pattern in BUILDER_PATTERNS:
        if re.search(pattern, text):
            score += 2
    for pattern in OWNER_PATTERNS:
        if re.search(pattern, text):
            score += 2
    for pattern in LEADER_PATTERNS:
        if re.search(pattern, text):
            score += 1
    for pattern in CONTRIBUTOR_PATTERNS:
        if re.search(pattern, text):
            score -= 1
    return max(0, min(10, score))


def select_role_gap_comparables(
    df: pd.DataFrame,
    *,
    target_department: str,
    target_scope: int,
    target_job_id: str,
    minimum_count: int = 5,
) -> tuple[pd.DataFrame, int, str]:
    """Select comparable salaried roles, relaxing filters when needed."""
    job_id_series = df["job_id"].astype(str)

    def _filter(scope_tolerance: int, same_department: bool) -> pd.DataFrame:
        mask = (
            (df["scope_score"] >= target_scope - scope_tolerance)
            & (df["scope_score"] <= target_scope + scope_tolerance)
            & (job_id_series != str(target_job_id))
        )
        if same_department:
            mask &= df["department"] == target_department
        return df.loc[mask].copy()

    comparables = _filter(scope_tolerance=2, same_department=True)
    if len(comparables) >= minimum_count:
        return comparables, 2, "same_department_scope_2"

    comparables = _filter(scope_tolerance=3, same_department=True)
    if len(comparables) >= minimum_count:
        return comparables, 3, "same_department_scope_3"

    comparables = _filter(scope_tolerance=3, same_department=False)
    return comparables, 3, "cross_department_scope_3"


def latest_per_job(df: pd.DataFrame) -> pd.DataFrame:
    """One row per job: its newest snapshot.

    Silver is keyed on (company, board, job_id, source_date), so a raw load has one row per
    snapshot and over-weights long-lived roles. source_date is YYYYMMDD or a 14-digit Wayback
    timestamp; both sort correctly as strings.
    """
    order = df["source_date"].astype(str).argsort(kind="stable")
    return df.iloc[order].drop_duplicates(subset="job_id", keep="last").reset_index(drop=True)


def build_relative_position(df: pd.DataFrame, job_id: str, *, min_n: int = 5) -> dict[str, Any]:
    """Place one salaried role against same-seniority peers at the same company.

    `df` is one company's salaried, latest-snapshot frame with `mid_usd`. Peers are the
    same seniority band only: the scope score has no correlation with pay (rho=-0.10 on
    562 Anthropic roles) and department matching leaves n<3 for technical writers.
    Pools under `min_n` are returned but flagged `thin` rather than widened.
    """
    job_id_series = df["job_id"].astype(str)
    target = df.loc[job_id_series == str(job_id)].iloc[0]
    peers = df.loc[(df["seniority"] == target["seniority"]) & (job_id_series != str(job_id)), "mid_usd"].dropna()
    n = len(peers)
    median = float(peers.median()) if n else float("nan")
    q1, q3 = (float(peers.quantile(0.25)), float(peers.quantile(0.75))) if n else (float("nan"),) * 2
    return {
        "title": target["title"],
        "location": target["location"],
        "seniority": target["seniority"],
        "target_mid": float(target["mid_usd"]),
        "n": n,
        "comp_median": median,
        "q1": q1,
        "q3": q3,
        "gap_pct": (target["mid_usd"] - median) / median * 100 if n else float("nan"),
        "percentile": float((peers < target["mid_usd"]).mean() * 100) if n else float("nan"),
        "thin": n < min_n,
    }


def coverage_label(df_all: pd.DataFrame, df_salary: pd.DataFrame) -> str:
    """Chart-title suffix so no salary statistic is read without its n and disclosure rate.

    Disclosure follows pay-transparency law by location, so a "median salary" is really the
    median of the roles posted where disclosure is required.
    """
    total, salaried = len(df_all), len(df_salary)
    pct = f" ({salaried / total:.0%})" if total else ""
    return f"n={salaried} of {total} jobs{pct} disclose salary"


def data_quality(df: pd.DataFrame) -> str:
    """One-line header for a notebook's loaded frame; stops charts being read at n=7 unnoticed."""
    n = len(df)
    salaried = int(df[["salary_min", "salary_max"]].notna().all(axis=1).sum()) if n else 0
    described = int(df["description_md"].notna().sum()) if n else 0
    pct = lambda k: f" ({k / n:.0%})" if n else ""  # noqa: E731
    dates = df["source_date"].astype(str).str[:8]
    span = f"{dates.min()[:4]}-{dates.min()[4:6]}-{dates.min()[6:]} to {dates.max()[:4]}-{dates.max()[4:6]}-{dates.max()[6:]}" if n else "none"
    return (
        f"DATA QUALITY: {n} jobs | salary disclosed: {salaried}{pct(salaried)} | "
        f"descriptions: {described}{pct(described)} | snapshots {span}"
    )


def build_historical_dataset(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build one row per job with first/last seen timestamps and active status."""
    hist = df.copy()
    hist["job_id"] = hist["job_id"].astype(str)
    hist["source_dt"] = pd.to_datetime(hist["source_date"].astype(str).str[:8], format="%Y%m%d")

    temporal = (
        hist.groupby("job_id")["source_dt"]
        .agg(first_seen="min", last_seen="max")
        .reset_index()
    )
    latest_date = hist["source_dt"].max()
    temporal["is_active"] = temporal["last_seen"] == latest_date

    hist = latest_per_job(hist).merge(temporal, on="job_id")
    hist["month_posted"] = hist["first_seen"].dt.to_period("M")
    add_usd_salary(hist)
    hist_salary = hist.dropna(subset=["salary_min", "salary_max"]).copy()
    return hist, hist_salary


def build_quarterly_salary_stats(hist_salary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add salary quarters and summarize salary midpoint stats by quarter."""
    salary = hist_salary.copy()
    qtr_stats_columns = ["median", "mean", "count", "std"]
    if salary.empty:
        return salary, pd.DataFrame(columns=qtr_stats_columns)

    salary["quarter"] = pd.to_datetime(salary["first_seen"]).dt.to_period("Q")
    qtr_stats = salary.groupby("quarter")["mid_usd"].agg(qtr_stats_columns)
    qtr_stats.index = qtr_stats.index.to_timestamp()
    qtr_stats = qtr_stats.apply(pd.to_numeric, errors="coerce")
    return salary, qtr_stats


def build_department_quarterly_salary_trends(
    hist_salary: pd.DataFrame,
    *,
    min_roles_per_quarter: int = 3,
    min_quarters: int = 2,
) -> pd.DataFrame:
    """Return quarterly median salaries for departments with enough observations."""
    if hist_salary.empty:
        return pd.DataFrame()

    salary = hist_salary.copy()
    if "quarter" not in salary.columns:
        salary["quarter"] = pd.to_datetime(salary["first_seen"]).dt.to_period("Q")

    dept_qtr_counts = salary.groupby(["quarter", "department"]).size().unstack(fill_value=0)
    departments = [
        department
        for department in dept_qtr_counts.columns
        if department != "Other"
        and (dept_qtr_counts[department] >= min_roles_per_quarter).sum() >= min_quarters
    ]
    if not departments:
        return pd.DataFrame()

    dept_qtr = (
        salary[salary["department"].isin(departments)]
        .groupby(["quarter", "department"])["mid_usd"]
        .median()
        .unstack()
    )
    dept_qtr.index = dept_qtr.index.to_timestamp()
    return dept_qtr


def build_active_role_timeseries(hist: pd.DataFrame, freq: str = "W") -> pd.DataFrame:
    """Count how many roles were active at each point in a date range."""
    if hist.empty:
        return pd.DataFrame(columns=["date", "active_roles"])

    date_range = pd.date_range(hist["first_seen"].min(), hist["last_seen"].max(), freq=freq)
    rows = []
    for date in date_range:
        active_roles = ((hist["first_seen"] <= date) & (hist["last_seen"] >= date)).sum()
        rows.append({"date": date, "active_roles": int(active_roles)})
    return pd.DataFrame(rows)


def build_monthly_hiring_activity(hist: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Count monthly new postings and monthly closings."""
    monthly_hist = hist.copy()
    monthly_hist["month_posted"] = monthly_hist["first_seen"].dt.to_period("M")
    monthly_new = monthly_hist.groupby("month_posted").size()

    closed = monthly_hist[~monthly_hist["is_active"]].copy()
    closed["month_closed"] = closed["last_seen"].dt.to_period("M")
    monthly_closed = closed.groupby("month_closed").size()
    return monthly_new, monthly_closed


def build_time_to_fill_dataset(hist: pd.DataFrame) -> pd.DataFrame:
    """Return closed roles with a positive open duration."""
    closed = hist[~hist["is_active"]].copy()
    closed["days_open"] = (closed["last_seen"] - closed["first_seen"]).dt.days
    return closed[closed["days_open"] > 0].copy()


def _status_counts(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    status_counts = df.groupby([group_col, "is_active"]).size().unstack(fill_value=0)
    status_counts = status_counts.rename(columns={False: "Closed", True: "Active"})
    for status in ["Closed", "Active"]:
        if status not in status_counts.columns:
            status_counts[status] = 0
    return status_counts[["Closed", "Active"]]


def build_active_closed_comparison(
    hist: pd.DataFrame,
    hist_salary: pd.DataFrame,
    seniority_order: list[str],
) -> dict[str, pd.DataFrame]:
    """Build salary, department, and seniority summaries by active/closed status."""
    hist_salary_status = hist_salary.copy()
    hist_salary_status["status"] = hist_salary_status["is_active"].map(
        {True: "Active", False: "Closed"}
    )

    dept_counts = _status_counts(hist, "department")
    dept_pct = dept_counts.div(dept_counts.sum(axis=0).replace(0, pd.NA), axis=1)
    dept_pct = (dept_pct * 100).fillna(0).sort_values("Active", ascending=True)

    seniority_counts = _status_counts(hist, "seniority")
    seniority_existing = [s for s in seniority_order if s in seniority_counts.index]
    seniority_counts = seniority_counts.reindex(seniority_existing)

    salary_summary = (
        hist_salary_status.groupby("status")["mid_usd"]
        .agg(count="count", median="median", mean="mean")
        .reindex(["Active", "Closed"])
    )
    salary_summary["count"] = salary_summary["count"].fillna(0).astype(int)

    return {
        "hist_salary": hist_salary_status,
        "dept_pct": dept_pct,
        "seniority_counts": seniority_counts,
        "salary_summary": salary_summary,
    }


def summarize_recurring_roles(
    hist_salary: pd.DataFrame,
    *,
    min_postings: int = 2,
) -> pd.DataFrame:
    """Summarize salary changes for normalized titles posted multiple times."""
    recurring = hist_salary.copy()
    recurring["title_norm"] = recurring["title"].str.strip().str.lower()
    recurring = recurring.sort_values(["title_norm", "first_seen"])

    summary = (
        recurring.groupby("title_norm")
        .agg(
            postings=("job_id", "nunique"),
            min_date=("first_seen", "min"),
            max_date=("first_seen", "max"),
            earliest_mid=("mid_usd", "first"),
            latest_mid=("mid_usd", "last"),
            display_title=("title", "first"),
        )
        .query("postings >= @min_postings")
        .copy()
    )
    summary["salary_change_pct"] = (
        (summary["latest_mid"] - summary["earliest_mid"]) / summary["earliest_mid"] * 100
    )
    return summary.sort_values("postings", ascending=False)


_SKILL_PHRASE_STOPWORDS: Final[set[str]] = {
    "the", "and", "for", "with", "that", "this", "you", "will",
    "our", "are", "from", "have", "your", "about", "been", "more",
    "their", "into", "also", "who", "can", "all", "has", "than",
    "its", "may", "other", "new", "not", "but", "what", "which",
    "when", "how", "each", "some", "such", "both", "between",
    "should", "would", "could", "across", "within", "including",
    "through", "well", "these", "those", "ability", "experience",
    "work", "working", "team", "role", "join", "looking", "ideal",
    "candidate", "strong", "years", "minimum", "preferred", "plus",
}


def extract_skill_phrases(
    description: object,
    *,
    top_n: int = 12,
    min_count: int = 2,
) -> dict[str, int]:
    """Extract repeated bigram phrases from a description as skill signals."""
    if not isinstance(description, str):
        return {}

    text = re.sub(r"[^a-z\s-]", " ", description.lower())
    words = [word for word in text.split() if word not in _SKILL_PHRASE_STOPWORDS and len(word) > 2]
    bigrams = [f"{words[i]} {words[i + 1]}" for i in range(len(words) - 1)]
    counts = pd.Series(bigrams).value_counts()
    counts = counts[counts >= min_count]
    if counts.empty:
        return {}
    return counts.head(top_n).astype(int).to_dict()


def build_skill_overlap_matrix(
    roles: pd.DataFrame,
    skill_phrases: dict[str, int],
    *,
    max_roles: int = 20,
) -> pd.DataFrame:
    """Build a role x phrase count matrix for role-gap skills overlap."""
    if roles.empty or not skill_phrases:
        return pd.DataFrame()

    trimmed = roles.drop_duplicates(subset="job_id").head(max_roles)
    scores: dict[str, dict[str, int]] = {}
    for _, row in trimmed.iterrows():
        desc = str(row.get("description_md", "")).lower()
        role_scores = {
            phrase: len(re.findall(re.escape(phrase), desc))
            for phrase in skill_phrases
        }
        scores[str(row["title"])[:45]] = role_scores

    overlap = pd.DataFrame(scores).T
    return overlap.loc[:, overlap.sum() > 0]
