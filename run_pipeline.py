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

    # Unknown board — route to adhoc
    parts = path.strip("/").split("/")
    job_id = parts[-1] if parts else path.replace("/", "-")
    company = (parsed.hostname or "").split(".")[0]
    return {"board": "adhoc", "company": company, "job_id": job_id}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

KERNEL_NAME = "job-analysis"


def scrape_adhoc(url: str, company: str, job_id: str) -> None:
    """Fetch a single job page from an unknown board and store to copper/adhoc."""
    import copper as _copper, requests
    from datetime import date
    db = _copper.open_db("adhoc")
    source_date = date.today().strftime("%Y%m%d")
    log.info("Fetching adhoc job: %s", url)
    resp = requests.get(url, timeout=30, headers={"User-Agent": "JobBoardResearch/1.0"})
    resp.raise_for_status()
    _copper.store(db, url=url, http_status=resp.status_code,
                  content=resp.text, source_date=source_date)
    log.info("Stored adhoc page to copper/adhoc.db")


def run_bronze_derivation(board: str, company: str, job_id: str = "") -> None:
    import copper as _copper, bronze as _bronze
    copper_db = _copper.open_db(board)
    bronze_db = _bronze.open_db(board)
    if board == "ashby":
        count = _bronze.derive_ashby(copper_db, bronze_db, company)
    elif board == "greenhouse":
        count = _bronze.derive_greenhouse(copper_db, bronze_db, company)
    else:  # adhoc
        count = _bronze.derive_adhoc(copper_db, bronze_db, company, job_id)
    log.info("Bronze derivation: %d records for %s/%s", count, board, company)


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
    """Inject config values into a notebook's first code cell via regex. Returns temp path."""
    nb = json.loads(Path(notebook_path).read_text())

    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            source = cell["source"] if isinstance(cell["source"], str) else "".join(cell["source"])
            for var_name, value in replacements.items():
                # Replace any existing value for this variable: VAR = "..." -> VAR = "new"
                source = re.sub(
                    rf'^({re.escape(var_name)}\s*=\s*)"[^"]*"',
                    rf'\1"{value}"',
                    source,
                    count=1,
                    flags=re.MULTILINE,
                )
            cell["source"] = source
            break  # only modify first code cell

    # Write to project dir so the kernel can find classify.py
    tmp_path = f".pipeline_{Path(notebook_path).name}"
    Path(tmp_path).write_text(json.dumps(nb, indent=1))
    return tmp_path


def run_notebook(notebook_path: str, output_label: str) -> bool:
    """Execute a notebook. Returns True on success."""
    log.info("Running %s ...", output_label)
    output_path = f"/tmp/pipeline_out_{Path(notebook_path).stem}.ipynb"
    cmd = [
        "jupyter", "nbconvert", "--to", "notebook", "--execute",
        f"--ExecutePreprocessor.kernel_name={KERNEL_NAME}",
        notebook_path,
        "--output", output_path,
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


def print_summary(company: str, board: str, job_id: str) -> None:
    import sqlite3 as _sqlite3
    try:
        conn = _sqlite3.connect("silver/jobs.db")
        conn.row_factory = _sqlite3.Row
        target = conn.execute(
            "SELECT * FROM jobs WHERE company=? AND board=? AND job_id=?",
            (company, board, job_id)
        ).fetchone()
        conn.close()
    except Exception as e:
        log.warning("Could not query silver for summary: %s", e)
        return
    if not target:
        log.warning("Job %s not found in silver for summary", job_id)
        return
    print("\n" + "=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    print(f"  Target:     {target['title']}")
    print(f"  Company:    {company}")
    print(f"  Department: {target['department'] or 'N/A'}")
    sal_min, sal_max = target["salary_min"], target["salary_max"]
    salary_str = f"${float(sal_min):,.0f} – ${float(sal_max):,.0f}" if sal_min and sal_max else "N/A"
    print(f"  Salary:     {salary_str}")
    print(f"  Location:   {target['location'] or 'N/A'}")
    print("=" * 60)


def main():
    ap = argparse.ArgumentParser(description="Run the full job analysis pipeline")
    ap.add_argument("url", help="Job posting URL (Ashby or Greenhouse)")
    args = ap.parse_args()

    info = parse_job_url(args.url)
    board, company, job_id = info["board"], info["company"], info["job_id"]
    log.info("Parsed: board=%s company=%s job_id=%s", board, company, job_id)

    # Step 1: Scrape → copper
    if board == "adhoc":
        scrape_adhoc(args.url, company, job_id)
    else:
        run_scraper(board, company)
        run_wayback(board, company)

    # Step 2: Bronze derivation
    run_bronze_derivation(board, company, job_id)

    # Step 3: Silver ETL
    nb_config = {"COMPANY": company, "BOARD": board}
    tmp = inject_notebook_config("silver.ipynb", nb_config)
    results = [("Silver ETL", run_notebook(tmp, "Silver ETL"))]

    # Step 4: Gold notebooks

    # Salary analysis
    tmp = inject_notebook_config("analyze_salaries.ipynb", nb_config)
    results.append(("Salary Analysis", run_notebook(tmp, "Salary Analysis")))

    # NLP analysis
    tmp = inject_notebook_config("analyze_nlp.ipynb", nb_config)
    results.append(("NLP Analysis", run_notebook(tmp, "NLP Analysis")))

    # Historical analysis: check bronze instead of CSV file
    import bronze as _bronze
    _bronze_db = _bronze.open_db(board)
    has_historical = bool(_bronze_db.execute(
        "SELECT 1 FROM snapshots WHERE company=? LIMIT 1", (company,)
    ).fetchone())
    if has_historical:
        tmp = inject_notebook_config("analyze_historical.ipynb", nb_config)
        results.append(("Historical Analysis", run_notebook(tmp, "Historical Analysis")))
    else:
        log.info("Skipping historical analysis (no data)")

    # Role gap analysis
    tmp = inject_notebook_config("analyze_role_gap.ipynb", {**nb_config, "JOB_ID": job_id})
    results.append(("Role Gap Analysis", run_notebook(tmp, "Role Gap Analysis")))

    # Step 5: Summary
    print_summary(company, board, job_id)

    print("\nNotebook Results:")
    for name, ok in results:
        status = "✓" if ok else "✗"
        print(f"  {status} {name}")

    # Clean up temp notebooks
    for p in Path(".").glob(".pipeline_*.ipynb"):
        p.unlink()

    if all(ok for _, ok in results):
        print("\nAll notebooks complete. Open them in Jupyter to view charts.")
    else:
        print("\nSome notebooks failed. Check logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
