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
    hostname = (parsed.hostname or "").removeprefix("www.")
    company = hostname.split(".")[0]
    return {"board": "adhoc", "company": company, "job_id": job_id}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

KERNEL_NAME = "job-analysis"


def scrape_adhoc(
    url: str,
    company: str,
    job_id: str,
    *,
    copper_base_dir: str = "copper",
) -> None:
    """Fetch a single job page from an unknown board and store to copper/adhoc."""
    import db as _db, requests
    from datetime import date
    copper_db = _db.open_copper("adhoc", base_dir=copper_base_dir)
    source_date = date.today().strftime("%Y%m%d")
    log.info("Fetching adhoc job: %s", url)
    resp = requests.get(url, timeout=30, headers={"User-Agent": "JobBoardResearch/1.0"})
    resp.raise_for_status()
    _db.store_copper(copper_db, url=url, http_status=resp.status_code,
                     content=resp.text, source_date=source_date)
    log.info("Stored adhoc page to copper/adhoc.db")



def run_scraper(
    board: str,
    company: str,
    *,
    copper_base_dir: str = "copper",
) -> None:
    """Run the appropriate scraper for the given board."""
    if board == "ashby":
        import scrape_ashby

        scrape_ashby.scrape_all_jobs(company, copper_base_dir=copper_base_dir)
    elif board == "greenhouse":
        import scrape_greenhouse

        scrape_greenhouse.scrape_all_jobs(company, copper_base_dir=copper_base_dir)
    else:
        log.warning("run_scraper called for unsupported board %r — skipping", board)
        return


def run_wayback(
    board: str,
    company: str,
    *,
    copper_base_dir: str = "copper",
) -> None:
    """Run wayback scraper to populate copper/bronze with historical snapshots."""
    if copper_base_dir != "copper":
        log.info("Skipping wayback for non-default copper base dir: %s", copper_base_dir)
        return
    log.info("Running wayback scraper for %s/%s...", board, company)
    cmd = [sys.executable, "scrape_wayback.py", "--board", board, "--company", company]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        log.warning("Wayback scraper failed — continuing without historical data")


def inject_notebook_config(notebook_path: str, replacements: dict) -> str:
    """Inject config values into a notebook's first code cell via regex. Returns temp path."""
    nb = json.loads(Path(notebook_path).read_text())

    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            source = cell["source"] if isinstance(cell["source"], str) else "".join(cell["source"])
            for var_name, value in replacements.items():
                # Replace any existing value for this variable: VAR = "..." -> VAR = "new"
                new_source, n = re.subn(
                    rf'^({re.escape(var_name)}\s*=\s*)["\'][^"\']*["\']',
                    rf'\1"{value}"',
                    source,
                    count=1,
                    flags=re.MULTILINE,
                )
                if n == 0:
                    raise RuntimeError(
                        f"Could not inject {var_name!r} into {notebook_path} — "
                        f"no assignment found matching the pattern"
                    )
                source = new_source
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


def get_summary(
    company: str,
    board: str,
    job_id: str,
    *,
    silver_base_dir: str = "silver",
) -> dict | None:
    import db as _db

    try:
        conn = _db.open_silver(base_dir=silver_base_dir)
        target = conn.execute(
            "SELECT * FROM jobs WHERE company=? AND board=? AND job_id=?"
            " ORDER BY source_date DESC LIMIT 1",
            (company, board, job_id)
        ).fetchone()
        conn.close()
    except Exception as e:
        log.warning("Could not query silver for summary: %s", e)
        return None
    if not target:
        log.warning("Job %s not found in silver for summary", job_id)
        return None

    return {
        "title": target["title"],
        "company": company,
        "department": target["department"],
        "salary_min": target["salary_min"],
        "salary_max": target["salary_max"],
        "location": target["location"],
    }


def print_summary(summary: dict | None) -> None:
    if not summary:
        return
    print("\n" + "=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    print(f"  Target:     {summary['title']}")
    print(f"  Company:    {summary['company']}")
    print(f"  Department: {summary['department'] or 'N/A'}")
    sal_min, sal_max = summary["salary_min"], summary["salary_max"]
    salary_str = f"${float(sal_min):,.0f} – ${float(sal_max):,.0f}" if sal_min and sal_max else "N/A"
    print(f"  Salary:     {salary_str}")
    print(f"  Location:   {summary['location'] or 'N/A'}")
    print("=" * 60)


def run_gold_notebooks(
    company: str,
    board: str,
    job_id: str,
    *,
    silver_base_dir: str = "silver",
    bronze_base_dir: str = "bronze",
) -> list[tuple[str, bool]]:
    nb_config = {"COMPANY": company, "BOARD": board}
    results: list[tuple[str, bool]] = []

    import db as _db

    silver_db = _db.open_silver(base_dir=silver_base_dir)
    has_salary = bool(silver_db.execute(
        "SELECT 1 FROM jobs WHERE company=? AND board=? AND has_salary=1 LIMIT 1",
        (company, board)
    ).fetchone())
    if has_salary:
        tmp = inject_notebook_config("analyze_salaries.ipynb", nb_config)
        results.append(("Salary Analysis", run_notebook(tmp, "Salary Analysis")))
    else:
        log.info("Skipping salary analysis (no salary data found)")

    tmp = inject_notebook_config("analyze_nlp.ipynb", nb_config)
    results.append(("NLP Analysis", run_notebook(tmp, "NLP Analysis")))

    bronze_db = _db.open_bronze(board, base_dir=bronze_base_dir)
    has_historical = bool(bronze_db.execute(
        "SELECT 1 FROM snapshots WHERE company=? LIMIT 1", (company,)
    ).fetchone())
    if has_historical:
        tmp = inject_notebook_config("analyze_historical.ipynb", nb_config)
        results.append(("Historical Analysis", run_notebook(tmp, "Historical Analysis")))
    else:
        log.info("Skipping historical analysis (no data)")

    tmp = inject_notebook_config("analyze_role_gap.ipynb", {**nb_config, "JOB_ID": job_id})
    results.append(("Role Gap Analysis", run_notebook(tmp, "Role Gap Analysis")))
    return results


def run_pipeline(
    url: str,
    *,
    run_notebooks: bool = False,
    copper_base_dir: str = "copper",
    bronze_base_dir: str = "bronze",
    silver_base_dir: str = "silver",
) -> dict | None:
    import bronze
    import silver

    info = parse_job_url(url)
    board, company, job_id = info["board"], info["company"], info["job_id"]
    log.info("Parsed: board=%s company=%s job_id=%s", board, company, job_id)

    if board == "adhoc":
        scrape_adhoc(url, company, job_id, copper_base_dir=copper_base_dir)
    else:
        run_scraper(board, company, copper_base_dir=copper_base_dir)
        run_wayback(board, company, copper_base_dir=copper_base_dir)

    bronze_count = bronze.derive(
        board,
        company,
        job_id if board == "adhoc" else None,
        copper_base_dir=copper_base_dir,
        bronze_base_dir=bronze_base_dir,
    )
    log.info("Bronze derivation complete: %d records for %s/%s", bronze_count, company, board)

    silver_result = silver.process(
        board,
        company,
        bronze_base_dir=bronze_base_dir,
        silver_base_dir=silver_base_dir,
    )
    log.info(
        "Silver ETL complete: processed=%d upserted=%d rejected=%d",
        silver_result["processed"],
        silver_result["upserted"],
        silver_result["rejected"],
    )

    summary = get_summary(company, board, job_id, silver_base_dir=silver_base_dir)

    if run_notebooks:
        results = run_gold_notebooks(
            company,
            board,
            job_id,
            silver_base_dir=silver_base_dir,
            bronze_base_dir=bronze_base_dir,
        )
        print("\nNotebook Results:")
        for name, ok in results:
            status = "✓" if ok else "✗"
            print(f"  {status} {name}")
        for path in Path(".").glob(".pipeline_*.ipynb"):
            path.unlink()
        if not all(ok for _, ok in results):
            raise RuntimeError("Some notebooks failed")

    return summary


def main():
    ap = argparse.ArgumentParser(description="Run the full job analysis pipeline")
    ap.add_argument("url", help="Job posting URL (Ashby or Greenhouse)")
    ap.add_argument(
        "--run-notebooks",
        action="store_true",
        help="Execute optional gold analysis notebooks after ETL",
    )
    args = ap.parse_args()

    try:
        summary = run_pipeline(args.url, run_notebooks=args.run_notebooks)
    except Exception as exc:
        log.error("Pipeline failed: %s", exc)
        sys.exit(1)
    print_summary(summary)


if __name__ == "__main__":
    main()
