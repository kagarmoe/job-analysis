# Flexible Role Gap Analysis

**Date:** 2026-03-25
**Status:** Approved

## Goal

Replace the hardcoded role gap notebook with a generic version that works for any job from any company's CSV.

## Input

Two variables in cell 1:
```python
JOB_ID = "2689707b-7314-4246-ac95-1e6466970ba3"
CSV_PATH = "crusoe_salaries.csv"
```

## Scope Scoring

Each role gets a 0-10 score from description patterns:

- Builder (+2 each): "from scratch", "ground up", "greenfield", "first hire", "founding", "build out"
- Owner (+2 each): "own", "define the strategy", "set the vision", "roadmap", "lead the"
- Leader (+1 each): "hire and manage", "build a team", "cross-functional leadership"
- Contributor (-1 each): "contribute to", "support", "assist", "join a team", "report to"

Capped at 0-10.

## Finding Comparables

1. Same normalized department
2. Scope score within ±2 of target
3. If fewer than 5 matches, relax to ±3, then drop department filter

## Cells (7 total)

1. Config + data load — JOB_ID, CSV_PATH, load CSV, compute scope scores
2. Target role summary — title, department, salary, seniority, scope score
3. Comparable roles salary bars — horizontal bars, target highlighted red
4. Salary percentile placement — histogram with target range highlighted
5. Experience vs. salary bubble chart — YoE from descriptions, bubble size = range width
6. Auto-detected skills heatmap — keywords from target description scored across comparables
7. Scope vs. salary scatter — scope on X, midpoint on Y, comparables highlighted

## What Gets Dropped

- Hardcoded job IDs, salary values, CONTENT_FAMILY_PATTERNS, SUPPORT_OPS_IDS
- Historical analysis (Anthropic-specific)
- Support-org-specific charts
- COMPLEXITY_DIMS (replaced by scope scoring)
