# Single-Command Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run the entire job analysis pipeline from a single command: `python run_pipeline.py <job_url>`

**Architecture:** `run_pipeline.py` parses the URL, calls the right scraper, optionally runs wayback for historical data, injects config into notebooks, and executes all 4 notebooks. Each scraper and notebook stays independent — the pipeline is pure orchestration.

**Tech Stack:** Python 3, subprocess, nbformat, jupyter nbconvert

---

### Task 1: Rename scrape_anthropic.py → scrape_greenhouse.py and make it generic

**Files:**
- Rename: `scrape_anthropic.py` → `scrape_greenhouse.py`
- Modify: `scrape_greenhouse.py` — add `--company` CLI arg, remove hardcoded `BOARD = "anthropic"`

**Step 1: Rename the file**

```bash
git mv scrape_anthropic.py scrape_greenhouse.py
```

**Step 2: Make it accept --company**

In `scrape_greenhouse.py`, replace:
```python
BOARD = "anthropic"
BASE_URL = f"https://boards-api.greenhouse.io/v1/boards/{BOARD}/jobs"
```

Remove those two module-level constants. Update `scrape_all_jobs` to accept `company`:
```python
def scrape_all_jobs(company: str) -> List[Dict[str, Any]]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
    log.info("Fetching all jobs from Greenhouse API for %s ...", company)
    resp = requests.get(url, params={"content": "true"}, timeout=30)
    resp.raise_for_status()
    jobs = resp.json().get("jobs", [])
    log.info("Fetched %d jobs", len(jobs))
    return jobs
```

Update `greenhouse_job_url` to accept `company`:
```python
def greenhouse_job_url(company: str, job_id: int) -> str:
    return f"https://job-boards.greenhouse.io/{company}/jobs/{job_id}"
```

Update `main()` argparse:
```python
ap.add_argument("--company", required=True, help="Greenhouse company slug (e.g. anthropic)")
ap.add_argument("--out", default=None)
```
And: `out_path = args.out or f"{args.company}_salaries.csv"`

Update the row loop to pass `args.company` to `greenhouse_job_url`.

**Step 3: Verify**

Run: `python scrape_greenhouse.py --company anthropic --out /tmp/test_gh.csv`
Expected: completes, same output as before

Run: `python -m pytest tests/test_classify.py -v`
Expected: all pass (no test changes needed — tests don't import from scraper)

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: rename scrape_anthropic.py to scrape_greenhouse.py, make company configurable

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Generalize scrape_wayback.py

**Files:**
- Modify: `scrape_wayback.py`

**Step 1: Add CLI args and generalize URL patterns**

Replace the hardcoded constants:
```python
JOB_URL_PATTERNS = [
    "boards.greenhouse.io/anthropic/jobs/*",
    "job-boards.greenhouse.io/anthropic/jobs/*",
]
OUTPUT_CSV = Path("anthropic_salaries_historical.csv")
```

With argparse in `main()`:
```python
ap = argparse.ArgumentParser()
ap.add_argument("--board", required=True, choices=["greenhouse", "ashby"])
ap.add_argument("--company", required=True, help="Company slug")
ap.add_argument("--out", default=None)
args = ap.parse_args()

out_path = Path(args.out or f"{args.company}_salaries_historical.csv")
current_csv = Path(f"{args.company}_salaries.csv")

if args.board == "greenhouse":
    job_url_patterns = [
        f"boards.greenhouse.io/{args.company}/jobs/*",
        f"job-boards.greenhouse.io/{args.company}/jobs/*",
    ]
elif args.board == "ashby":
    job_url_patterns = [
        f"jobs.ashbyhq.com/{args.company}/*",
    ]
```

Add `import argparse` at the top.

Pass `job_url_patterns` to `step1_build_job_index` (change its signature to accept the patterns list instead of using the module-level constant).

Pass `current_csv` to `mark_active_jobs` instead of hardcoded `Path("anthropic_salaries.csv")`.

Pass `out_path` to `write_csv` instead of `OUTPUT_CSV`.

Update `PROGRESS_FILE` to include the company: `Path(f".wayback_progress_{args.company}.json")`

For Ashby, the job ID is a UUID in the URL path (not a numeric ID like Greenhouse). Update the regex in `step1_build_job_index`:
```python
if board == "greenhouse":
    m = re.search(r"/jobs/(\d+)", row["original"])
elif board == "ashby":
    m = re.search(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", row["original"])
```

Pass `board` through to `step1_build_job_index` and `step2_fetch_job_details`.

For Ashby page parsing, add a `parse_ashby_page` function alongside existing `parse_job_page` (Greenhouse). Ashby pages are React SPAs so the Wayback snapshot may have job data in a `__appData` JSON blob or may be empty. Try extracting from script tags first, fall back to HTML parsing:
```python
def parse_ashby_page(html: str) -> dict:
    result = {"title": "", "location": "", "department": "",
              "salary_text": "", "salary_min": None, "salary_max": None,
              "currency": "", "salary_unit": ""}
    soup = BeautifulSoup(html, "html.parser")

    # Try JSON-LD first (structured data, most reliable)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if data.get("@type") == "JobPosting":
                result["title"] = data.get("title", "")
                loc = data.get("jobLocation", {})
                if isinstance(loc, dict):
                    addr = loc.get("address", {})
                    result["location"] = f"{addr.get('addressLocality', '')}, {addr.get('addressRegion', '')}"
                break
        except (json.JSONDecodeError, TypeError):
            continue

    # Fall back to HTML text for salary
    text = soup.get_text(" ", strip=True)
    m = re.search(r"Compensation will be[^.]*\$[^.]+\.", text, re.I)
    if m:
        result["salary_text"] = m.group(0)

    if result["salary_text"]:
        _parse_salary_numbers(result)

    return result
```

In `step2_fetch_job_details`, dispatch to the right parser:
```python
if board == "greenhouse":
    details = parse_job_page(html)
elif board == "ashby":
    details = parse_ashby_page(html)
```

**Step 2: Verify with Anthropic (existing behavior)**

Run: `python scrape_wayback.py --board greenhouse --company anthropic --out /tmp/test_hist.csv`
Expected: produces historical CSV (may take a while if no progress file exists — can Ctrl+C after first few jobs to verify it works)

**Step 3: Commit**

```bash
git add scrape_wayback.py
git commit -m "refactor: generalize wayback scraper for any company/board

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Parameterize the 3 analysis notebooks

**Files:**
- Modify: `analyze_salaries.ipynb` — add CSV_PATH config cell
- Modify: `analyze_nlp.ipynb` — add CSV_PATH config cell
- Modify: `analyze_historical.ipynb` — add CSV_PATH config cell

**Step 1: Update analyze_salaries.ipynb**

The notebook currently has (in the imports/load cell):
```python
df_raw = pd.read_csv("anthropic_salaries.csv", dtype={"job_id": str})
```

Add a config section at the top of that cell:
```python
# ── CONFIG ──────────────────────────────────────────────────────────
CSV_PATH = "anthropic_salaries.csv"
# ────────────────────────────────────────────────────────────────────
```

Replace the read_csv line with:
```python
df_raw = pd.read_csv(CSV_PATH, dtype={"job_id": str})
```

**Step 2: Update analyze_nlp.ipynb**

Same pattern. Currently:
```python
df = pd.read_csv("anthropic_salaries.csv", dtype={"job_id": str})
```

Add config, replace with `pd.read_csv(CSV_PATH, ...)`.

**Step 3: Update analyze_historical.ipynb**

Currently:
```python
hist = pd.read_csv("anthropic_salaries_historical.csv", dtype={"job_id": str})
```

Add config:
```python
CSV_PATH = "anthropic_salaries_historical.csv"
```

Replace with `pd.read_csv(CSV_PATH, ...)`.

Also check if this notebook loads the current salaries CSV anywhere (for comparing active/closed). If so, add a `CURRENT_CSV_PATH` config too.

**Step 4: Verify all notebooks execute**

```bash
jupyter nbconvert --to notebook --execute --ExecutePreprocessor.kernel_name=job-analysis analyze_salaries.ipynb --output /tmp/test_s.ipynb
jupyter nbconvert --to notebook --execute --ExecutePreprocessor.kernel_name=job-analysis analyze_nlp.ipynb --output /tmp/test_n.ipynb
jupyter nbconvert --to notebook --execute --ExecutePreprocessor.kernel_name=job-analysis analyze_historical.ipynb --output /tmp/test_h.ipynb
```

Expected: all succeed (defaults still point to anthropic files)

**Step 5: Commit**

```bash
git add analyze_salaries.ipynb analyze_nlp.ipynb analyze_historical.ipynb
git commit -m "refactor: parameterize CSV paths in analysis notebooks

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Add URL parsing tests

**Files:**
- Create: `tests/test_pipeline.py`

**Step 1: Write failing tests**

```python
"""Tests for run_pipeline URL parsing."""
from run_pipeline import parse_job_url


def test_ashby_url():
    result = parse_job_url("https://jobs.ashbyhq.com/Crusoe/2689707b-7314-4246-ac95-1e6466970ba3")
    assert result == {
        "board": "ashby",
        "company": "crusoe",
        "job_id": "2689707b-7314-4246-ac95-1e6466970ba3",
    }


def test_ashby_url_with_query_params():
    result = parse_job_url(
        "https://jobs.ashbyhq.com/Crusoe/2689707b-7314-4246-ac95-1e6466970ba3?departmentId=abc"
    )
    assert result == {
        "board": "ashby",
        "company": "crusoe",
        "job_id": "2689707b-7314-4246-ac95-1e6466970ba3",
    }


def test_greenhouse_url():
    result = parse_job_url("https://job-boards.greenhouse.io/anthropic/jobs/5080929008")
    assert result == {
        "board": "greenhouse",
        "company": "anthropic",
        "job_id": "5080929008",
    }


def test_invalid_url():
    try:
        parse_job_url("https://linkedin.com/jobs/12345")
        assert False, "Should have raised"
    except ValueError:
        pass
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `run_pipeline` does not exist

**Step 3: Create `run_pipeline.py` with just `parse_job_url`**

```python
#!/usr/bin/env python3
"""
Run the full job analysis pipeline from a single job posting URL.

Usage:
  python run_pipeline.py https://jobs.ashbyhq.com/Crusoe/2689707b-...
"""

from __future__ import annotations

import re
import sys
from urllib.parse import urlparse


def parse_job_url(url: str) -> dict:
    """Parse a job posting URL into board, company, and job_id."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path.strip("/")

    if "ashbyhq.com" in host:
        # jobs.ashbyhq.com/{company}/{job_id}
        parts = path.split("/")
        if len(parts) >= 2:
            return {
                "board": "ashby",
                "company": parts[0].lower(),
                "job_id": parts[1],
            }

    if "greenhouse.io" in host:
        # job-boards.greenhouse.io/{company}/jobs/{job_id}
        m = re.match(r"([^/]+)/jobs/(\d+)", path)
        if m:
            return {
                "board": "greenhouse",
                "company": m.group(1).lower(),
                "job_id": m.group(2),
            }

    raise ValueError(f"Unsupported job board URL: {url}")
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add run_pipeline.py tests/test_pipeline.py
git commit -m "feat: add run_pipeline.py with URL parsing

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Build the pipeline orchestrator

**Files:**
- Modify: `run_pipeline.py` — add `main()` orchestration

**Step 1: Add orchestration logic**

Add to `run_pipeline.py`:

```python
import argparse
import json
import logging
import subprocess
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

KERNEL_NAME = "job-analysis"


def run_scraper(board: str, company: str) -> Path:
    """Run the appropriate scraper. Returns path to output CSV."""
    out_csv = Path(f"{company}_salaries.csv")
    if board == "ashby":
        cmd = [sys.executable, "scrape_ashby.py", "--company", company, "--out", str(out_csv)]
    elif board == "greenhouse":
        cmd = [sys.executable, "scrape_greenhouse.py", "--company", company, "--out", str(out_csv)]
    else:
        raise ValueError(f"Unknown board: {board}")

    log.info("Scraping current jobs: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)
    return out_csv


def run_wayback(board: str, company: str) -> Path | None:
    """Run wayback scraper if historical CSV doesn't exist. Returns path or None."""
    hist_csv = Path(f"{company}_salaries_historical.csv")
    if hist_csv.exists():
        log.info("Historical data exists: %s (skipping wayback)", hist_csv)
        return hist_csv

    log.info("No historical data for %s — running wayback scraper...", company)
    cmd = [sys.executable, "scrape_wayback.py", "--board", board, "--company", company,
           "--out", str(hist_csv)]
    try:
        subprocess.run(cmd, check=True)
        if hist_csv.exists():
            return hist_csv
    except subprocess.CalledProcessError:
        log.warning("Wayback scraper failed — continuing without historical data")
    return None


def inject_notebook_config(notebook_path: str, replacements: dict) -> str:
    """Inject config values into a notebook's first code cell. Returns temp path."""
    nb = json.loads(Path(notebook_path).read_text())

    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            source = cell["source"] if isinstance(cell["source"], str) else "".join(cell["source"])
            for old, new in replacements.items():
                source = source.replace(old, new)
            cell["source"] = source
            break  # only modify first code cell

    tmp_path = f"/tmp/pipeline_{Path(notebook_path).name}"
    Path(tmp_path).write_text(json.dumps(nb, indent=1))
    return tmp_path


def run_notebook(notebook_path: str, output_label: str) -> bool:
    """Execute a notebook. Returns True on success."""
    log.info("Running %s ...", output_label)
    cmd = [
        "jupyter", "nbconvert", "--to", "notebook", "--execute",
        f"--ExecutePreprocessor.kernel_name={KERNEL_NAME}",
        notebook_path,
        "--output", f"/tmp/pipeline_out_{Path(notebook_path).stem}.ipynb",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
        log.info("  ✓ %s complete", output_label)
        return True
    except subprocess.CalledProcessError as e:
        log.error("  ✗ %s failed:\n%s", output_label, e.stderr[-500:] if e.stderr else "")
        return False
    except subprocess.TimeoutExpired:
        log.error("  ✗ %s timed out", output_label)
        return False


def print_summary(csv_path: str, job_id: str):
    """Print a quick text summary of the role gap analysis."""
    import csv as csv_mod
    with open(csv_path) as f:
        rows = list(csv_mod.DictReader(f))
    target = next((r for r in rows if str(r["job_id"]) == job_id), None)
    if not target:
        log.warning("Could not find job %s in %s for summary", job_id, csv_path)
        return

    print("\n" + "=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    print(f"  Target:     {target['title']}")
    print(f"  Company:    {Path(csv_path).stem.replace('_salaries', '')}")
    print(f"  Department: {target.get('department', 'N/A')}")
    print(f"  Salary:     ${float(target['salary_min']):,.0f} – ${float(target['salary_max']):,.0f}")
    print(f"  Location:   {target['location']}")
    print("=" * 60)


def main():
    ap = argparse.ArgumentParser(description="Run the full job analysis pipeline")
    ap.add_argument("url", help="Job posting URL (Ashby or Greenhouse)")
    args = ap.parse_args()

    info = parse_job_url(args.url)
    board, company, job_id = info["board"], info["company"], info["job_id"]
    log.info("Parsed: board=%s company=%s job_id=%s", board, company, job_id)

    # Step 1: Scrape current jobs
    csv_path = run_scraper(board, company)

    # Step 2: Scrape historical (if needed)
    hist_path = run_wayback(board, company)

    # Step 3: Run notebooks
    results = []

    # Salary analysis
    tmp = inject_notebook_config("analyze_salaries.ipynb", {
        'CSV_PATH = "anthropic_salaries.csv"': f'CSV_PATH = "{csv_path}"',
    })
    results.append(("Salary Analysis", run_notebook(tmp, "Salary Analysis")))

    # NLP analysis
    tmp = inject_notebook_config("analyze_nlp.ipynb", {
        'CSV_PATH = "anthropic_salaries.csv"': f'CSV_PATH = "{csv_path}"',
    })
    results.append(("NLP Analysis", run_notebook(tmp, "NLP Analysis")))

    # Historical analysis
    if hist_path:
        tmp = inject_notebook_config("analyze_historical.ipynb", {
            'CSV_PATH = "anthropic_salaries_historical.csv"': f'CSV_PATH = "{hist_path}"',
        })
        results.append(("Historical Analysis", run_notebook(tmp, "Historical Analysis")))
    else:
        log.info("Skipping historical analysis (no data)")

    # Role gap analysis
    tmp = inject_notebook_config("analyze_role_gap.ipynb", {
        f'JOB_ID = "2689707b-7314-4246-ac95-1e6466970ba3"': f'JOB_ID = "{job_id}"',
        'CSV_PATH = "crusoe_salaries.csv"': f'CSV_PATH = "{csv_path}"',
    })
    results.append(("Role Gap Analysis", run_notebook(tmp, "Role Gap Analysis")))

    # Step 4: Summary
    print_summary(str(csv_path), job_id)

    print("\nNotebook Results:")
    for name, ok in results:
        status = "✓" if ok else "✗"
        print(f"  {status} {name}")

    if all(ok for _, ok in results):
        print("\nAll notebooks complete. Open them in Jupyter to view charts.")
    else:
        print("\nSome notebooks failed. Check logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

**Step 2: Verify end-to-end with Crusoe**

Run: `python run_pipeline.py "https://jobs.ashbyhq.com/Crusoe/2689707b-7314-4246-ac95-1e6466970ba3"`
Expected: scrapes Crusoe, runs all notebooks, prints summary

**Step 3: Commit**

```bash
git add run_pipeline.py
git commit -m "feat: add pipeline orchestrator — single command runs full analysis

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Update CLAUDE.md and final verification

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update CLAUDE.md**

Update Key Files section:
- Remove `scrape_anthropic.py` entry
- Add `scrape_greenhouse.py` — Greenhouse job board scraper (was scrape_anthropic.py)
- Add `run_pipeline.py` — Single-command pipeline orchestrator
- Update `scrape_wayback.py` description — now accepts `--board` and `--company`

Add usage section:
```
## Usage
python run_pipeline.py <job_posting_url>

Example:
  python run_pipeline.py https://jobs.ashbyhq.com/Crusoe/2689707b-7314-4246-ac95-1e6466970ba3
```

**Step 2: Run full pipeline end-to-end**

```bash
python run_pipeline.py "https://jobs.ashbyhq.com/Crusoe/2689707b-7314-4246-ac95-1e6466970ba3"
```

**Step 3: Run all tests**

```bash
python -m pytest tests/ -v
```

**Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with pipeline usage

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```
