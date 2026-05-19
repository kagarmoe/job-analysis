# tests/conftest.py
import subprocess
import sys
from pathlib import Path


def pytest_configure(config):
    """Generate classify.py from classify.ipynb before running tests."""
    root = Path(__file__).parent.parent
    nb = root / "classify.ipynb"
    out_dir = root
    if nb.exists():
        result = subprocess.run(
            [sys.executable, "-m", "nbconvert", "--to", "script",
             str(nb), "--output", "classify", "--output-dir", str(out_dir)],
            check=True,
            capture_output=True,
        )
        # nbconvert may write classify.txt when the kernel name is not "python3"
        txt = out_dir / "classify.txt"
        py = out_dir / "classify.py"
        if txt.exists() and not py.exists():
            txt.rename(py)
