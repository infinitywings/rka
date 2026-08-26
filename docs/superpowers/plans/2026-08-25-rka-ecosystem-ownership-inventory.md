# RKA Ecosystem E0 Component Ownership Inventory

- Status: E0 review draft under ADR 0012
- Date: 2026-08-25
- Inventory baseline: `origin/main` at `57fa8f07bf6f298bc5b3a9cf113cf492898d8a03`
- Scope: current files in `infinitywings/rka`; the `agentic` branch is noted but
  is not treated as part of this baseline
- Authority: [ADR 0012](../../adr/0012-rka-ecosystem-repository-boundaries.md)

## 1. Purpose and disposition vocabulary

This inventory assigns one target disposition to every current component
family before repository extraction begins. The dispositions are deliberately
about the end state, not about where a file happens to live today.

| Disposition | Meaning |
|---|---|
| `core` | Remains an active, supported part of `infinitywings/rka`. |
| `writer` | Moves with history to `infinitywings/rka-writer`; no active copy remains in Core after the compatibility window. |
| `agentic` | Moves with history to `infinitywings/rka-agentic`; no active copy remains in Core after the compatibility window. |
| `core-legacy` | Remains readable or callable in Core only for compatibility; receives no feature development. |
| `writer-legacy-export` | Remains in Core only long enough to read, verify, and export historical Writer state. |
| `remove-after-migration` | Has no continuing authority after its replacement is verified; remove only after its stated migration gate. |

No row below has two dispositions. When a current source file contains more
than one product responsibility, the inventory splits the file by endpoint or
subcomponent and records the required refactor.

## 2. Coverage and counting method

The inventory was produced by static inspection of the baseline above:

- SQL `CREATE TABLE` and `CREATE VIRTUAL TABLE` declarations were collected
  from `schema.sql`, `schema_phase2.sql`, migrations 001--051, and the migration
  runner's `schema_migrations` table. SQLite-generated FTS shadow tables were
  excluded. Three `*_v2` names are migration staging tables, not independent
  end-state authorities, but are included so every declaration is accounted
  for.
- REST endpoints were counted from the 38 mounted route modules using FastAPI
  `@router.get/post/put/patch/delete` decorators. The application health route
  is counted separately in the package-entry-point section because it is
  declared in `rka/api/app.py`, not a route module.
- MCP typed operations were read from `OPERATIONS_SCHEMA`; its `tool` field is
  the count authority. Compatibility functions and dispatch plumbing are
  inventoried separately rather than double-counted as additional operations.
- Test counts include files named `test_*.py`, exclude macOS `._*` AppleDouble
  files, and count `tests/` plus all three eval-harness generations.
- Generated `web/dist`, caches, captured eval results, and AppleDouble files
  are not product components and are excluded.

| Surface | Count at baseline |
|---|---:|
| SQL-declared table names | 94 |
| Migration files | 51 |
| REST route modules | 38 |
| REST endpoints in route modules | 230 |
| Typed MCP operations | 152 (68 query, 84 execute) |
| Model modules, excluding `__init__.py` | 25 |
| Service modules, excluding `__init__.py` | 56 |
| Python tests in `tests/` | 218 |
| Eval-harness Python tests | 14 |
| Web page modules | 16 (17 route entries) |
| Web source files | 80 |
| Mirrored role-skill families | 5 (`brain`, `executor`, `pi`, `writer`, `mcp-credentials`) |
| Python package console scripts | 2 |

### Contract-count finding

`OPERATIONS_SCHEMA` contains 152 callable typed operations: 68
`rka_query` branches and 84 `rka_execute` branches. The active instructions in
`rka/mcp/server.py` agree. `CLAUDE.md` still says 150 (67 + 83), while
`.claude-plugin/marketplace.json` advertises an older 109-operation surface.
Disposition: `core`. Recommendation: make one generated contract-count test
and use its output in release/plugin documentation during E2.

## 3. Database tables and migrations

### 3.1 Table inventory

The following 94 names cover every explicit table declaration.

| Disposition | Count | Tables | Reason / next action |
|---|---:|---|---|
| `core` | 57 | `artifacts`, `audit_log`, `bootstrap_log`, `calibration_outcomes`, `change_events`, `checkpoints`, `claim_edges`, `claim_evidence_relations`, `claim_scope_versions`, `claims`, `context_snapshots`, `decision_options`, `decisions`, `embedding_metadata`, `entity_links`, `entity_topics`, `events`, `evidence_clusters`, `evidence_locators`, `experiment_observations`, `experiment_plan_versions`, `experiment_run_events`, `experiment_runs`, `experiments`, `figures`, `fts_claims`, `fts_clusters`, `fts_decisions`, `fts_journal`, `fts_literature`, `fts_missions`, `graph_views`, `hook_executions`, `hooks`, `interpretation_candidate_hints`, `interpretation_candidates`, `interpretation_promotions`, `interpretation_review_events`, `jobs`, `journal`, `keynodes`, `kv_store`, `literature`, `missions`, `project_deletion_authorizations`, `project_states`, `projects`, `review_queue`, `schema_migrations`, `tags`, `topics`, `vec_artifacts`, `vec_claims`, `vec_decisions`, `vec_journal`, `vec_literature`, `vec_missions` | Canonical research knowledge, evidence, provenance, retrieval, integrity, async Core jobs, and generic Core lifecycle hooks. |
| `writer-legacy-export` | 29 | `manuscript_checkpoints`, `manuscript_claim_evidence`, `manuscript_claim_ratifications`, `manuscript_claim_units`, `manuscript_claim_verification_attestations`, `manuscript_claim_versions`, `manuscript_claims`, `manuscript_evaluation_events`, `manuscript_migration_issues`, `manuscript_planning_artifact_versions`, `manuscript_planning_artifacts`, `manuscript_planning_branch_events`, `manuscript_planning_branches`, `manuscript_planning_evidence_bindings`, `manuscript_planning_promotion_events`, `manuscript_reference_members`, `manuscript_source_events`, `manuscript_source_proposals`, `manuscript_unit_citations`, `manuscript_unit_evidence`, `manuscript_unit_outline_profiles`, `manuscript_units`, `manuscripts`, `reference_validation_attestations`, `reference_validation_migration_issues`, `semantic_patch_context_manifests`, `semantic_patch_proposal_events`, `semantic_patch_proposals`, `semantic_patch_provider_events` | Preserve IDs, revisions, ratifications, references, ledgers, and checksums for export to Writer staging. No new schema features in Core. |
| `core-legacy` | 7 | `project_state`, `journal_v2`, `events_v2`, `checkpoints_v2`, `exploration_summaries`, `qa_sessions`, `qa_logs` | The singleton/project migration remnants and old LLM summary/Q&A records remain readable for compatibility. `*_v2` names are transient migration tables and must never become public entities. |
| `agentic` | 1 | `brain_notifications` | The queue is named for and consumed by the orchestration role. Migrate still-actionable notifications or explicitly expire them before removing the Core table; Core keeps generic hooks and hook-execution audit. |

`project_deletion_authorizations` is classified `core`, despite first appearing
in a manuscript migration, because Core claim-scope, interpretation, and
experiment immutability triggers now depend on it. Its API should be made a
generic integrity primitive before the Writer export is removed.

### 3.2 Migration-family inventory

All migration files remain in Core history so existing databases can upgrade.
Disposition controls active ownership and future feature work, not whether a
historical SQL file is deleted.

| Files | Count | Disposition | Scope |
|---|---:|---|---|
| `001`--`031` | 31 | `core` | Artifacts, retrieval, multi-project scoping, jobs, claims/clusters, temporal state, hooks, decisions, Zotero, review/freshness, and claim evidence status. |
| `032`--`034` | 3 | `writer-legacy-export` | Reference validation, native manuscript aggregate, and legacy manuscript backfill. |
| `035` | 1 | `core` | Generic monotonic semantic change cursor. Writer-specific impact projection is not part of this ownership. |
| `036` | 1 | `writer-legacy-export` | Async manuscript-reference validation. |
| `037` | 1 | `core` | Generic Core job lease fencing. |
| `038`--`039` | 2 | `writer-legacy-export` | Reference manifest and immutable Writer ledgers. Before removing active Writer use, preserve the generic `project_deletion_authorizations` primitive in Core. |
| `040`--`042` | 3 | `core` | Interpretation staging, claim-scope contracts, and experiment evidence substrate. |
| `043`--`050` | 8 | `writer-legacy-export` | Planning, semantic proposals, promotions, evaluation ledger, outline, academic-writing semantics, and source synchronization. |
| `051` | 1 | `core` | Project-scoped tag primary key and change events. |

Totals: 37 `core` migrations and 14 `writer-legacy-export` migrations.

## 4. REST API ownership

The endpoint count in this table is exact and sums to 230. Mixed modules are
split by endpoint so each family has one disposition.

| Route module / endpoint family | Endpoints | Disposition | Extraction rule |
|---|---:|---|---|
| `academic.py` | 5 | `core` | BibTeX/document ingestion and literature metadata. |
| `artifacts.py` | 6 | `core` | Research artifacts and figures. |
| `audit.py` | 2 | `core` | Core audit log and counts. |
| `changes.py`: `/changes` | 1 | `core` | Generic project change cursor. |
| `changes.py`: `/manuscripts/{id}/impact` | 1 | `writer` | Reimplement in Writer using Core `changes_since` and Writer-owned bindings. |
| `checkpoints.py` | 4 | `core` | Durable research checkpoints, not agent runtime checkpoints. |
| `claims.py` | 7 | `core` | Claims, scope versions, and claim edges. |
| `clusters.py` | 4 | `core` | Evidence clusters. |
| `config.py` | 5 | `core` | Embedding configuration and re-embedding lifecycle. |
| `context.py`: context + eviction | 2 | `core` | Deterministic context assembly and rule-based archival proposal. |
| `context.py`: `/summarize` | 1 | `agentic` | Model-driven synthesis moves behind an Agentic client of Core. |
| `decisions.py` | 20 | `core` | Research decisions, options, supersession, PI selection, and outcomes. |
| `enrich.py` | 1 | `agentic` | LLM-driven semantic linking becomes an Agentic workflow using public Core mutations. |
| `entities.py` | 1 | `core` | Bounded Core entity resolution. |
| `events.py` | 1 | `core` | Durable research event log. |
| `experiments.py` | 13 | `core` | Scientific plans/runs/observations/evidence remain canonical; actual execution is Agentic. |
| `graph.py` | 8 | `core` | Graph reads, refresh, traversal, timeline, and report context. |
| `hooks.py`: hook CRUD, executions, fire | 8 | `core` | Generic lifecycle integration and execution audit. |
| `hooks.py`: notification list + clear | 2 | `agentic` | Move with the Brain notification queue. |
| `interpretations.py` | 5 | `core` | Auditable staging and promotion into canonical knowledge. |
| `literature.py` | 5 | `core` | Literature registry and Zotero binding. |
| `llm.py` | 4 | `agentic` | Provider/model configuration and probing are orchestration concerns. |
| `maintenance.py` | 3 | `core` | Backlog, summary, and research-health checks. |
| `manuscript_sources.py` | 7 | `writer` | Writer-owned source snapshots and proposals. |
| `manuscripts.py` | 20 | `writer` | Active manuscript aggregate, spine, outline, checkpoints, and validation API. |
| `missions.py` | 6 | `core` | Durable mission objective/report; Agentic owns execution state. |
| `notes.py` | 4 | `core` | Journal create/read/update. |
| `onboarding.py` | 1 | `core` | Core client onboarding; remove role-specific Agentic prose from its template. |
| `planning.py` | 17 | `writer` | Writer planning branches, contributions, evaluation mapping, and outline proposals. |
| `project.py` | 10 | `core` | Projects, capabilities, status, import/export, and deletion. |
| `research_map.py` | 4 | `core` | Research questions, clusters, and claim navigation. |
| `researcher_tools.py` | 10 | `core` | Evidence assembly, cluster lifecycle, RQ advancement, freshness, and integrity. |
| `review_queue.py` | 4 | `core` | Canonical interpretation/review queue. |
| `search.py` | 1 | `core` | Project-scoped hybrid search. |
| `semantic_patches.py` | 9 | `writer` | Writer semantic edits and LM Studio proposal path. |
| `summary.py`: generate + ask | 2 | `agentic` | LLM execution moves to Agentic. |
| `summary.py`: list/get/bless + Q&A history/verify | 6 | `core-legacy` | Read historical records during compatibility; do not add new Core Q&A features. |
| `tags.py` | 1 | `core` | Project-scoped research tags. |
| `topics.py` | 6 | `core` | Research topics and hierarchy. |
| `verification.py` | 5 | `core` | Provenance, mission guard, as-of belief, and staleness. |
| `workspace.py` | 5 | `core` | Workspace discovery/ingestion into research knowledge. |
| `zotero_config.py` | 3 | `core` | Literature connector configuration. |

Disposition totals: 160 `core`, 54 `writer`, 10 `agentic`, and 6
`core-legacy` endpoints.

The `/api/health` route in `rka/api/app.py` is `core`. The SPA fallback is
`core` infrastructure; after extraction it serves only the minimal Core UI.

## 5. MCP ownership

### 5.1 Typed operation inventory

| Operation family | Count | Disposition | Operations |
|---|---:|---|---|
| Core/session/capabilities | 11 | `core` | `status`, `context`, `search`, `entity`, `resolve_entities`, `changes_since`, `changelog`, `update_status`, `bulk_update`, `list_projects`, `health` |
| Project creation | 1 | `core` | `create_project` |
| Journal/ingestion | 5 | `core` | `journal`, `record_note`, `ingest_document`, `update_note`, `batch_import` |
| Decisions/calibration | 10 | `core` | `decision_tree`, `record_decision`, `update_decision`, `orphan_supersedes`, `link_supersession`, `supersede_decision`, `present_decision`, `record_pi_selection`, `record_outcome`, `calibration_metrics` |
| Literature | 7 | `core` | `literature`, `record_literature`, `update_literature`, `import_bibtex`, `enrich_doi`, `link_literature_to_zotero`, `process_paper` |
| Missions/checkpoints | 13 | `core` | `mission`, `report`, `mission_guard`, `create_mission`, `update_mission`, `update_mission_status`, `submit_report`, `advance_rq`, `checkpoints`, `submit_checkpoint`, `resolve_checkpoint`, `create_gate`, `evaluate_gate` |
| Claims/research map/review | 19 | `core` | `research_map`, `review_queue`, `clusters`, `claims`, `claim_scope`, `interpretation_candidates`, `evidence`, `extract_claims`, `create_interpretation_candidate`, `add_interpretation_hint`, `triage_interpretation_candidate`, `set_claim_scope`, `review_claims`, `create_cluster`, `assign_claims_to_cluster`, `split_cluster`, `merge_clusters`, `review_cluster`, `resolve_contradiction` |
| Experiments | 10 | `core` | `experiments`, `experiment_runs`, `experiment_observations`, `create_experiment`, `append_experiment_plan`, `transition_experiment`, `create_experiment_run`, `transition_experiment_run`, `record_experiment_observation`, `add_evidence_locator` |
| Graph/provenance | 9 | `core` | `graph`, `ego_graph`, `graph_stats`, `graph_mermaid`, `provenance`, `multi_hop`, `collect_report_context`, `staleness_impact`, `belief_as_of` |
| Maintenance | 7 | `core` | `freshness`, `contradictions`, `integrity`, `pending_maintenance`, `flag_stale`, `eviction_sweep`, `bootstrap_review` |
| Workspace | 4 | `core` | `workspace_tree`, `workspace_scan`, `bootstrap_workspace`, `scan_workspace` |
| Hooks | 6 | `core` | `hooks`, `hook_executions`, `hook_add`, `hook_enable`, `hook_disable`, `hook_delete` |
| Manuscript | 19 | `writer` | `manuscript`, `manuscript_reference_manifest`, `manuscript_context`, `manuscript_readiness`, `manuscript_spine`, `manuscript_outline`, `manuscript_writing_candidates`, `manuscript_impact`, `register_manuscript`, `create_manuscript`, `update_manuscript`, `upsert_argument_spine`, `replace_manuscript_reference_manifest`, `ratify_manuscript_claim`, `transition_manuscript_phase`, `create_manuscript_checkpoint`, `resolve_manuscript_checkpoint`, `record_verification_attestation`, `prepare_manuscript_outline_proposal` |
| Manuscript planning | 16 | `writer` | `planning_branches`, `planning_resume`, `planning_compare`, `planning_artifact_versions`, `planning_argument_workflow`, `planning_promotions`, `planning_evaluation_workflow`, `planning_evaluation_events`, `create_planning_branch`, `transition_planning_branch`, `append_planning_artifact_version`, `promote_planning_rq`, `prepare_planning_contribution`, `ratify_planning_contribution`, `create_planning_evaluation_mission`, `prepare_planning_evaluation_result` |
| Semantic patches | 7 | `writer` | `semantic_patch_proposals`, `semantic_patch_schema`, `prepare_semantic_patch_context`, `create_semantic_patch_proposal`, `apply_semantic_patch_proposal`, `reject_semantic_patch_proposal`, `generate_lm_studio_semantic_patch` |
| Citation validation | 2 | `writer` | `reference_validation_status`, `validate_reference` |
| Model-driven synthesis/notification/runtime | 5 | `agentic` | `summarize`, `generate_summary`, `brain_notifications`, `brain_notifications_clear`, `session_digest` |
| Obsolete session reset | 1 | `core-legacy` | `reset_session` |

Totals: 102 `core`, 44 `writer`, 5 `agentic`, and 1 `core-legacy`.

### 5.2 MCP transport and compatibility surface

| Component | Disposition | Action |
|---|---|---|
| `rka_query`, `rka_execute`, `rka_describe` | `core` | Keep the dispatch pattern; remove Writer/Agentic branches from Core only after clients pass E2 contracts. |
| `rka_load_tools`, `rka_help`, deferred per-tool wrappers | `core-legacy` | Preserve through the final 2.x compatibility release; Core 3.0 may remove wrappers not needed by supported clients. |
| `rka_list_skills`, `rka_read_skill`, `rka_start_session` | `core` | Keep the adapter mechanism but reduce Core payloads to the thin Core-usage skill. Writer and Agentic publish their own skills. |
| Six MCP prompts in `server.py` | `agentic` | Role/decision/execution prompts move with Agentic; Core retains only neutral API-usage instructions. |
| `operation_args.py`, `operation_args_batch_c.py`, `_enums.py`, `operations_schema.py`, `verb_dispatch.py` | `core` | Split generated/curated Writer and Agentic branches during E2; then publish Core's contract snapshot for downstream generation. |

Legacy functions in `server.py` follow the disposition of their corresponding
typed operation and are not a second authority.

## 6. Models and services

### 6.1 Model modules

| Modules | Count | Disposition |
|---|---:|---|
| `audit`, `calibration`, `checkpoint`, `claim`, `context`, `decision`, `decision_option`, `event`, `experiment`, `hooks`, `interpretation`, `journal`, `knowledge_pack`, `literature`, `mission`, `project`, `review_queue`, `topic`, `workspace` | 19 | `core` |
| `manuscript_native`, `manuscript_source`, `outline`, `planning`, `reference_validation`, `semantic_patch` | 6 | `writer` |

`knowledge_pack` is classified `core`, but its Writer record definitions must
move into the legacy Writer exporter/importer rather than remain in the Core
pack schema indefinitely.

### 6.2 Service modules

| Modules | Count | Disposition |
|---|---:|---|
| `academic`, `admin_repair`, `artifacts`, `audit`, `backfill`, `base`, `calibration`, `change_tracking`, `checkpoints`, `claims`, `classify`, `clusters`, `context`, `decision_options`, `decisions`, `embedding_backfill`, `embedding_config`, `embedding_reshape`, `entity_resolver`, `events`, `experiments`, `graph`, `hook_dispatcher`, `hooks_service`, `interpretation`, `jobs`, `knowledge_pack`, `literature`, `maintenance`, `missions`, `notes`, `onboarding`, `pareto`, `project`, `reindex`, `rendering`, `research_map`, `researcher_tools`, `review_queue`, `search`, `topics`, `verification`, `worker`, `workspace`, `zotero_config`, `zotero_linker` | 46 | `core` |
| `manuscript`, `manuscript_native`, `manuscript_source`, `outline`, `outline_integrity`, `planning`, `reference_validation`, `semantic_patch`, `lm_studio_proposals` | 9 | `writer` |
| `summary` | 1 | `agentic` |

Required splits before extraction:

- `context` keeps deterministic retrieval in Core; its LLM summarization path
  moves to Agentic.
- `worker` keeps Core import/embedding jobs; reference-validation jobs move to
  Writer.
- `knowledge_pack` keeps Core research records; Writer rows become the
  versioned legacy export payload.
- `summary` moves its generation logic to Agentic, while old summary/Q&A rows
  remain `core-legacy` data until an explicit retention decision.

The provider modules `rka/infra/llm.py` and `rka/infra/llm_models.py` are
`agentic`; database/files/IDs and embedding infrastructure are `core`.

## 7. Skills, plugin, and package entry points

### 7.1 Skill and plugin inventory

The same role material is currently mirrored under `rka/skills/` and
`plugin/skills/`. Each row applies to both copies.

| Skill / plugin component | Disposition | Action |
|---|---|---|
| `brain`, `executor`, `pi` | `agentic` | Extract role policy and workflows to the Agentic plugin. |
| `writer` and all references, venue registry, scripts, templates, and Writer MCP tools | `writer` | Extract with history to Writer and retain its human-writing-quality tests. |
| `mcp-credentials` | `core` | Keep connector credentials needed by Core literature/retrieval integrations; remove provider credentials used only by downstream products. |
| `rka/skills/SKILL.md` umbrella | `core` | Replace role router with a small Core usage/retrieval/provenance guide. |
| `plugin/.claude-plugin/plugin.json`, `.mcp.json`, bridge, SessionStart health hook | `core` | Keep as the Core connector plugin and remove Writer/Agentic claims after their plugins exist. |
| Commands `rka-status`, `rka-search`, `rka-pending`, `rka-setup-claude-desktop` | `core` | Keep with the Core connector. |
| Command `rka-set-project` | `core-legacy` | It is already a deprecated no-op; remove after supported clients use explicit `project_id`. |
| Command and helper `rka-start-manuscript` | `writer` | Move to Writer. |
| Marketplace entry `.claude-plugin/marketplace.json` | `core` | Continue distributing Core only; update stale operation and skill counts. Writer and Agentic get their own manifests. |

Do not keep two manually edited skill sources after extraction. Each target
repository owns one source tree and generates or verifies its packaged plugin
copy in CI.

### 7.2 Package and process entry points

| Entry point | Disposition | Action |
|---|---|---|
| Console script `rka = rka.cli:main` | `core` | Retain Core serve/MCP/worker/status/backup/migrate/admin/credential commands. |
| `rka writer ...` subcommand group | `writer` | Move to Writer CLI and remove its registration from Core after compatibility. |
| Console script `rka-writer-tools` | `writer` | Move unchanged in responsibility, then version independently. |
| `rka.api.app:app`, `rka serve`, Docker `CMD`, Compose `rka` service | `core` | Core REST and minimal UI runtime. |
| `rka mcp` | `core` | Core agent-facing connector. |
| `rka worker` | `core` | Retain Core jobs only; Writer validation workers move out. |
| `web/src/main.tsx` SPA | `core` | Remains Core shell; extract Workbench routes/components and split mixed API types. |
| `scripts/rka_mcp_oauth_proxy.py`, `scripts/tunnel.sh` | `core` | Core HTTP MCP/ChatGPT connector deployment. |
| `scripts/sanitize_knowledge_pack.py` | `core` | Core pack integrity utility; add Writer export sanitization in Writer, not here. |

The `writer-tools` optional dependency group is `writer`. The general `llm`
provider dependencies become `agentic`, except embeddings (`fastembed`,
`sqlite-vec`) which remain `core`. `academic`, `workspace`, and `dev` remain
Core groups after Writer-only packages and tests move.

## 8. Test ownership

There are 232 Python test files: 218 under `tests/` and 14 in the eval
harness. Every file receives a disposition by the rules below.

| Test set | Count | Disposition |
|---|---:|---|
| All tests not named in the following rows | 163 | `core` |
| `tests/skills/writer/test_*.py` | 30 | `writer` |
| Root `tests/test_manuscript_native_models.py` | 1 | `writer` |
| API: `test_change_tracking_routes`, `test_manuscript_planning`, `test_manuscript_sources`, `test_native_manuscripts`, `test_reference_validation_attestations`, `test_semantic_patches` | 6 | `writer` |
| DB: migrations `032`, `033`, `034`, `036`, `038`, `039`, `043`, `044`, `047`, `048`, `049`, `050` | 12 | `writer` |
| MCP: `test_manuscript_planning`, `test_native_manuscript_operations`, `test_reference_validation_attestations` | 3 | `writer` |
| Services: `test_async_reference_validation`, `test_evaluation_contract`, `test_knowledge_pack_native`, `test_knowledge_pack_planning`, `test_knowledge_pack_semantic_patch`, `test_manuscript_planning`, `test_manuscript_project_scope`, `test_manuscript_source`, `test_native_manuscript_service`, `test_outline`, `test_reference_validation_attestations`, `test_semantic_patch` | 12 | `writer` |
| `eval-harness/v3/tests/test_writing_metrics.py` | 1 | `writer` |
| API `test_llm_health`, infra `test_llm_call_is_bounded`, services `test_llm_failure_is_visible` and `test_summary_qa` | 4 | `agentic` |
| `eval-harness/v3/tests/test_writing_metrics.py` is already counted above; no additional Agentic eval test exists on `origin/main` | 0 | `agentic` |

The table totals 232: 163 `core`, 65 `writer`, and 4 `agentic`.

Several `core` files are mixed integration tests and must be split rather than
copied wholesale: `test_knowledge_pack.py`, `test_project.py`,
`test_update_scope_guards.py`, `test_app_lifespan.py`,
`test_skill_adapter_tools.py`, and `test_skills_packaging.py`. Core retains the
Core assertions; Writer or Agentic receives the downstream scenarios.

`eval-harness/`, `v2`, and the v3 retention/currency/tracing/self-study suites
are `core`. `eval-harness/v3/writer/` and its writing metrics are `writer`.
Captured results remain historical evidence in their owning repository but
are not executable product code.

## 9. Web UI ownership

### 9.1 Pages and routes

| Pages/routes | Count | Disposition |
|---|---:|---|
| `Dashboard`, `Journal`, `Decisions`, `Literature`, `Missions`, `Timeline`, `KnowledgeGraph`, `ResearchMap`, `InterpretationStaging`, `ClaimScopeReview`, `ResearchHealth`, `ReportContext`, `AuditLog`, `ContextInspector`, `Settings` | 15 page modules / 15 routes | `core` |
| `ManuscriptWorkbench` at `/workbench` and `/manuscripts/:manuscriptId/workbench` | 1 page module / 2 routes | `writer` |

`Settings` remains `core`, but its server-side LLM provider controls move to
Agentic and any LM Studio Workbench controls move to Writer.

### 9.2 Components, hooks, and API client

| Component family | Disposition | Action |
|---|---|---|
| `components/workbench/*` (9 files) | `writer` | Extract with the Workbench page. |
| `useManuscriptOutline`, `useManuscriptSources`, `useManuscriptWorkbench`, `usePlanningBranches`, `useSemanticPatches` | `writer` | Extract with Writer API bindings. |
| Remaining layout/shared/UI components, project provider, and Core hooks | `core` | Keep minimal research-record UI. |
| `api/client.ts`, `api/types.ts` | `core` | Split Writer and provider-specific methods/types into generated downstream clients; Core file retains only the Core OpenAPI surface. |
| Sidebar/header navigation | `core` | Remove Workbench navigation after Writer has its own entry point. |

## 10. Major directory and documentation disposition

| Current area | Disposition | Boundary action |
|---|---|---|
| `rka/db`, Core models/services/routes, `rka/infra` except LLM provider modules | `core` | Harden and publish stable contracts. |
| `rka/skills/writer`, Writer models/services/routes and `rka/cli_writer.py` | `writer` | Extract after E2. |
| `rka/skills/{brain,executor,pi}` and LLM-provider modules | `agentic` | Extract with the agentic branch runtime after E2. |
| `plugin/` | `core` | Split role skills/commands; retain connector shell. |
| `web/` | `core` | Extract Workbench page/components/hooks; retain maintenance UI. |
| `eval-harness/` | `core` | Extract only `v3/writer`; keep retrieval/reliability evaluation. |
| `tests/` | `core` | Apply the exact test split in section 8. |
| `examples/` | `core` | Knowledge-pack example remains Core; do not embed manuscript-only fixtures in future packs. |
| `scripts/` | `core` | Connector/tunnel and Core pack sanitation. |
| `.github/workflows/` | `core` | Core CI remains; downstream repositories create independent CI rather than importing Core workflow internals. |
| `docs/adr/0001`, `0005`--`0011`; Writer plans/specs/walkthroughs | `writer` | Preserve history and cross-link from Core's migration docs. |
| `docs/adr/0002`--`0004`; Core architecture/manual/connector/retrieval docs | `core` | Remain authoritative for Core. |
| `docs/adr/0012`, ecosystem roadmap/slate/separation documents | `core` | Remain in Core as the ecosystem's origin decision record; downstream repos link back. |
| `docs/paper/` | `core-legacy` | Historical project papers are not product runtime; retain until an archival policy is approved. |
| `docs/archive/` | `core-legacy` | Preserve repository history; do not move as active product documentation. |
| Root Docker/Compose/install/user docs | `core` | Remove Writer/Agentic setup only after replacements exist. |

There is no `orchestrator/` directory on this `origin/main` baseline. Its actual
runtime must be inventoried from the `agentic` branch during E3 and cannot be
assumed to match the role skills currently on main.

## 11. Resolved ambiguities and required refactors

These cases looked cross-owned in the current monorepo. E0 resolves each to one
authority and records the work needed to make that authority real.

1. **Core is more than journal CRUD.** Claims, evidence clusters, RQs,
   interpretations, experiment evidence, artifacts, freshness, provenance,
   graph retrieval, and change history are `core`.
2. **Mission versus agent run.** Mission objective, status, checkpoint, and
   final report are `core`; scheduler state, model transcript, retries,
   interrupts, and resumable runtime checkpoints are `agentic`.
3. **Experiment run versus execution runtime.** A reviewed plan, run identity,
   status transition, observation, and evidence locator are durable science and
   therefore `core`. Commands, environments, queues, and retry machinery used
   to execute them are `agentic`.
4. **Change cursor versus Writer impact.** `change_events` and `/changes` are
   `core`; the projection from Core changes to affected manuscript units is
   `writer`.
5. **Knowledge packs.** The Core pack contains canonical research knowledge.
   Existing manuscript tables are `writer-legacy-export`; future Writer state
   has its own export/import format linked by Core IDs and hashes.
6. **Reference validation.** Literature identity and metadata remain `core`.
   Citation/manuscript-reference attestation and readiness are `writer`.
7. **Hooks, jobs, and Brain notifications.** Generic Core event hooks, hook
   audit, and Core job leases remain `core`; the Brain notification queue is
   `agentic`. No generic Core job may become an agent-run scheduler.
8. **LLM and embeddings.** Model-provider probing, LLM summarization, and
   auto-enrichment are `agentic`; embedding generation and vector indexes used
   for deterministic Core retrieval are `core`.
9. **Historical summary/Q&A data.** Old `exploration_summaries`, `qa_sessions`,
   and `qa_logs` are `core-legacy`, while new model-driven synthesis is
   `agentic`. Decide retention/export before removing the legacy read surface.
10. **Dual skill mirrors.** Product ownership follows the skill, not its
    current copy. Extraction must establish one source-of-truth per repository
    and CI verification of packaged output.

## 12. E0 extraction blockers and acceptance checks

The inventory removes authority ambiguity, but the following refactors are
prerequisites for code movement:

1. Add a contract-generated count check and correct the 152/150/109
   documentation drift.
2. Split mixed `context`, `changes`, `hooks`, `summary`, `worker`,
   `knowledge_pack`, Settings, MCP-schema, and API-client modules.
3. Define the Writer legacy export schema for the 29 Writer tables, including
   IDs, revisions, immutable ledgers, reference bindings, and checksums.
4. Make `project_deletion_authorizations` an explicit generic Core integrity
   primitive instead of an accidental dependency introduced by Writer.
5. Inventory the `agentic` branch separately before E3 extraction.
6. Keep all 51 historical migrations in Core until the oldest supported
   database can upgrade and Writer export passes on a disposable copy.

The inventory is complete for `origin/main` when reviewers confirm the counts,
the six dispositions, and the ten resolved boundary decisions above. It does
not authorize creating repositories, moving code, changing a live database,
or deleting compatibility state.
