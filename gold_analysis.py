from __future__ import annotations

import re
from typing import Final

import pandas as pd
from classify import add_usd_salary

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

    hist = hist.drop_duplicates(subset="job_id").merge(temporal, on="job_id")
    add_usd_salary(hist)
    hist_salary = hist.dropna(subset=["salary_min", "salary_max"]).copy()
    return hist, hist_salary


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
