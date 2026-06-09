from __future__ import annotations

import re
from typing import Final

import pandas as pd

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

