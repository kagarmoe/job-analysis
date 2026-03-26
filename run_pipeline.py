#!/usr/bin/env python3
"""
Run the full job analysis pipeline from a single job posting URL.

Usage:
  python run_pipeline.py https://jobs.ashbyhq.com/Crusoe/2689707b-...
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
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
    """Run wayback scraper if historical CSV doesn't exist for this company."""
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
    """Print a quick text summary."""
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

    # Step 2: Scrape historical (if needed for this company)
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
        'JOB_ID = "2689707b-7314-4246-ac95-1e6466970ba3"': f'JOB_ID = "{job_id}"',
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
