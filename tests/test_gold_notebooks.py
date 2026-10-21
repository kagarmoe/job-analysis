# Source checks for what executing the notebooks can't see (execution is tested in
# test_gold_contract.py): a wrong number or an unlabeled chart doesn't raise.
import json
from pathlib import Path

NOTEBOOK_DIR = Path(__file__).resolve().parent.parent / "notebooks"


def _notebook_source(path: str) -> str:
    notebook = json.loads((NOTEBOOK_DIR / path).read_text())
    return "\n\n".join(
        "".join(cell.get("source", [])) if isinstance(cell.get("source"), list) else cell.get("source", "")
        for cell in notebook["cells"]
    )


def test_salary_chart_titles_carry_coverage_suffix():
    for path in sorted(p.name for p in NOTEBOOK_DIR.glob("analyze_*.ipynb")):
        bare = [ln for ln in _notebook_source(path).splitlines()
                if "set_title(" in ln and "Salary" in ln and "COVERAGE_SUFFIX" not in ln]
        assert bare == [], (path, bare)


def test_role_gap_notebook_does_not_overwrite_usd_with_native_currency():
    # Regression: the notebook once recomputed mid_usd from native-currency salary_min/max.
    source = _notebook_source("analyze_role_gap.ipynb")
    assert 'df["mid_usd"] = (df["salary_min"]' not in source
    assert 'left=row["salary_min"]' not in source
