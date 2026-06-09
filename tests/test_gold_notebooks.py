import json
from pathlib import Path


def _notebook_source(path: str) -> str:
    notebook = json.loads(Path(path).read_text())
    return "\n\n".join(
        "".join(cell.get("source", [])) if isinstance(cell.get("source"), list) else cell.get("source", "")
        for cell in notebook["cells"]
    )


def test_salary_notebook_uses_shared_location_helper_and_generic_labels():
    source = _notebook_source("analyze_salaries.ipynb")
    assert "from gold_analysis import split_locations" in source
    assert "# Anthropic Salary Analysis" not in source
    assert "Anthropic Salary Dashboard" not in source
    assert "def split_locations" not in source


def test_nlp_notebook_uses_shared_gold_helpers():
    source = _notebook_source("analyze_nlp.ipynb")
    assert "from gold_analysis import SKILL_KEYWORDS, EDU_PATTERNS, extract_required_yoe" in source
    assert "def extract_yoe" not in source
    assert "SKILL_KEYWORDS = {" not in source
    assert "EDU_PATTERNS = {" not in source


def test_role_gap_notebook_uses_shared_scope_and_yoe_helpers():
    source = _notebook_source("analyze_role_gap.ipynb")
    assert (
        "from gold_analysis import extract_required_yoe, score_scope, select_role_gap_comparables"
        in source
    )
    assert "def score_scope" not in source
    assert "BUILDER_PATTERNS" not in source
    assert "def extract_yoe" not in source
