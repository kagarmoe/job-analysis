# Gold Data Contract Plan

**Date:** 2026-06-09
**Status:** Approved direction

## Decision

The current gold notebooks are requirements.

Their analyses may be improved, reorganized, or made more reliable, but the analytical coverage they provide must not disappear. The copper -> bronze -> silver pipeline must produce the data needed for those notebooks to run and answer their intended questions.

This plan defines the contract between the ETL layers and the gold layer.

## Required Gold Analyses

### Current Salary Landscape

Notebook: `analyze_salaries.ipynb`

Required explorations:

- Salary data coverage: jobs with and without salary ranges.
- Currency distribution and per-currency native salary stats.
- USD conversion using explicit exchange rates.
- Salary midpoint distribution.
- Salary min vs max scatter.
- Salary range spread distribution.
- Multi-location splitting and role counts by city.
- Salary by city.
- Top and bottom roles by salary midpoint.
- Role counts by department.
- Salary by department.
- Role counts and salary by seniority.
- Department x seniority salary heatmap.
- Work-mode classification and salary comparison.
- Summary dashboard.

Silver data required:

- `company`
- `board`
- `job_id`
- `source_date`
- `title`
- `location`
- `url`
- `department`
- `seniority`
- `work_mode`
- `salary_min`
- `salary_max`
- `currency`
- `salary_unit`
- `has_salary`

### NLP And Text Analysis

Notebook: `analyze_nlp.ipynb`

Required explorations:

- Description coverage and average description length.
- Curated skill and technology keyword counts.
- Skill mentions by department heatmap.
- Years-of-experience extraction.
- Experience distribution.
- Experience vs salary relationship.
- Experience by department.
- Word clouds by department.
- TF-IDF + SVD job-description map.
- KMeans clusters over job descriptions.
- Cluster profiles: top terms, department mix, median salary.
- Education and degree requirement parsing.
- Education mentions by department.
- Description length and bullet count vs salary.

Silver data required:

- `company`
- `board`
- `job_id`
- `title`
- `department`
- `description_md`
- `salary_min`
- `salary_max`
- `currency`
- `yoe`

Shared helper candidates:

- `SKILL_KEYWORDS`
- education requirement patterns
- description length metrics
- a single tested `extract_yoe()` implementation

### Historical Hiring Analysis

Notebook: `analyze_historical.ipynb`

Required explorations:

- Total jobs ever seen.
- Jobs with salary data.
- Active vs closed roles.
- Date range.
- Monthly new postings.
- Monthly closings.
- Estimated active open roles over time.
- New postings by department over time.
- Quarterly salary trends.
- Salary trends by department.
- Time-to-fill for closed roles.
- Active vs closed salary comparison.
- Active vs closed department mix.
- Active vs closed seniority mix.
- Recurring roles and salary changes.
- Historical dashboard.

Silver data required:

- Multiple rows per `(company, board, job_id)` across distinct `source_date` values.
- Stable `source_date` format that can be parsed by truncating to `YYYYMMDD`.
- `company`
- `board`
- `job_id`
- `source_date`
- `title`
- `department`
- `seniority`
- `salary_min`
- `salary_max`
- `currency`
- `has_salary`

Contract rule:

- Silver must preserve history. It must not collapse all snapshots of the same job into a single current row.

### Role Gap Analysis

Notebook: `analyze_role_gap.ipynb`

Required explorations:

- Target job lookup by `JOB_ID`, `COMPANY`, and `BOARD`.
- Target summary: title, department, raw department, salary, location.
- Scope scoring from description language.
- Comparable role selection:
  - same department
  - similar scope within tolerance
  - relax tolerance if too few
  - drop department filter if still too few
- Salary range bars comparing target to comparables.
- Company-wide salary percentile.
- Experience vs salary bubble chart.
- Skills overlap heatmap.
- Scope vs salary scatter.
- Gap summary against comparable median.

Silver data required:

- `company`
- `board`
- `job_id`
- `title`
- `location`
- `department_raw`
- `department`
- `description_md`
- `salary_min`
- `salary_max`
- `currency`
- `yoe`

Shared helper candidates:

- Scope scoring patterns and `score_scope()`.
- Comparable selection rules.
- Target lookup and validation.
- Skill phrase extraction.

## Silver Schema Contract

Silver must expose a stable `jobs` table with these columns for gold:

```text
company
board
job_id
source_date
title
location
url
department_raw
department
seniority
work_mode
salary_text
currency
salary_min
salary_max
salary_unit
description_md
has_title
has_salary
has_location
completeness
yoe
bronze_id
processed_at
fetched_at
```

Silver must also expose:

```text
silver_rejected
audit_log
```

## Copper And Bronze Responsibilities

Copper must preserve raw HTTP content needed to re-derive gold-supporting fields:

- Board API JSON.
- Individual job page HTML where available.
- Ashby application / JSON-LD content where available.
- Wayback snapshots with source timestamps.

Bronze must preserve structured page types needed by silver:

- `api_board`
- `job_page`
- `application`

Bronze rows must retain:

- `company`
- `board`
- `job_id`
- `page_type`
- `source_date`
- `original_url`
- `content`
- `copper_id`

## Contract Tests

The normal test suite must prove the gold contract. `python -m pytest -q` should fail if a future ETL change breaks required gold data.

### Salary Contract Test

Fixture:

- At least one Ashby job with salary in board API content.
- At least one Greenhouse job with salary in board API content.

Assertions after copper -> bronze -> silver:

- `salary_min`, `salary_max`, `currency`, and `salary_unit` are populated.
- `has_salary = 1`.
- `department`, `seniority`, and `work_mode` are populated.
- `location` is populated and suitable for location splitting.

### NLP Contract Test

Fixture:

- Job description includes recognizable skills, education, bullet points, and YoE language.

Assertions after copper -> bronze -> silver:

- `description_md` is populated.
- `yoe` is populated using the shared `classify.extract_yoe()` behavior.
- Salary fields remain available for description-vs-salary analysis.
- Department is populated for department-level text analysis.

### Historical Contract Test

Fixture:

- Same `job_id` appears at two or more distinct `source_date` values.
- At least one job appears only in an earlier snapshot.
- At least one job appears in the latest snapshot.

Assertions after copper -> bronze -> silver:

- Silver contains multiple rows for the repeated `job_id`.
- `source_date` values are preserved.
- Active/closed status can be inferred using latest `source_date`.
- Salary trend analysis can group by quarter.

### Role Gap Contract Test

Fixture:

- One target job with salary and description.
- Several comparable jobs with salary, department, and description.
- At least one same-department comparable.
- At least one cross-department fallback candidate.

Assertions after copper -> bronze -> silver:

- Target lookup by `company`, `board`, `job_id` succeeds.
- Target and comparables have `department`, `description_md`, `salary_min`, and `salary_max`.
- `job_id` is string-compatible.
- Required fields are sufficient to run scope scoring and comparable selection.

### Cross-Layer Trace Contract Test

Fixture:

- Any job that reaches silver.

Assertions:

- `jobs.bronze_id` points to a bronze row.
- That bronze row has `copper_id`.
- That copper row contains the raw content used to derive the silver row.

## Extraction Guidelines

Keep notebooks as the presentation and exploration layer.

Extract logic to Python only when one of these is true:

- The logic is needed by more than one notebook.
- The logic defines a project requirement.
- The logic should be tested to prevent regression.
- The logic is needed by silver to materialize a required gold field.

Good extraction candidates:

- `extract_yoe()`
- `score_scope()`
- comparable-role selection
- skill keyword dictionary
- education pattern dictionary
- description metrics

Do not extract plotting code unless there is a clear reuse or testing reason.

## Acceptance Criteria

- Current gold analytical coverage is documented as required behavior.
- `python -m pytest -q` includes contract tests for salary, NLP, historical, role gap, and cross-layer trace requirements.
- Copper -> bronze -> silver fixtures produce the fields gold notebooks need.
- Gold notebooks remain focused on presentation, exploration, and interpretation.
- Required reusable analysis rules are tested in Python before notebook cleanup changes rely on them.
