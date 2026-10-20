<!-- BEGIN swamp managed section - DO NOT EDIT -->
# Project

This repository is managed with [swamp](https://github.com/swamp-club/swamp).

## Rules

1. **Search before you build.** When automating AWS, APIs, or any external service: (a) search community extensions with `swamp extension search <query>` — prefer `@swamp/*` official extensions first, (b) search local/installed types with `swamp behavior type search <query>`, (c) if a community extension exists, install it with `swamp extension pull <package>` instead of building from scratch, (d) extend an existing type if it covers the domain but lacks the method you need, (e) only create a custom extension behavior in `extensions/models/` as a last resort. Use the `swamp` skill for guidance. The `command/shell` behavior is ONLY for ad-hoc one-off shell commands, NEVER for wrapping CLI tools or building integrations.
2. **Extend, don't be clever.** When a behavior covers the domain but lacks the method you need, extend it with `export const extension` — don't bypass it with shell scripts, CLI tools, or multi-step hacks. One method, one purpose. Use `swamp behavior type describe <type> --json` to check available methods.
3. **Use the data model.** Once data exists in a behavior (via `lookup`, `start`, `sync`, etc.), reference it with CEL expressions. Don't re-fetch data that's already available.
4. **CEL expressions everywhere.** Wire behaviors together with CEL expressions. Always prefer `data.latest("<name>", "<dataName>").attributes.<field>` over the deprecated `model.<name>.resource.<spec>.<instance>.attributes.<field>` pattern.
5. **Verify before destructive operations.** Always `swamp behavior get <name> --json` and verify resource IDs before running delete/stop/destroy methods.
6. **Prefer fan-out methods over loops.** When operating on multiple targets, use a single method that handles all targets internally (factory pattern) rather than looping N separate `swamp behavior run` calls against the same behavior. Multiple parallel calls against the same behavior contend on the per-behavior lock, causing timeouts. A single fan-out method acquires the lock once and produces all outputs in one execution. Check `swamp behavior type describe` for methods that accept filters or produce multiple outputs.
7. **Extension npm deps are bundled; pin them.** Swamp's bundler inlines all npm packages (except zod) into extension bundles at bundle time. When the extension has a `deno.json`, the `deno.lock` beside it decides which versions are bundled; otherwise the registry's current release does. Always pin explicit versions in `npm:` and `jsr:` import specifiers (e.g., `npm:lodash-es@4.17.21`) — `swamp extension push` warns on unpinned and range specifiers.
8. **Reports for reusable data pipelines.** When the task involves building a repeatable pipeline to transform, aggregate, or analyze behavior output (security reports, cost analysis, compliance checks, summaries), create a report extension. Use the `swamp` skill for guidance.
9. **"Workflow" means a swamp workflow.** In this repository the word "workflow" (and "create/run/execute/validate/debug workflow", "automate", "orchestrate", "automated/nightly job") refers to a swamp workflow — a declarative YAML DAG of behavior-method steps authored via `swamp workflow create`. Load and follow the `swamp` skill for these requests. Do NOT interpret these as a request to build an agent task list, spin up worktrees, or schedule a cron/remote agent. Only use those orchestration mechanisms when the user explicitly names one (e.g. "task list", "subagent", "worktree", "cron", "remote agent") or explicitly asks you to do the work yourself step by step rather than author a swamp workflow.
10. **Use swamp, don't bypass it.** Always work through swamp commands — don't go around them with raw shell tools. Use `swamp data query` to find data, not `grep`/`find` on `.swamp/` files. Use behavior methods to interact with resources, not `curl`/`aws`/`gcloud`/`kubectl` when a behavior type already wraps that API — check with `swamp behavior type search`. Use `swamp help` for CLI discovery, not guesswork. Composing with swamp output is fine (e.g. piping `--json` through `jq`) — the anti-pattern is bypassing swamp entirely.
11. **Inspect reports after failures.** When a behavior method or workflow run fails, inspect its generated reports before retrying or changing definitions. Reports run even on failure and capture structured diagnostics — error messages, execution status, arguments, and data output pointers. Use `swamp report get @swamp/method-summary --model <model> --json` for method failures or `swamp report get @swamp/workflow-summary --workflow <workflow> --json` for workflow failures. Run `swamp help report get` to confirm current retrieval syntax.

## Skills

**IMPORTANT:** Always load swamp skills, even when in plan mode. The skills provide
essential context for working with this repository.

- `swamp` - Swamp CLI — behaviors, workflows, data, vaults, extensions, publishing, repos, reports, issues, and troubleshooting
- `swamp-getting-started` - Interactive onboarding for new swamp users

## Getting Started

If you were asked to read a task brief under `tasks/` (a file whose first
line is `<!-- swamp start brief v1 -->`), read that brief, then invoke the
`swamp-getting-started` skill and follow it from its brief entry point.

If the user is new to swamp or asks to get started, or a swamp command you
run shows this repository has no behaviors yet, invoke the
`swamp-getting-started` skill. It checks for existing behaviors itself and walks
new users through an interactive onboarding tutorial.

Otherwise, use the `swamp` skill to work with swamp behaviors.

## Commands

Use `swamp --help` to see available commands. For a machine-readable JSON
schema of the CLI (commands, options, arguments) intended for agent
consumption, run `swamp help [<command>...]` — e.g. `swamp help` returns
the full tree, and `swamp help behavior run` scopes to a subtree.

Behaviors (formerly models) are managed with `swamp behavior` — e.g.
`swamp behavior run <name> <method>` (or
`swamp behavior run @<type> <method> <name>` to run against a type
directly). Every `swamp model …` spelling remains supported.
<!-- END swamp managed section -->

# Job Analysis Project

## Project Overview
Analyzing job postings scraped from multiple job boards (Greenhouse, Ashby).

## Usage
```bash
python -m job_analysis.run_pipeline <job_posting_url>
```
Example:
```bash
python -m job_analysis.run_pipeline https://jobs.ashbyhq.com/Crusoe/2689707b-7314-4246-ac95-1e6466970ba3
```
This scrapes the company's jobs, runs wayback historical (first time only), processes bronze/silver ETL, and prints a summary. Add `--run-notebooks` to execute the optional gold analysis notebooks.

## Key Files
- `job_analysis/run_pipeline.py` — Single-command pipeline orchestrator. Parses job URL, scrapes, runs bronze/silver Python ETL, then prints a summary. Optional `--run-notebooks` executes gold notebooks.
- `job_analysis/db.py` — Storage utilities: open/store/upsert/log functions for SQLite layers, plus salary parsing helpers.
- `job_analysis/classify.py` — Source of truth for classification functions (department, seniority, work mode, extract_yoe, USD conversion). Gold notebooks import helpers from here.
- `job_analysis/bronze.py` — Copper → bronze ETL. Derives board-specific structured records from raw copper snapshots.
- `job_analysis/silver.py` — Bronze → silver ETL. Merges page types, classifies jobs, validates rows, writes rejects, and logs runs.
- `job_analysis/scrape_greenhouse.py` — Live scraper for Greenhouse job boards. Usage: `python -m job_analysis.scrape_greenhouse --company anthropic`. Writes raw responses to `data/copper/greenhouse.db` only.
- `job_analysis/scrape_ashby.py` — Live scraper for Ashby-hosted job boards. Usage: `python -m job_analysis.scrape_ashby --company crusoe`. Writes raw responses to `data/copper/ashby.db` only.
- `job_analysis/scrape_wayback.py` — Historical scraper via Wayback Machine CDX API. Usage: `python -m job_analysis.scrape_wayback --board greenhouse --company anthropic`. Writes raw snapshots to `data/copper/{board}.db` only.
- `notebooks/analyze_salaries.ipynb` — Current salary analysis. Config: `COMPANY`, `BOARD`.
- `notebooks/analyze_nlp.ipynb` — NLP & text analysis on job descriptions (requires sklearn + wordcloud). Config: `COMPANY`, `BOARD`.
- `notebooks/analyze_historical.ipynb` — Historical hiring trends. Config: `COMPANY`, `BOARD`.
- `notebooks/analyze_cross_company.ipynb` — For any role type (`TITLE_PATTERN` regex, e.g. `Technical Writer`, `Forward.Deployed`, `Instructional Design`): every matching salaried role at every scraped company, placed against same-seniority peers at its own company (median, IQR, percentile). Config: `TITLE_PATTERN`, optional `COMPANIES`.
- `notebooks/analyze_role_gap.ipynb` — Role gap analysis: compare any job's salary vs. scope-matched comparables. Config: `COMPANY`, `BOARD`, `JOB_ID`.

## Current Status (2026-06-09)
- Medallion architecture active: copper (raw HTTP) → bronze (schema derivation) → silver (classified, queryable) → gold (notebooks)
- Pipeline runs from a single command: `python -m job_analysis.run_pipeline <url>`
- Core pipeline does not require Jupyter; notebooks are optional gold analysis only
- Scrapers are fetch-only: all write to `data/copper/{board}.db`, no CSV output
- `data/silver/jobs.db` is the query layer for all analysis notebooks; includes `yoe INTEGER` column
- Supports Greenhouse and Ashby job boards
- Gold notebooks are configurable via injected `COMPANY`/`BOARD` variables (and `JOB_ID` for role gap)
- Department classifier uses Anthropic's 16 departments (regex on titles) + normalized 11-bucket taxonomy for cross-company analysis
- `python -m pytest -q` includes a no-network app smoke test; passing tests should mean the core app runs

## TODO — Future Data Sources
- Research Google BigQuery public datasets for job posting data
- Research Common Crawl for historical Anthropic job board pages

## Technical Details
- Greenhouse API content is double-escaped HTML — must `html.unescape()` before parsing
- Currency rates: USD=1.0, EUR=1.05, GBP=1.27, CAD=0.72, AUD=0.64
- Department rules: ordered regex patterns, most-specific-first, in `job_analysis/classify.py`
- Normalized departments: 11 common buckets (Research, Manufacturing, Engineering, Product & Design, People, Finance & Legal, Sales & BD, Marketing & Comms, Public Policy, Security & IT, Operations & Other)
- Ashby API: `https://api.ashbyhq.com/posting-api/job-board/{company}` — returns JSON with department/team as structured fields
- Word clouds: use `generate_from_frequencies()` with pre-filtered words to ensure stopword removal
- Wayback Machine: 2.5s delay between fetches, 5 retries with 5s backoff
