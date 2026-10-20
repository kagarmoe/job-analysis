# Graph Report - .  (2026-10-20)

## Corpus Check
- 37 files · ~62,514 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 361 nodes · 825 edges · 20 communities
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 58 edges (avg confidence: 0.9)
- Token cost: 365,758 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_CopperBronze Storage & Smoke Test|Copper/Bronze Storage & Smoke Test]]
- [[_COMMUNITY_Department & Seniority Classification|Department & Seniority Classification]]
- [[_COMMUNITY_Salary Parsing & Silver DB|Salary Parsing & Silver DB]]
- [[_COMMUNITY_Bronze Board Derivation|Bronze Board Derivation]]
- [[_COMMUNITY_Gold Notebooks & Role Gap|Gold Notebooks & Role Gap]]
- [[_COMMUNITY_Salary Trends & TF-IDF|Salary Trends & TF-IDF]]
- [[_COMMUNITY_Wayback Historical Scraper|Wayback Historical Scraper]]
- [[_COMMUNITY_Active Roles & Skill Matrices|Active Roles & Skill Matrices]]
- [[_COMMUNITY_Medallion Gold Contract|Medallion Gold Contract]]
- [[_COMMUNITY_Clustering & Description Length|Clustering & Description Length]]
- [[_COMMUNITY_Hiring Activity & Skills|Hiring Activity & Skills]]
- [[_COMMUNITY_Years of Experience|Years of Experience]]
- [[_COMMUNITY_Swamp Repo Config|Swamp Repo Config]]
- [[_COMMUNITY_Swamp Pipeline Extension|Swamp Pipeline Extension]]
- [[_COMMUNITY_Historical Snapshot Dataset|Historical Snapshot Dataset]]
- [[_COMMUNITY_Scope Score Comparables|Scope Score Comparables]]
- [[_COMMUNITY_Same-Seniority Peer Position|Same-Seniority Peer Position]]
- [[_COMMUNITY_Time to Fill|Time to Fill]]
- [[_COMMUNITY_Salary Coverage Labels|Salary Coverage Labels]]
- [[_COMMUNITY_Location Splitting|Location Splitting]]

## God Nodes (most connected - your core abstractions)
1. `normalize_department()` - 23 edges
2. `DataFrame` - 23 edges
3. `derive()` - 18 edges
4. `open_silver()` - 18 edges
5. `process()` - 18 edges
6. `store_copper()` - 17 edges
7. `open_copper()` - 16 edges
8. `open_bronze()` - 16 edges
9. `extract_yoe()` - 15 edges
10. `run_pipeline()` - 14 edges

## Surprising Connections (you probably didn't know these)
- `merge_to_silver()` --shares_data_with--> `Bronze page_type values (api_board, job_page, application)`  [INFERRED]
  silver.py → docs/database.md
- `derive_adhoc()` --references--> `Adhoc board (unknown boards, HTML only)`  [INFERRED]
  bronze.py → docs/database.md
- `add_usd_salary()` --implements--> `Fixed USD conversion rates (EUR 1.05, GBP 1.27, CAD 0.72, AUD 0.64)`  [INFERRED]
  classify.py → CLAUDE.md
- `extract_yoe()` --semantically_similar_to--> `extract_required_yoe()`  [INFERRED] [semantically similar]
  classify.py → gold_analysis.py
- `open_copper()` --implements--> `copper snapshots table`  [INFERRED]
  db.py → docs/database.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Medallion ETL flow: scrapers -> copper -> bronze -> silver -> gold** — scrape_ashby, scrape_greenhouse, scrape_wayback, db_store_copper, bronze_derive, silver_process, silver_jobs_table, gold_layer [INFERRED 0.85]
- **Gold notebooks bound by the silver data contract** — analyze_salaries, analyze_nlp, analyze_historical, analyze_role_gap, silver_jobs_table, gold_contract_tests [EXTRACTED 1.00]
- **Architecture evolution: CSV-first -> layer-as-notebook -> Python-first medallion** — csv_first_architecture, layer_as_notebook_decision, python_first_etl_decision, medallion_architecture [EXTRACTED 1.00]
- **Copper to bronze to silver to gold medallion flow** — copper_board_db, bronze_derive, bronze_board_db, silver_process, silver_jobs_db, gold_notebooks [EXTRACTED 1.00]
- **Fetch-only scrapers writing raw responses to copper** — scrape_ashby_scrape_all_jobs, scrape_greenhouse_scrape_all_jobs, scrape_wayback_scrape_api_snapshots, run_pipeline_scrape_adhoc, db_store_copper [EXTRACTED 1.00]
- **Silver row classification via classify.py** — silver_merge_to_silver, classify_classify_seniority, classify_normalize_department, classify_classify_work_mode, classify_extract_yoe [EXTRACTED 1.00]
- **Copper->bronze->silver ETL exercised end to end in tests** — db_store_copper, bronze_derive, silver_process, db_open_silver, tests_test_gold_contract__run_layers, tests_test_pipeline_test_pipeline_smoke_runs_without_jupyter_or_network [EXTRACTED 1.00]
- **Notebook source tests enforce gold_analysis helper reuse** — analyze_salaries, analyze_nlp, analyze_historical, analyze_role_gap, tests_test_gold_notebooks__notebook_source, concept_notebooks_delegate_to_gold_analysis [INFERRED 0.95]
- **Role gap comparable selection helpers** — gold_analysis_score_scope, gold_analysis_select_role_gap_comparables, gold_analysis_extract_required_yoe, gold_analysis_build_skill_overlap_matrix, analyze_role_gap [INFERRED 0.85]

## Communities (20 total, 0 thin omitted)

### Community 0 - "Copper/Bronze Storage & Smoke Test"
Cohesion: 0.06
Nodes (58): Ashby job board (posting-api), Bronze SQLite layer (bronze/{board}.db snapshots table), derive(), Derive bronze records for one board/company from copper snapshots., No-network app smoke test (scraper/wayback stubbed, no Jupyter), Copper SQLite layer (copper/{board}.db), open_bronze(), open_copper() (+50 more)

### Community 1 - "Department & Seniority Classification"
Cohesion: 0.08
Nodes (46): Anthropic 16-department title regex classifier, add_usd_salary(), _annual_multiplier(), classify_department(), classify_seniority(), classify_work_mode(), extract_yoe(), normalize_department() (+38 more)

### Community 2 - "Salary Parsing & Silver DB"
Cohesion: 0.08
Nodes (41): audit_log table, extract_salary_block_from_html(), get_copper(), log_run(), looks_like_salary_text(), normalize_whitespace(), open_silver(), parse_json_ld_job_posting() (+33 more)

### Community 3 - "Bronze Board Derivation"
Cohesion: 0.08
Nodes (36): Adhoc board (unknown boards, HTML only), derive_adhoc(), derive_ashby(), derive_greenhouse(), bronze.ipynb (deprecated layer notebook), Bronze layer (schema applied), main(), Bronze page_type values (api_board, job_page, application) (+28 more)

### Community 4 - "Gold Notebooks & Role Gap"
Cohesion: 0.23
Nodes (18): Comparable role selection with relaxed fallback, Gold notebooks delegate logic to shared gold_analysis helpers (no inline reimplementation), Flexible Role Gap Analysis design (deprecated), Gold Data Contract Plan, Scope scoring (builder/owner/leader/contributor signals, 0-10), Silver must preserve history (no collapse to current row), silver jobs table (silver/jobs.db), Silver upsert key (company, board, job_id, source_date) (+10 more)

### Community 5 - "Salary Trends & TF-IDF"
Cohesion: 0.17
Nodes (17): build_department_quarterly_salary_trends(), build_quarterly_salary_stats(), build_tfidf_cluster_projection(), data_quality(), Build TF-IDF features, 2D SVD coordinates, and KMeans cluster labels., One-line header for a notebook's loaded frame; stops charts being read at n=7 un, Add salary quarters and summarize salary midpoint stats by quarter., Return quarterly median salaries for departments with enough observations. (+9 more)

### Community 6 - "Wayback Historical Scraper"
Cohesion: 0.14
Nodes (15): _build_session(), cdx_query(), _extract_job_fields(), _fetch_snapshot(), Scrape historical job postings from the Wayback Machine.  Supports Greenhouse an, Extract job title from <title> tag, stripping ' | Company' suffix., Return (content, wayback_url), reading copper cache first., Fallback for Ashby boards where the board-level API was never archived.      Cop (+7 more)

### Community 7 - "Active Roles & Skill Matrices"
Cohesion: 0.14
Nodes (15): DataFrame, build_active_closed_comparison(), build_active_role_timeseries(), build_department_skill_matrix(), build_skill_overlap_matrix(), Build department x skill percentages for descriptions mentioning each skill., Count how many roles were active at each point in a date range., Build salary, department, and seniority summaries by active/closed status. (+7 more)

### Community 8 - "Medallion Gold Contract"
Cohesion: 0.42
Nodes (13): Gold-layer data contract on silver/jobs.db, Medallion layers copper -> bronze -> silver -> gold, _ashby_job(), _description(), _greenhouse_job(), _run_layers(), _store_ashby_board(), _store_greenhouse_board() (+5 more)

### Community 9 - "Clustering & Description Length"
Cohesion: 0.16
Nodes (13): build_cluster_profiles(), build_description_length_analysis(), DescriptionLengthAnalysis, Container for TF-IDF projection and clustering outputs., Container for description length metrics and salary relationships., Summarize each TF-IDF cluster with terms, department mix, and median salary., Derive description length metrics and salary relationship summaries., Summarize salary changes for normalized titles posted multiple times. (+5 more)

### Community 10 - "Hiring Activity & Skills"
Cohesion: 0.15
Nodes (13): build_education_requirement_summary(), build_monthly_hiring_activity(), build_skill_mention_counts(), extract_skill_phrases(), Count roles whose descriptions mention each skill pattern., Build overall and department-level education requirement mention summaries., Count monthly new postings and monthly closings., Extract repeated bigram phrases from a description as skill signals. (+5 more)

### Community 11 - "Years of Experience"
Cohesion: 0.22
Nodes (9): build_yoe_dataset(), extract_required_yoe(), Return the highest minimum years-of-experience requirement found in text., Return a copy of jobs with parsed years-of-experience requirements., Summarize parseable YoE requirements by department., summarize_yoe_by_department(), test_build_yoe_dataset_and_department_summary(), test_extract_required_yoe_rejects_out_of_range_values() (+1 more)

### Community 12 - "Swamp Repo Config"
Cohesion: 0.29
Nodes (6): job-pipeline swamp model (@kagarmoe/job-pipeline), upstream_extensions.json (@swamp/stagecraft 2026.10.15.2), Swamp repo rules (search before build, extend, CEL, fan-out, workflows), @swamp/stagecraft extension, swamp (repo automation CLI), .swamp.yaml (swamp repo config)

### Community 13 - "Swamp Pipeline Extension"
Cohesion: 0.29
Nodes (7): GlobalArgs, GlobalArgsSchema, model, PipelineOutputSchema, RunArgs, RunArgsSchema, SummarySchema

### Community 14 - "Historical Snapshot Dataset"
Cohesion: 0.29
Nodes (7): build_historical_dataset(), latest_per_job(), One row per job: its newest snapshot.      Silver is keyed on (company, board, j, Build one row per job with first/last seen timestamps and active status., test_build_historical_dataset_derives_first_last_and_active_flags(), test_build_historical_dataset_keeps_latest_snapshot_row(), test_latest_per_job_keeps_newest_snapshot_per_job()

### Community 15 - "Scope Score Comparables"
Cohesion: 0.33
Nodes (6): Score role ownership/scope from 0-10 using heuristic language cues., Select comparable salaried roles, relaxing filters when needed., score_scope(), select_role_gap_comparables(), test_score_scope_rewards_builder_and_owner_language(), test_select_role_gap_comparables_prefers_same_department_then_relaxes()

### Community 16 - "Same-Seniority Peer Position"
Cohesion: 0.50
Nodes (4): build_relative_position(), Any, Place one salaried role against same-seniority peers at the same company.      `, test_build_relative_position_uses_same_seniority_peers_and_flags_thin_pools()

### Community 17 - "Time to Fill"
Cohesion: 0.67
Nodes (3): build_time_to_fill_dataset(), Return closed roles with a positive open duration., test_build_time_to_fill_dataset_filters_zero_day_roles()

### Community 18 - "Salary Coverage Labels"
Cohesion: 0.67
Nodes (3): coverage_label(), Chart-title suffix so no salary statistic is read without its n and disclosure r, test_coverage_label_reports_n_and_disclosure_rate()

### Community 19 - "Location Splitting"
Cohesion: 0.67
Nodes (3): Split multi-location strings on common delimiters for city-level analysis., split_locations(), test_split_locations_handles_multi_value_and_missing_inputs()

## Ambiguous Edges - Review These
- `build_tfidf_cluster_projection()` → `seed_labels.json (labeled department seed set)`  [AMBIGUOUS]
  seed_labels.json · relation: conceptually_related_to
- `run_pipeline.py` → `job-pipeline swamp model (@kagarmoe/job-pipeline)`  [AMBIGUOUS]
  models/@kagarmoe/job-pipeline/job-pipeline.yaml · relation: conceptually_related_to
- `README.md` → `Normalized department taxonomy (cross-company buckets)`  [AMBIGUOUS]
  README.md · relation: references

## Knowledge Gaps
- **11 isolated node(s):** `GlobalArgsSchema`, `GlobalArgs`, `RunArgsSchema`, `RunArgs`, `SummarySchema` (+6 more)
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `build_tfidf_cluster_projection()` and `seed_labels.json (labeled department seed set)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `run_pipeline.py` and `job-pipeline swamp model (@kagarmoe/job-pipeline)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `README.md` and `Normalized department taxonomy (cross-company buckets)`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **Why does `extract_yoe()` connect `Department & Seniority Classification` to `Years of Experience`, `Gold Notebooks & Role Gap`?**
  _High betweenness centrality (0.091) - this node is a cross-community bridge._
- **Why does `Python-first ETL decision (notebooks gold-only)` connect `Copper/Bronze Storage & Smoke Test` to `Department & Seniority Classification`, `Salary Parsing & Silver DB`, `Bronze Board Derivation`?**
  _High betweenness centrality (0.086) - this node is a cross-community bridge._
- **Why does `normalize_department()` connect `Department & Seniority Classification` to `Bronze Board Derivation`?**
  _High betweenness centrality (0.070) - this node is a cross-community bridge._
- **What connects `Derive per-job bronze records from copper for an Ashby company.`, `Derive per-job bronze records from copper for a Greenhouse company.`, `Derive bronze records for an adhoc job.` to the rest of the system?**
  _74 weakly-connected nodes found - possible documentation gaps or missing edges._