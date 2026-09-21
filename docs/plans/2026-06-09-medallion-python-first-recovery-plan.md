# Medallion Python-First Recovery Plan

**Date:** 2026-06-09
**Status:** Approved direction

## Decision

Keep the medallion architecture, but remove notebooks from the required pipeline execution path.

The core goal is still valid: preserve raw scraped data so parsing, classification, schema, and analysis bugs can be fixed by reprocessing existing data instead of re-scraping live job boards or Wayback snapshots.

The part to reverse is the later layer-as-notebook decision. Copper, bronze, and silver should be implemented as ordinary Python modules with focused tests. Notebooks should remain gold-layer analysis consumers only.

## Problem With The Current Direction

The current repository mixes two ideas:

- Medallion storage: Copper -> Bronze -> Silver -> Gold.
- Notebook execution: `bronze.ipynb`, `silver.ipynb`, and `classify.ipynb` are required for pipeline execution.

The first idea is useful. The second idea adds avoidable fragility:

- Jupyter kernel setup is required for non-visual ETL.
- `%run classify.ipynb` makes shared logic harder to import, test, and review.
- Notebook JSON diffs obscure small logic changes.
- `nbconvert` failures can break the CLI even when Python logic is sound.
- Test setup has to regenerate Python from notebooks.

## Target Architecture

```text
scrape -> copper db -> bronze db -> silver db -> gold analysis
```

Required pipeline execution:

```text
scrapers + Python modules only
```

Optional analysis execution:

```text
Jupyter notebooks read from silver/jobs.db
```

## Ideas Retained From March 2026 Plans

The March 25 plans are deprecated because they are CSV-first, but several ideas remain important:

- Single-command orchestration from a job posting URL remains the user-facing workflow.
- Board detection should remain explicit: Ashby URLs route to Ashby logic, Greenhouse URLs route to Greenhouse logic, and unknown boards route to adhoc handling.
- Scrapers should remain board-specific because each board has different API and HTML behavior.
- Shared classification belongs in one importable Python module, not duplicated across scrapers or notebooks.
- Normalized department taxonomy is still required for cross-company comparison.
- Gold analysis should remain generic across companies and boards.
- Role gap analysis should keep scope scoring, comparable-role matching, and relaxed fallback rules.
- Historical scraping should be skipped or reused when data already exists, but in the medallion version that reuse is based on copper/bronze contents rather than CSV file presence.

## Target Files

```text
run_pipeline.py
scrape_ashby.py
scrape_greenhouse.py
scrape_wayback.py

db.py
classify.py
bronze.py
silver.py

notebooks or repo root:
analyze_salaries.ipynb
analyze_nlp.ipynb
analyze_historical.ipynb
analyze_role_gap.ipynb

tests/
```

`db.py` should stay boring: schema creation, connection helpers, storage helpers, upserts, queries, and low-level parsing utilities that are genuinely storage-adjacent.

`classify.py` should be the source of truth for classification logic: department, normalized department, seniority, work mode, salary parsing if not split into `salary.py`, YOE extraction, and shared constants.

`bronze.py` should derive board-specific structured records from copper.

`silver.py` should merge bronze records into normalized jobs, apply classification, validate rows, write rejects, and append audit logs.

Gold notebooks should query `silver/jobs.db`. They should not be required for the CLI to complete ETL.

## Non-Goals

- Do not return to CSV as the primary architecture.
- Do not make notebooks the source of truth for shared functions.
- Do not require Jupyter to run scrape, bronze, or silver.
- Do not rewrite all scrapers at once unless required by tests.
- Do not delete existing databases as part of the refactor unless a migration or rebuild command explicitly does that.

## Compatibility Rules

- Existing copper, bronze, and silver SQLite file paths should remain valid:
  - `copper/ashby.db`
  - `copper/greenhouse.db`
  - `copper/adhoc.db`
  - `bronze/ashby.db`
  - `bronze/greenhouse.db`
  - `bronze/adhoc.db`
  - `silver/jobs.db`
- Reprocessing should be idempotent.
- The silver upsert key remains `(company, board, job_id, source_date)`.
- Failed silver records must be written to `silver_rejected`; they should not silently disappear.
- `audit_log` should record each silver run.
- `bronze_id` and `copper_id` should continue to support cross-layer tracing from a silver job back to the raw HTTP response.
- `docs/database.md` is not deprecated. Treat it as the current database reference and update it whenever schema, table ownership, or query patterns change.
- `docs/plans/2026-06-09-gold-data-contract-plan.md` defines the required gold analyses and the silver fields needed to support them.

## Test Contract

`python -m pytest -q` must mean the app runs, not merely that isolated helpers work.

The default test suite must include at least one no-network end-to-end smoke test that exercises the same code path as the CLI:

```text
parse URL -> scrape/fetch fixture into copper -> derive bronze -> process silver -> print/query summary
```

That smoke test should:

- Use fixtures or monkeypatched HTTP responses, not live network calls.
- Use temporary copper, bronze, and silver database paths.
- Run without Jupyter.
- Prove a target job reaches `silver/jobs.db`.
- Prove the app can produce the same summary fields the CLI promises: title, company, department, salary if available, and location.
- Fail if `run_pipeline.py` only parses the URL but does not execute the pipeline.

## Implementation Plan

### Task 1: Restore `classify.py` As Source Of Truth

**Goal:** Remove notebook generation from the test and runtime path.

**Changes:**

- Create or restore `classify.py` from the current `classify.ipynb` logic.
- Move `extract_yoe()` into `classify.py`.
- Move shared constants such as seniority ordering and USD conversion into importable Python.
- Update tests to import `classify.py` directly.
- Remove the `tests/conftest.py` notebook-to-Python generation step.

**Verification:**

```bash
python -m pytest tests/test_classify.py -q
python -m pytest -q
```

### Task 2: Keep `db.py` For Storage, Reduce Its Scope

**Goal:** Keep useful current DB work, but avoid turning `db.py` into the whole application.

**Changes:**

- Keep schema functions:
  - `open_copper()`
  - `store_copper()`
  - `open_bronze()`
  - `store_bronze()`
  - `open_silver()`
  - `upsert_job()`
  - `log_run()`
- Keep small data helpers if already stable.
- Move board-specific derivation out of `db.py` into `bronze.py`.
- Move silver merge/classification orchestration out of notebooks into `silver.py`.

**Verification:**

```bash
python -m pytest tests/test_db.py -q
```

### Task 2a: Preserve Database Contract Tests

**Goal:** Make the schema documented in `docs/database.md` executable through tests.

**Changes:**

- Ensure tests cover copper immutability and `(url, source_date)` idempotency.
- Ensure tests cover bronze uniqueness on `(company, job_id, source_date, page_type)`.
- Ensure tests cover silver uniqueness on `(company, board, job_id, source_date)`.
- Ensure tests cover `silver_rejected` rows for failed validation.
- Ensure tests cover `audit_log` rows for silver runs.
- Add at least one cross-layer trace test or fixture that proves `jobs.bronze_id` and `snapshots.copper_id` can connect a silver row back to copper content.

**Verification:**

```bash
python -m pytest tests/test_db.py -q
```

### Task 2b: Preserve Gold Data Contract Tests

**Goal:** Prove copper -> bronze -> silver produces the data required by the gold notebooks.

**Reference:** `docs/plans/2026-06-09-gold-data-contract-plan.md`

**Changes:**

- Add fixture-based tests for salary analysis requirements.
- Add fixture-based tests for NLP/text analysis requirements.
- Add fixture-based tests for historical analysis requirements.
- Add fixture-based tests for role-gap analysis requirements.
- Add cross-layer trace tests from silver back to bronze and copper.

**Verification:**

```bash
python -m pytest -q
```

### Task 3: Replace `bronze.ipynb` With `bronze.py`

**Goal:** Derive bronze data from copper without Jupyter.

**Public API:**

```python
def derive(board: str, company: str, job_id: str | None = None) -> int:
    ...
```

**CLI:**

```bash
python bronze.py --board ashby --company crusoe
python bronze.py --board greenhouse --company anthropic
python bronze.py --board adhoc --company acme --job-id abc123
```

**Changes:**

- Move current `db.derive_ashby()`, `db.derive_greenhouse()`, and `db.derive_adhoc()` logic into `bronze.py`.
- Keep board parsing logic covered by tests.
- Preserve `page_type` values currently used by silver.

**Verification:**

```bash
python -m pytest tests/test_bronze.py -q
python bronze.py --board ashby --company crusoe
```

### Task 4: Replace `silver.ipynb` With `silver.py`

**Goal:** Normalize and classify bronze records into silver without Jupyter.

**Public API:**

```python
def process(board: str, company: str) -> dict[str, int]:
    ...
```

**CLI:**

```bash
python silver.py --board ashby --company crusoe
python silver.py --board greenhouse --company anthropic
```

**Changes:**

- Move silver merge logic from `silver.ipynb` into `silver.py`.
- Import classification functions from `classify.py`.
- Validate required fields before upsert.
- Write rejected records to `silver_rejected`.
- Log runs to `audit_log`.

**Verification:**

```bash
python -m pytest tests/test_silver.py -q
python silver.py --board ashby --company crusoe
```

### Task 5: Update `run_pipeline.py`

**Goal:** Make the pipeline complete without Jupyter.

**Flow:**

```text
parse URL
scrape to copper
derive bronze
process silver
print summary from silver
optionally run gold notebooks
```

**Changes:**

- Replace `nbconvert` calls for `bronze.ipynb` and `silver.ipynb` with Python function calls.
- Keep notebook execution behind an optional flag, for example:

```bash
python run_pipeline.py URL --run-notebooks
```

- Default behavior should complete ETL and print a useful summary without Jupyter.
- Add an app-level test around the CLI or its main orchestration function. This test must run the no-network fixture pipeline end to end and assert that the target job exists in silver afterward.
- Keep URL parsing tests, but do not treat them as sufficient pipeline coverage.

**Verification:**

```bash
python -m pytest tests/test_pipeline.py -q
python run_pipeline.py <known_local_or_test_url>
```

### Task 6: Reclassify Notebook Files

**Goal:** Make notebook ownership clear.

**Changes:**

- Keep gold notebooks:
  - `analyze_salaries.ipynb`
  - `analyze_nlp.ipynb`
  - `analyze_historical.ipynb`
  - `analyze_role_gap.ipynb`
- Remove or archive executable layer notebooks after Python replacements are tested:
  - `copper.ipynb`
  - `bronze.ipynb`
  - `silver.ipynb`
  - `classify.ipynb`
- If any are kept temporarily, mark them as deprecated in a markdown cell.

**Verification:**

```bash
python -m pytest -q
```

### Task 7: Documentation Cleanup

**Goal:** Make the repo tell one story.

**Changes:**

- Update `README.md` so setup and quick start do not imply Jupyter is required for the core pipeline.
- Keep `docs/database.md` as the current database reference.
- Update `docs/database.md` if schema details, table ownership, or cross-layer tracing patterns change.
- Add explicit `ATTACH DATABASE` examples if cross-layer SQL examples rely on querying multiple SQLite files at once.
- Mark old May 18 medallion notebook docs as deprecated and point to this plan.
- Mark old March 25 CSV-first plans as deprecated and point to this plan.
- Document the optional gold notebook workflow separately from the CLI pipeline.

## Suggested Commit Sequence

1. `docs: add python-first medallion recovery plan`
2. `refactor: restore classify.py as source of truth`
3. `refactor: move bronze derivation to python module`
4. `refactor: move silver processing to python module`
5. `refactor: run pipeline without jupyter for etl`
6. `docs: clarify notebook role in gold analysis`
7. `chore: remove deprecated executable layer notebooks`

## Acceptance Criteria

- `python -m pytest -q` passes, and that suite includes an app-level no-network pipeline smoke test.
- If `python -m pytest -q` passes, it is valid to conclude that the core app runs: scrape/fetch fixture, copper write, bronze derivation, silver processing, and summary query all work without Jupyter.
- The pipeline can scrape, derive bronze, process silver, and print a summary without Jupyter.
- Jupyter is only needed when explicitly running analysis notebooks.
- Classification functions are imported from Python, not generated from notebooks.
- Gold notebooks read from `silver/jobs.db`.
- Existing DB paths remain stable.
- Old May 18 notebook-centric docs are clearly deprecated.
