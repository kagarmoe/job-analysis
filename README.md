# Job Analysis

Analyze job postings from any company to evaluate salary fairness relative to role scope. Scrapes current and historical job data from Greenhouse and Ashby job boards, then runs automated analysis notebooks.

## Quick Start

```bash
python run_pipeline.py <job_posting_url>
```

Example:

```bash
python run_pipeline.py https://jobs.ashbyhq.com/Crusoe/2689707b-7314-4246-ac95-1e6466970ba3
```

This single command:

1. **Scrapes current jobs** for the company
2. **Scrapes historical jobs** from the Wayback Machine (first run only)
3. **Runs 4 analysis notebooks** with the target job's data
4. **Prints a summary** with salary, department, and location

Output notebooks are written to `/tmp/pipeline_out_*.ipynb` — open them in Jupyter to view charts.

## Supported Job Boards

| Board | URL Pattern | Example |
|---|---|---|
| Ashby | `jobs.ashbyhq.com/{company}/{job_id}` | Crusoe, etc. |
| Greenhouse | `job-boards.greenhouse.io/{company}/jobs/{job_id}` | Anthropic, etc. |

## Analysis Notebooks

| Notebook | What It Does |
|---|---|
| `analyze_salaries.ipynb` | Salary distributions by department, seniority, location |
| `analyze_nlp.ipynb` | Skills extraction, word clouds, job description clustering |
| `analyze_historical.ipynb` | Hiring volume trends, salary changes over time, time-to-fill |
| `analyze_role_gap.ipynb` | Compare a target job's salary vs. scope-matched comparable roles |

All notebooks are parameterized via `CSV_PATH` (and `JOB_ID` for role gap). The pipeline injects these automatically, but you can also run notebooks standalone in Jupyter.

## Role Gap Analysis

The role gap notebook compares a target job against comparable roles using **scope scoring** rather than title-based seniority. Each role gets a 0-10 score based on description language:

- **Builder signals** (+2): "from scratch", "ground up", "greenfield", "first hire"
- **Owner signals** (+2): "own", "define the strategy", "set the vision", "roadmap"
- **Leader signals** (+1): "hire and manage", "build a team", "cross-functional leadership"
- **Contributor signals** (-1): "contribute to", "assist", "join a team", "report to"

Comparables are found by matching on normalized department + similar scope score.

## Setup

Requires Python 3.10+ and a Jupyter kernel named `job-analysis`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install requests beautifulsoup4 html2text pandas matplotlib seaborn scikit-learn wordcloud
python -m ipykernel install --user --name job-analysis --display-name "Python (job-analysis)"
```

## Scrapers

Run scrapers individually if needed:

```bash
# Current jobs
python scrape_greenhouse.py --company anthropic
python scrape_ashby.py --company crusoe

# Historical jobs (Wayback Machine)
python scrape_wayback.py --board greenhouse --company anthropic
python scrape_wayback.py --board ashby --company crusoe
```

## Department Taxonomy

Jobs are classified into 11 normalized departments for cross-company comparison:

Research, Manufacturing, Engineering, Product & Design, People, Finance & Legal, Sales & BD, Marketing & Comms, Public Policy, Security & IT, Operations & Other
