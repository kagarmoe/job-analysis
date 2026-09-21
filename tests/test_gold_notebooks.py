import json
from pathlib import Path


GOLD_NOTEBOOKS = [
    "analyze_salaries.ipynb",
    "analyze_nlp.ipynb",
    "analyze_historical.ipynb",
    "analyze_role_gap.ipynb",
    "analyze_cross_company.ipynb",
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
    assert ".apply(split_locations)" in source
    assert "Anthropic" not in source


def test_notebooks_call_shared_helpers_instead_of_inlining_them():
    # Logic lives in gold_analysis.py (tested there); notebooks must call it, not redefine it.
    assert "build_relative_position(df, JOB_ID)" in _notebook_source("analyze_role_gap.ipynb")
    assert "build_tfidf_cluster_projection(df_nlp)" in _notebook_source("analyze_nlp.ipynb")
    assert "build_historical_dataset(df)" in _notebook_source("analyze_historical.ipynb")
    for path in GOLD_NOTEBOOKS:
        assert "def build_" not in _notebook_source(path), path
    assert "scope" not in _notebook_source("analyze_role_gap.ipynb").lower()


def test_role_gap_notebook_handles_missing_salary_data():
    source = _notebook_source("analyze_role_gap.ipynb")
    assert "if df.empty:" in source
    assert "No salaried roles available for comparable salary analysis." in source
    assert "No salary ranges available for salary comparison chart." in source


def test_role_gap_notebook_does_not_overwrite_usd_with_native_currency():
    source = _notebook_source("analyze_role_gap.ipynb")
    assert 'df["mid_usd"] = (df["salary_min"]' not in source
    assert 'left=row["salary_min"]' not in source


def test_every_notebook_prints_data_quality_and_salary_charts_carry_coverage():
    for path in GOLD_NOTEBOOKS:
        source = _notebook_source(path)
        assert "data_quality(" in source, path
        bare = [ln for ln in source.splitlines()
                if "set_title(" in ln and "Salary" in ln and "COVERAGE_SUFFIX" not in ln]
        assert bare == [], (path, bare)


def test_snapshot_level_notebooks_dedupe_to_latest_per_job():
    for path in ["analyze_salaries.ipynb", "analyze_nlp.ipynb", "analyze_role_gap.ipynb"]:
        assert "latest_per_job(" in _notebook_source(path), path
