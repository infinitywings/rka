"""v2.7.0 — Pydantic discriminated-union argument models for rka_query / rka_execute.

This module is the **typed surface** for the v2.7.0 always-on verbs. Each
operation gets its own Pydantic ``Args`` model that:

1. **Locks enums at the JSON Schema layer.** Every per-operation enum field
   uses an ``Annotated[Literal[...]]`` alias imported from ``rka.mcp._enums``.
   FastMCP renders the model as ``oneOf`` with per-branch ``enum: [...]``
   arrays — the LLM cannot emit a bad enum value (the tool surface rejects it
   pre-dispatch).
2. **Locks required fields per operation.** Each branch's required-fields
   array is explicit; the LLM-emission-time gap that Run-5 exploited
   (``confidence='confirmed'``, ``content=`` vs ``description=``) is closed.
3. **Locks cross-field invariants** via ``model_validator(mode='after')``
   for the empirically-observed Brain hallucination + omission classes
   (``related_journal=[]``, ``source='pi'`` without ``verbatim_input``,
   missing ``motivated_by_decision``).

Naming convention: ``{operation_pascal_case}Args``. For query ops whose verb
name collides with a write sibling (``mission``, ``manuscript``), the model
is prefixed ``Query...`` to disambiguate (``QueryMissionArgs`` vs
``CreateMissionArgs``).

Discriminator: each model declares
``operation: Literal['<op>'] = '<op>'`` — FastMCP keys the discriminated
union by this field.

Configuration: every model sets
``model_config = ConfigDict(extra='forbid', use_enum_values=True)`` so
unknown kwargs are rejected at the schema layer (closes the silent-typo
class identified in the v2.7.0 pre-mortem).

Source of truth (drift-detection):
  - ``rka/mcp/operations_schema.py`` ``OPERATIONS_SCHEMA`` — canonical
    required/optional/enum lists per operation.
  - ``rka/mcp/_enums.py`` — module-level Literal aliases.
  - ``rka/models/*.py`` — service-layer Pydantic shapes.

The lock-tests in ``tests/test_mcp/test_v270_typed_args_lock.py`` pin each
model's field set against ``OPERATIONS_SCHEMA`` and assert each Literal in
each model is ``is`` the imported alias from ``_enums.py``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

# NOTE: enum aliases from ``rka.mcp._enums`` are imported on a per-batch
# basis. Batch A (query ops) doesn't directly type any enum field — query
# enums live inside the ``filters: dict[str, Any]`` payload. Batches B/C/D
# (write ops) add per-field Literal aliases. The lock-tests in
# ``tests/test_mcp/test_v270_typed_args_lock.py`` audit that each
# Annotated[Literal[...]] in a write model uses the imported alias.

# Batch D imports — claim/cluster review + maintenance enums.
from rka.mcp._enums import (  # noqa: E402  (intentional post-docstring batch import)
    ClusterConfLit,
    ConfidenceLit,
    EvidenceStatusLit,
    ReviewActionLit,
    StalenessLit,
)

# Batch B imports — Record/Create write op enums. ConfidenceLit / ClusterConfLit
# are re-imported in their own block for batch-locality reading even though
# Batch D's import above already pulled them; Python's import machinery
# deduplicates so this is no cost. The lock-tests audit per-model that each
# Annotated[Literal[...]] uses the imported alias.
from rka.mcp._enums import (  # noqa: E402, F811
    ClaimTypeLit,
    DecidedByLit,
    DecisionKindLit,
    GateTypeLit,
    ImportanceLit,
    IngestSourceLit,
    LitStatusLit,
    NoteTypeLit,
    SourceLit,
)

# Batch C imports — Update/Lifecycle/Submit enums.
from rka.mcp._enums import (  # noqa: E402, F811
    CheckpointResolvedByLit,
    ChkTypeLit,
    DecisionStatusLit,
    JournalStatusLit,
    MissionStatusLit,
    OutcomeLit,
    RecordedByLit,
    RQStatusLit,
    VerdictLit,
)

# Batch B extras — actor aliases for batch_import + hook_add (promoted
# from inline Literals to public aliases in Phase 3 so the drift-test
# infra catches future divergence).
from rka.mcp._enums import (  # noqa: E402, F811
    BatchImportActorLit,
    HookCreatedByLit,
)

# ---------------------------------------------------------------------------
# Shared base classes
# ---------------------------------------------------------------------------


class ProjectScopedArgs(BaseModel):
    """Base for project-scoped operations (the vast majority).

    Subclasses inherit ``project_id: str`` and the strict ``ConfigDict``.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    project_id: Annotated[
        str,
        Field(description="Project ID (prj_...). REQUIRED."),
    ]


class UnscopedArgs(BaseModel):
    """Base for operations that don't require a project_id.

    Used by ``list_projects``, ``health``, ``create_project``, ``reset_session``.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


# ---------------------------------------------------------------------------
# Reusable mixins (composed via multiple inheritance where appropriate)
# ---------------------------------------------------------------------------


class PaginatedFiltersMixin(BaseModel):
    """List-mode reads: optional ``limit`` + ``filters`` dict."""

    limit: Annotated[
        Optional[int],
        Field(default=None, description="Cap on result count."),
    ] = None
    filters: Annotated[
        Optional[dict[str, Any]],
        Field(default=None, description="Operation-specific filter dict."),
    ] = None


# =============================================================================
# Batch A — QUERY operations (38 models)
# =============================================================================

# ---------------------------------------------------------------------------
# Core read operations (status / context / search / entity)
# ---------------------------------------------------------------------------


class QueryStatusArgs(ProjectScopedArgs):
    """[ANY] Current phase, focus, blockers — the minimal session-start probe.

    Related: ``context``, ``pending_maintenance``, ``checkpoints``.
    """

    operation: Literal["status"] = "status"


class QueryContextArgs(ProjectScopedArgs):
    """[ANY] Load current project state + recent knowledge for a topic.

    Related: ``status``, ``summarize``, ``search``.
    """

    operation: Literal["context"] = "context"

    query: Annotated[
        Optional[str],
        Field(default=None, description="Optional topic to scope the context pull."),
    ] = None
    filters: Annotated[
        Optional[dict[str, Any]],
        Field(default=None, description="Optional filters (e.g. {'phase': str})."),
    ] = None
    options: Annotated[
        Optional[dict[str, Any]],
        Field(
            default=None,
            description="Optional options (e.g. {'depth': 'summary'|'detailed'}).",
        ),
    ] = None


class QuerySearchArgs(ProjectScopedArgs):
    """[ANY] Full-text + semantic search across journal/decision/literature/clusters.

    Pass 2-4 keyword terms; longer queries reduce recall.
    """

    operation: Literal["search"] = "search"

    query: Annotated[
        str,
        Field(description="Search query (2-4 keyword terms recommended)."),
    ]
    limit: Annotated[
        Optional[int],
        Field(default=None, description="Cap on result count (default 20)."),
    ] = None
    filters: Annotated[
        Optional[dict[str, Any]],
        Field(
            default=None,
            description=(
                "Optional filters (e.g. {'entity_types': ['decision', 'journal']})."
            ),
        ),
    ] = None


class QueryEntityArgs(ProjectScopedArgs):
    """[ANY] Fetch a single entity by ID (jrn_/dec_/lit_/mis_/clm_/ecl_/chk_).

    Entity prefix is auto-routed.
    """

    operation: Literal["entity"] = "entity"

    id: Annotated[
        str,
        Field(description="Entity ID (jrn_/dec_/lit_/mis_/clm_/ecl_/chk_)."),
    ]


# ---------------------------------------------------------------------------
# List-mode reads (journal / literature / mission / report / checkpoints)
# ---------------------------------------------------------------------------


class QueryJournalArgs(ProjectScopedArgs, PaginatedFiltersMixin):
    """[ANY] List journal entries (notes, logs, directives).

    Filter keys: ``type``, ``phase``, ``confidence``, ``status``, ``since``,
    ``source``, ``tags``.
    """

    operation: Literal["journal"] = "journal"


class QueryLiteratureArgs(ProjectScopedArgs, PaginatedFiltersMixin):
    """[ANY] List literature entries.

    Filter keys: ``status``, ``tag``.
    """

    operation: Literal["literature"] = "literature"

    query: Annotated[
        Optional[str],
        Field(default=None, description="Optional free-text search over literature."),
    ] = None


class QueryMissionArgs(ProjectScopedArgs):
    """[ANY] Fetch a specific mission (by ID) or the current active/pending mission.

    Omit ``id`` to auto-locate the most recent active or pending mission.
    """

    operation: Literal["mission"] = "mission"

    id: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Mission ID (mis_...). Omit to auto-locate the current "
                "active or pending mission."
            ),
        ),
    ] = None


class QueryReportArgs(ProjectScopedArgs):
    """[ANY] Fetch a mission's submitted report.

    ``id`` is the mission_id, NOT a report_id.
    """

    operation: Literal["report"] = "report"

    id: Annotated[
        str,
        Field(description="Mission ID (mis_...) whose report you want."),
    ]


class QueryCheckpointsArgs(ProjectScopedArgs):
    """[ANY] List checkpoints (default: open).

    Filter: ``{'status': 'open' | 'resolved' | 'all'}``.
    """

    operation: Literal["checkpoints"] = "checkpoints"

    filters: Annotated[
        Optional[dict[str, Any]],
        Field(
            default=None,
            description="Optional filters (e.g. {'status': 'open'}).",
        ),
    ] = None


# ---------------------------------------------------------------------------
# Decision / calibration / hooks / notifications
# ---------------------------------------------------------------------------


class QueryDecisionTreeArgs(ProjectScopedArgs):
    """[ANY] Render the decision tree, optionally rooted at a decision.

    Filter keys: ``phase``, ``active_only``.
    """

    operation: Literal["decision_tree"] = "decision_tree"

    id: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional root decision ID; omit for full project tree.",
        ),
    ] = None
    filters: Annotated[
        Optional[dict[str, Any]],
        Field(
            default=None,
            description="Optional filters (e.g. {'active_only': True, 'phase': '...'}).",
        ),
    ] = None


class QueryCalibrationMetricsArgs(ProjectScopedArgs):
    """[BRAIN] Aggregate calibration outcomes for decisions you've made.

    Related: ``record_outcome``.
    """

    operation: Literal["calibration_metrics"] = "calibration_metrics"


class QueryHooksArgs(ProjectScopedArgs):
    """[ANY] List configured hooks.

    Filter keys: ``event``, ``enabled_only``.
    """

    operation: Literal["hooks"] = "hooks"

    filters: Annotated[
        Optional[dict[str, Any]],
        Field(default=None, description="Optional filters."),
    ] = None


class QueryHookExecutionsArgs(ProjectScopedArgs, PaginatedFiltersMixin):
    """[ANY] Recent hook execution history.

    Filter keys: ``hook_id``, ``since``, ``status``.
    """

    operation: Literal["hook_executions"] = "hook_executions"


class QueryBrainNotificationsArgs(ProjectScopedArgs, PaginatedFiltersMixin):
    """[BRAIN] Notifications queued for the Brain.

    Filter keys: ``since``, ``include_cleared``.
    """

    operation: Literal["brain_notifications"] = "brain_notifications"


# ---------------------------------------------------------------------------
# Research map / review / claims / clusters / manuscript
# ---------------------------------------------------------------------------


class QueryResearchMapArgs(ProjectScopedArgs):
    """[ANY] Top-level research map: RQs -> clusters -> claims with synthesis."""

    operation: Literal["research_map"] = "research_map"


class QueryReviewQueueArgs(ProjectScopedArgs, PaginatedFiltersMixin):
    """[BRAIN] Pending review items (claims, clusters needing synthesis, etc.).

    Filter keys: ``status`` (``pending`` | ``reviewed`` | ``all``), ``target_type``.
    """

    operation: Literal["review_queue"] = "review_queue"


class QueryClustersArgs(ProjectScopedArgs, PaginatedFiltersMixin):
    """[ANY] List evidence clusters.

    Filter keys: ``research_question_id``, ``confidence``.
    """

    operation: Literal["clusters"] = "clusters"


class QueryClaimsArgs(ProjectScopedArgs, PaginatedFiltersMixin):
    """[ANY] List claims.

    Filter keys: ``source_entry_id``, ``cluster_id``, ``claim_type``,
    ``verified`` (source-grounding fidelity), ``evidence_status``
    (scientific evidence assessment), ``stale``.
    """

    operation: Literal["claims"] = "claims"


class QueryManuscriptArgs(ProjectScopedArgs):
    """[ANY] Fetch a registered manuscript."""

    operation: Literal["manuscript"] = "manuscript"

    id: Annotated[
        str,
        Field(description="Manuscript journal ID (jrn_...)."),
    ]


# ---------------------------------------------------------------------------
# Graph operations
# ---------------------------------------------------------------------------


class QueryGraphArgs(ProjectScopedArgs, PaginatedFiltersMixin):
    """[ANY] Subset of the research-knowledge graph (nodes + edges).

    Filter keys: ``include_types``, ``phase``.
    """

    operation: Literal["graph"] = "graph"


class QueryEgoGraphArgs(ProjectScopedArgs):
    """[ANY] Local neighborhood graph centered on one entity."""

    operation: Literal["ego_graph"] = "ego_graph"

    id: Annotated[
        str,
        Field(description="Center-entity ID."),
    ]
    filters: Annotated[
        Optional[dict[str, Any]],
        Field(
            default=None,
            description="Optional filters (e.g. {'depth': 1}).",
        ),
    ] = None


class QueryGraphStatsArgs(ProjectScopedArgs):
    """[ANY] Top-level node/edge counts."""

    operation: Literal["graph_stats"] = "graph_stats"


class QueryGraphMermaidArgs(ProjectScopedArgs):
    """[ANY] Render the decision tree as Mermaid graph syntax.

    Filter keys: ``phase``, ``active_only``.
    """

    operation: Literal["graph_mermaid"] = "graph_mermaid"

    filters: Annotated[
        Optional[dict[str, Any]],
        Field(default=None, description="Optional filters."),
    ] = None


class QueryProvenanceArgs(ProjectScopedArgs):
    """[ANY] Trace the reasoning chain that produced an entity.

    Filter keys: ``direction`` (``forward`` | ``backward`` | ``both``),
    ``max_depth``.
    """

    operation: Literal["provenance"] = "provenance"

    id: Annotated[
        str,
        Field(description="Entity ID whose provenance to trace."),
    ]
    filters: Annotated[
        Optional[dict[str, Any]],
        Field(default=None, description="Optional filters."),
    ] = None


class QueryMultiHopArgs(ProjectScopedArgs):
    """[BRAIN] Multi-hop graph retrieval seeded by query or explicit seed IDs.

    Pass ``filters.seeds=[...]`` to override the query-based seeding.
    """

    operation: Literal["multi_hop"] = "multi_hop"

    query: Annotated[
        str,
        Field(description="Seed query for multi-hop retrieval."),
    ]
    filters: Annotated[
        Optional[dict[str, Any]],
        Field(
            default=None,
            description=(
                "Optional filters (e.g. {'seeds': [...], 'max_depth': 3, "
                "'max_nodes': 50})."
            ),
        ),
    ] = None


class QueryCollectReportContextArgs(ProjectScopedArgs):
    """[ANY] Collect the node set relevant to a report described in prose.

    Composite retrieval for the "I want to write a report about X"
    workflow: seeds from every angle query, BFS-expands through the
    typed link graph, protects seeds from cap displacement, and tags
    every node with inclusion provenance (``included_via``).

    ALWAYS provide ``filters.angle_queries`` — 3-5 short (1-4 word)
    queries decomposing the description from different angles
    (components, bugs/fixes, decisions, evaluations). Paragraph-only
    seeding measured 0.32 mean cohort recall vs 0.80 for
    angle-decomposed retrieval (eval-v3).
    """

    operation: Literal["collect_report_context"] = "collect_report_context"

    query: Annotated[
        str,
        Field(description=(
            "The report description — the PI's prose paragraph describing "
            "what the report should cover."
        )),
    ]
    filters: Annotated[
        Optional[dict[str, Any]],
        Field(
            default=None,
            description=(
                "Optional filters: {'angle_queries': ['short query', ...], "
                "'max_depth': 2, 'max_nodes': 60, 'seed_limit': 8}. "
                "angle_queries is STRONGLY recommended."
            ),
        ),
    ] = None


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------


class QueryStalenessImpactArgs(ProjectScopedArgs):
    """[ANY] Downstream blast-radius of a stale (or about-to-be-stale) entity.

    Walks dependent-direction links only: everything whose reasoning rests
    on the entity. Use before/after a supersede or retraction.
    """

    operation: Literal["staleness_impact"] = "staleness_impact"

    id: Annotated[
        str,
        Field(description="Entity ID whose downstream impact to compute."),
    ]
    filters: Annotated[
        Optional[dict[str, Any]],
        Field(default=None, description="Optional filters: {'max_depth': 3}."),
    ] = None


class QueryMissionGuardArgs(ProjectScopedArgs):
    """[EXECUTOR] Negative knowledge relevant to a mission at pickup.

    Retracted/superseded findings and unresolved contradictions overlapping
    the mission objective: approaches already falsified or contested. Call
    alongside mission context at pickup.
    """

    operation: Literal["mission_guard"] = "mission_guard"

    id: Annotated[
        str,
        Field(description="Mission ID to guard."),
    ]


class QueryBeliefAsOfArgs(ProjectScopedArgs):
    """[ANY] Reconstruct the believed-current knowledge state at a past date.

    'What did we believe in March, and what changed since?' Supersession
    transitions are exact; retraction times are approximate (updated_at).
    """

    operation: Literal["belief_as_of"] = "belief_as_of"

    query: Annotated[
        str,
        Field(description="ISO date or timestamp, e.g. '2026-03-15'."),
    ]


class QuerySummarizeArgs(ProjectScopedArgs):
    """[ANY] Topic-scoped summarization across the knowledge graph.

    Filter keys: ``topic``, ``phase``, ``entity_ids``.
    """

    operation: Literal["summarize"] = "summarize"

    query: Annotated[
        Optional[str],
        Field(default=None, description="Optional topic query."),
    ] = None
    filters: Annotated[
        Optional[dict[str, Any]],
        Field(default=None, description="Optional filters."),
    ] = None


class QueryGenerateSummaryArgs(ProjectScopedArgs):
    """[ANY] Render a structured summary (project / mission / decision scope).

    Filter keys: ``scope_type`` (``project`` | ``mission`` | ``decision``),
    ``scope_id``, ``granularity`` (``paragraph`` | ``outline`` | ``bullet_list``).

    Note: v2.4.0 removed the LLM-driven path; this scope is a stub until
    re-wired through the orchestrator.
    """

    operation: Literal["generate_summary"] = "generate_summary"

    id: Annotated[
        Optional[str],
        Field(default=None, description="Optional scope-entity ID."),
    ] = None
    filters: Annotated[
        Optional[dict[str, Any]],
        Field(default=None, description="Optional filters."),
    ] = None


# ---------------------------------------------------------------------------
# Evidence / maintenance / freshness / contradictions
# ---------------------------------------------------------------------------


class QueryEvidenceArgs(ProjectScopedArgs):
    """[BRAIN] Assemble structured evidence supporting a research question.

    ``id`` is the research_question_id (stored as a decision id with
    kind=``research_question``).
    """

    operation: Literal["evidence"] = "evidence"

    id: Annotated[
        str,
        Field(description="Research question ID (dec_... with kind='research_question')."),
    ]
    filters: Annotated[
        Optional[dict[str, Any]],
        Field(
            default=None,
            description=(
                "Optional filters (e.g. {'format': "
                "'progress_report'|'briefing'|'audit'})."
            ),
        ),
    ] = None


class QueryFreshnessArgs(ProjectScopedArgs):
    """[BRAIN] Check freshness/staleness of claims and clusters.

    Filter keys: ``days_threshold``.
    """

    operation: Literal["freshness"] = "freshness"

    filters: Annotated[
        Optional[dict[str, Any]],
        Field(
            default=None,
            description="Optional filters (e.g. {'days_threshold': 30}).",
        ),
    ] = None


class QueryContradictionsArgs(ProjectScopedArgs):
    """[BRAIN] Detect contradicting evidence near a given entity.

    Filter keys: ``similarity_threshold``, ``max_results``.
    """

    operation: Literal["contradictions"] = "contradictions"

    id: Annotated[
        str,
        Field(description="Anchor entity ID for contradiction search."),
    ]
    filters: Annotated[
        Optional[dict[str, Any]],
        Field(default=None, description="Optional filters."),
    ] = None


class QueryIntegrityArgs(ProjectScopedArgs):
    """[BRAIN] Database integrity probe (orphans, broken links)."""

    operation: Literal["integrity"] = "integrity"


class QueryPendingMaintenanceArgs(ProjectScopedArgs):
    """[BRAIN] Provenance gaps, untagged entries, orphans, etc."""

    operation: Literal["pending_maintenance"] = "pending_maintenance"


# ---------------------------------------------------------------------------
# Changelog / workspace / bootstrap_review
# ---------------------------------------------------------------------------


class QueryChangelogArgs(ProjectScopedArgs):
    """[ANY] Project changelog since a given date.

    ``filters.since`` is REQUIRED (ISO8601 date string).
    """

    operation: Literal["changelog"] = "changelog"

    limit: Annotated[
        Optional[int],
        Field(default=None, description="Cap on result count (default 50)."),
    ] = None
    filters: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Required filter dict; MUST contain 'since' as an ISO8601 "
                "date string (e.g. {'since': '2026-05-01'})."
            ),
        ),
    ]

    @model_validator(mode="after")
    def _require_since(self) -> "QueryChangelogArgs":
        if self.filters is None or "since" not in self.filters:
            raise ValueError(
                "changelog requires filters.since as an ISO8601 date string"
            )
        since_val = self.filters["since"]
        if not isinstance(since_val, str) or not since_val.strip():
            raise ValueError(
                "changelog filters.since must be a non-empty ISO8601 string"
            )
        return self


class QueryBootstrapReviewArgs(ProjectScopedArgs):
    """[ANY] Review the proposed bootstrap result for a workspace scan.

    ``id`` is the scan_id (scn_...).
    """

    operation: Literal["bootstrap_review"] = "bootstrap_review"

    id: Annotated[
        str,
        Field(description="Scan ID (scn_...)."),
    ]


class QueryWorkspaceTreeArgs(ProjectScopedArgs):
    """[ANY] Read-only file-tree probe of a workspace folder.

    The ``folder_path`` lives in ``filters``; the optional ``max_depth`` is
    a top-level kwarg for ergonomic access.
    """

    operation: Literal["workspace_tree"] = "workspace_tree"

    filters: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Required filter dict; MUST contain 'folder_path' as a string. "
                "Optional 'max_depth' int."
            ),
        ),
    ]
    max_depth: Annotated[
        Optional[int],
        Field(default=None, description="Optional max recursion depth."),
    ] = None

    @model_validator(mode="after")
    def _require_folder_path(self) -> "QueryWorkspaceTreeArgs":
        if self.filters is None or "folder_path" not in self.filters:
            raise ValueError(
                "workspace_tree requires filters.folder_path as an absolute path"
            )
        fp = self.filters["folder_path"]
        if not isinstance(fp, str) or not fp.strip():
            raise ValueError(
                "workspace_tree filters.folder_path must be a non-empty string"
            )
        return self


class QueryWorkspaceScanArgs(ProjectScopedArgs):
    """[ANY] Deep workspace scan (full file contents for ingestion).

    The ``folder_path`` lives in ``filters``; ``ignore_patterns``,
    ``max_file_size_mb``, and ``use_llm`` are top-level optional kwargs.
    """

    operation: Literal["workspace_scan"] = "workspace_scan"

    filters: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Required filter dict; MUST contain 'folder_path' as a string."
            ),
        ),
    ]
    ignore_patterns: Annotated[
        Optional[list[str]],
        Field(default=None, description="Optional list of glob patterns to ignore."),
    ] = None
    max_file_size_mb: Annotated[
        Optional[int],
        Field(default=None, description="Optional max per-file size in MB."),
    ] = None
    use_llm: Annotated[
        Optional[bool],
        Field(default=None, description="Optional flag to enable LLM-assisted scan."),
    ] = None

    @model_validator(mode="after")
    def _require_folder_path(self) -> "QueryWorkspaceScanArgs":
        if self.filters is None or "folder_path" not in self.filters:
            raise ValueError(
                "workspace_scan requires filters.folder_path as an absolute path"
            )
        fp = self.filters["folder_path"]
        if not isinstance(fp, str) or not fp.strip():
            raise ValueError(
                "workspace_scan filters.folder_path must be a non-empty string"
            )
        return self


# ---------------------------------------------------------------------------
# Unscoped session operations (list_projects / health)
# ---------------------------------------------------------------------------


class QueryListProjectsArgs(UnscopedArgs):
    """[ANY] List all available projects (UNSCOPED — does not require project_id)."""

    operation: Literal["list_projects"] = "list_projects"


class QueryHealthArgs(UnscopedArgs):
    """[ANY] API health probe (UNSCOPED)."""

    operation: Literal["health"] = "health"


# ---------------------------------------------------------------------------
# Union (discriminated by `operation`)
# ---------------------------------------------------------------------------


QueryArgsUnion = Annotated[
    Union[
        # Core
        QueryStatusArgs,
        QueryContextArgs,
        QuerySearchArgs,
        QueryEntityArgs,
        # List-mode
        QueryJournalArgs,
        QueryLiteratureArgs,
        QueryMissionArgs,
        QueryReportArgs,
        QueryCheckpointsArgs,
        # Decision / calibration / hooks / notifications
        QueryDecisionTreeArgs,
        QueryCalibrationMetricsArgs,
        QueryHooksArgs,
        QueryHookExecutionsArgs,
        QueryBrainNotificationsArgs,
        # Research map / review / claims / clusters / manuscript
        QueryResearchMapArgs,
        QueryReviewQueueArgs,
        QueryClustersArgs,
        QueryClaimsArgs,
        QueryManuscriptArgs,
        # Graph
        QueryGraphArgs,
        QueryEgoGraphArgs,
        QueryGraphStatsArgs,
        QueryGraphMermaidArgs,
        QueryProvenanceArgs,
        QueryMultiHopArgs,
        QueryCollectReportContextArgs,
        QueryStalenessImpactArgs,
        QueryMissionGuardArgs,
        QueryBeliefAsOfArgs,
        # Summarization
        QuerySummarizeArgs,
        QueryGenerateSummaryArgs,
        # Evidence / maintenance
        QueryEvidenceArgs,
        QueryFreshnessArgs,
        QueryContradictionsArgs,
        QueryIntegrityArgs,
        QueryPendingMaintenanceArgs,
        # Changelog / workspace / bootstrap_review
        QueryChangelogArgs,
        QueryBootstrapReviewArgs,
        QueryWorkspaceTreeArgs,
        QueryWorkspaceScanArgs,
        # Unscoped session
        QueryListProjectsArgs,
        QueryHealthArgs,
    ],
    Field(discriminator="operation"),
]


# =============================================================================
# Batch B — RECORD/CREATE write operations (13 models)
# =============================================================================
#
# record_note, ingest_document, record_decision, record_literature,
# import_bibtex, batch_import, register_manuscript, create_mission,
# create_cluster, create_project, create_gate, hook_add, extract_claims.
#
# Provenance discipline (mirrors verb_dispatch.dispatch_record_note +
# dispatch_record_decision + dispatch_mission(action='create')) is
# encoded as Pydantic ``model_validator(mode='after')`` raisers:
#   - RecordNoteArgs: source='pi' -> verbatim_input required
#   - RecordDecisionArgs: related_journal min_length=1
#   - CreateMissionArgs: motivated_by_decision required (non-Optional)
#   - RecordLiteratureArgs: at least one of {title, doi} required
#   - ExtractClaimsArgs: claims min_length=1
#   - CreateGateArgs: deliverables + pass_criteria min_length=1


# --- journal --------------------------------------------------------------


class _NoteProvenance(BaseModel):
    """Nested provenance dict shape accepted by ``record_note`` /
    ``ingest_document`` per Graft A — flattened into the legacy REST
    call by the dispatcher.

    Fields mirror ``verb_dispatch._NOTE_PROVENANCE_KEYS``.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    related_decisions: Annotated[
        Optional[list[str]],
        Field(default=None, description="Decision IDs justifying this note."),
    ] = None
    related_literature: Annotated[
        Optional[list[str]],
        Field(default=None, description="Literature IDs cited by this note."),
    ] = None
    related_mission: Annotated[
        Optional[str],
        Field(default=None, description="Mission ID this note belongs to."),
    ] = None
    supersedes: Annotated[
        Optional[str],
        Field(default=None, description="Journal ID this note supersedes."),
    ] = None


class RecordNoteArgs(ProjectScopedArgs):
    """[ANY] RECORD a journal entry (note, log, directive).

    Phase-X²' rule: ``source='pi'`` REQUIRES ``verbatim_input``. The
    typed-args layer rejects calls without it pre-flight (PI provenance
    discipline — preserves PI's exact wording for intellectual attribution).

    Brain hallucination class closed: ``confidence='confirmed'`` is NOT
    in the allowed set; use one of
    {hypothesis, tested, verified, superseded, retracted}.
    """

    operation: Literal["record_note"] = "record_note"

    # Required body
    content: Annotated[
        str,
        Field(description="Journal entry body (PRIMARY field)."),
    ]

    # Optional enum-typed fields
    source: Annotated[
        SourceLit,
        Field(default="executor", description="Actor of record."),
    ] = "executor"
    type: Annotated[
        NoteTypeLit,
        Field(default="note", description="Journal entry type."),
    ] = "note"
    confidence: Annotated[
        ConfidenceLit,
        Field(default="hypothesis", description="Confidence level."),
    ] = "hypothesis"
    importance: Annotated[
        ImportanceLit,
        Field(default="normal", description="Importance level."),
    ] = "normal"

    # Optional provenance / metadata
    verbatim_input: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Verbatim PI wording. REQUIRED when source='pi' "
                "(preserves PI intellectual attribution)."
            ),
        ),
    ] = None
    phase: Annotated[
        Optional[str],
        Field(default=None, description="Project phase tag."),
    ] = None
    tags: Annotated[
        Optional[list[str]],
        Field(default=None, description="Free-form tags."),
    ] = None
    # Phase-X²' polish: surface the previously-hidden JournalEntryCreate
    # source fields through the typed-args layer so Brain can set them
    # explicitly instead of relying on REST-layer defaults.
    summary: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Optional short summary of the entry (matches "
                "rka/models/journal.py JournalEntryCreate.summary)."
            ),
        ),
    ] = None
    status: Annotated[
        Optional[JournalStatusLit],
        Field(
            default=None,
            description=(
                "Journal entry lifecycle status (draft|active|superseded|"
                "retracted). Defaults to 'active' at the REST layer when "
                "omitted; matches rka/db/schema.sql migration 009."
            ),
        ),
    ] = None
    pinned: Annotated[
        Optional[bool],
        Field(
            default=None,
            description=(
                "Whether the entry is pinned for quick access. Matches "
                "rka/models/journal.py JournalEntryCreate.pinned."
            ),
        ),
    ] = None
    provenance: Annotated[
        Optional[_NoteProvenance],
        Field(
            default=None,
            description=(
                "Nested provenance dict (Graft A): "
                "{related_decisions, related_literature, related_mission, supersedes}."
            ),
        ),
    ] = None

    @model_validator(mode="after")
    def _enforce_pi_verbatim(self) -> "RecordNoteArgs":
        if self.source == "pi" and (
            self.verbatim_input is None or not str(self.verbatim_input).strip()
        ):
            raise ValueError(
                "rka_record_note(source='pi'): verbatim_input is required "
                "(preserves PI's exact wording for intellectual attribution)"
            )
        return self


class IngestDocumentArgs(ProjectScopedArgs):
    """[ANY] Ingest a markdown document into many journal entries.

    Splits the input by H1/H2 headings (when ``split_by_headings=True``).
    Each section becomes its own journal row carrying the shared
    provenance + default_type.
    """

    operation: Literal["ingest_document"] = "ingest_document"

    # Required body
    content: Annotated[
        str,
        Field(description="Markdown document body (PRIMARY field)."),
    ]

    # Optional enum-typed fields
    source: Annotated[
        IngestSourceLit,
        Field(default="executor", description="Actor of record."),
    ] = "executor"
    default_type: Annotated[
        NoteTypeLit,
        Field(
            default="finding",
            description="Default note type for emitted entries.",
        ),
    ] = "finding"
    split_by_headings: Annotated[
        bool,
        Field(default=True, description="Split markdown body on H1/H2 headings."),
    ] = True
    phase: Annotated[
        Optional[str],
        Field(default=None, description="Project phase tag."),
    ] = None
    tags: Annotated[
        Optional[list[str]],
        Field(default=None, description="Tags applied to every emitted entry."),
    ] = None
    provenance: Annotated[
        Optional[_NoteProvenance],
        Field(
            default=None,
            description="Shared provenance applied to every emitted entry.",
        ),
    ] = None


# --- decisions ------------------------------------------------------------


class RecordDecisionArgs(ProjectScopedArgs):
    """[BRAIN/PI] RECORD a decision node. Provenance-required.

    Brain hallucination classes closed:
      - ``confidence='confirmed'`` is NOT in the allowed set; use one of
        {hypothesis, tested, verified, superseded, retracted}.
      - ``decided_by='SUPERVISOR'`` is NOT valid; use {pi, brain, executor}.
      - ``kind='research_question'`` is reserved for advanceable RQs;
        most decisions are 'decision' or 'design_choice'.
      - ``related_journal=[]`` is rejected at the Pydantic layer
        (``min_length=1``) AND in the post-validator
        (defense-in-depth for programmatic callers bypassing the schema).
    """

    operation: Literal["record_decision"] = "record_decision"

    # Required body
    question: Annotated[
        str,
        Field(description="Decision question (PRIMARY field)."),
    ]
    chosen: Annotated[
        str,
        Field(description="Chosen option label."),
    ]
    rationale: Annotated[
        str,
        Field(description="Why this was chosen."),
    ]

    # Required enums
    decided_by: Annotated[
        DecidedByLit,
        Field(
            description=(
                "Who decided this. PI for ratified, Brain for proposed, "
                "Executor for self-reported operational decisions."
            ),
        ),
    ]
    kind: Annotated[
        DecisionKindLit,
        Field(description="Kind of decision."),
    ]

    # Required provenance
    related_journal: Annotated[
        list[str],
        Field(
            min_length=1,
            description=(
                "Journal IDs justifying this decision. REQUIRED non-empty "
                "(provenance discipline preserved from Phase-X²)."
            ),
        ),
    ]

    # Optional fields
    options: Annotated[
        Optional[list[dict]],
        Field(
            default=None,
            description="Options considered (each: {id, label, ...}).",
        ),
    ] = None
    supersedes_decision_id: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "If set, this decision supersedes the given decision ID "
                "atomically (POST /api/decisions/{old}/supersede)."
            ),
        ),
    ] = None
    confidence: Annotated[
        ConfidenceLit,
        Field(default="tested", description="Confidence level."),
    ] = "tested"
    tags: Annotated[
        Optional[list[str]],
        Field(default=None, description="Free-form tags."),
    ] = None
    phase: Annotated[
        str,
        Field(
            description=(
                "Project phase tag. REQUIRED — decisions are phase-scoped and "
                "the REST DecisionCreate model requires it. v2.7.0.7 promoted "
                "this from optional to required so a missing phase fails at the "
                "typed-args boundary with a clear message instead of as an "
                "opaque 422 at the API. (The dedicated `supersede_decision` "
                "operation still allows omitting phase — it inherits the old "
                "decision's phase.)"
            ),
        ),
    ]
    parent_id: Annotated[
        Optional[str],
        Field(default=None, description="Parent decision ID (decision tree)."),
    ] = None
    related_literature: Annotated[
        Optional[list[str]],
        Field(default=None, description="Literature IDs cited by this decision."),
    ] = None
    related_missions: Annotated[
        Optional[list[str]],
        Field(
            default=None,
            description=(
                "Mission IDs related to this decision (surfaces the "
                "DecisionCreate.related_missions source field through the "
                "typed-args layer)."
            ),
        ),
    ] = None
    status: Annotated[
        Optional[DecisionStatusLit],
        Field(
            default=None,
            description=(
                "Decision lifecycle status; defaults to 'active' at the "
                "REST layer when omitted."
            ),
        ),
    ] = None
    assumptions: Annotated[
        Optional[list[str]],
        Field(default=None, description="Assumptions underlying this decision."),
    ] = None

    @model_validator(mode="after")
    def _enforce_related_journal_nonempty(self) -> "RecordDecisionArgs":
        # ``min_length=1`` enforces this at the Pydantic schema layer; this
        # validator is defense-in-depth for any caller bypassing the
        # schema (e.g. an orchestrator constructing the model
        # programmatically via __dict__ mutation).
        if not self.related_journal:
            raise ValueError(
                "rka_record_decision: related_journal must be a non-empty "
                "list — decisions need justifying journal entries "
                "(provenance discipline preserved from Phase-X²)"
            )
        return self


# --- literature -----------------------------------------------------------


class RecordLiteratureArgs(ProjectScopedArgs):
    """[ANY] Add a literature entry. Title-based create is the canonical mode.

    For BibTeX bulk-import, use ``import_bibtex`` (separate op). For
    semantic-scholar / arxiv search modes, use Batch A's literature
    query path with the appropriate search_source. This op exists for
    title-based create OR doi-only bootstrap (where the row is created
    with a placeholder title to be enriched later via ``enrich_doi``).
    """

    operation: Literal["record_literature"] = "record_literature"

    # Body: title is the canonical PRIMARY field; doi is the fallback for
    # bootstrap-from-DOI mode.
    title: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Paper title (PRIMARY for title-mode). Either title OR doi "
                "must be provided."
            ),
        ),
    ] = None
    doi: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "DOI (e.g. '10.48550/arXiv.1706.03762'). When only doi is "
                "set (no title), bootstraps a row to enrich later."
            ),
        ),
    ] = None

    # Optional metadata
    authors: Annotated[
        Optional[list[str]],
        Field(default=None, description="Authors list."),
    ] = None
    year: Annotated[
        Optional[int],
        Field(default=None, description="Publication year."),
    ] = None
    venue: Annotated[
        Optional[str],
        Field(default=None, description="Publication venue."),
    ] = None
    url: Annotated[
        Optional[str],
        Field(default=None, description="URL to the paper."),
    ] = None
    abstract: Annotated[
        Optional[str],
        Field(default=None, description="Abstract text."),
    ] = None
    status: Annotated[
        LitStatusLit,
        Field(default="to_read", description="Reading lifecycle status."),
    ] = "to_read"
    tags: Annotated[
        Optional[list[str]],
        Field(default=None, description="Tags."),
    ] = None
    related_decisions: Annotated[
        Optional[list[str]],
        Field(default=None, description="Decision IDs citing this paper."),
    ] = None

    @model_validator(mode="after")
    def _enforce_title_or_doi(self) -> "RecordLiteratureArgs":
        if not self.title and not self.doi:
            raise ValueError(
                "rka_record_literature: provide one of title or doi "
                "(title-based create or doi-only bootstrap)"
            )
        return self


class ImportBibtexArgs(ProjectScopedArgs):
    """[ANY] Bulk-import literature entries from BibTeX."""

    operation: Literal["import_bibtex"] = "import_bibtex"

    bibtex: Annotated[
        str,
        Field(
            min_length=1,
            description="BibTeX library source text (non-empty).",
        ),
    ]
    default_status: Annotated[
        LitStatusLit,
        Field(
            default="to_read",
            description="Reading status applied to every imported entry.",
        ),
    ] = "to_read"


# --- multi-entity ingestion ----------------------------------------------


class BatchImportArgs(ProjectScopedArgs):
    """[ANY] Bulk import mixed entity types in one call.

    Each entry must have ``entity_type`` (note | literature | decision) and
    ``data`` fields. ``actor='import'`` is auto-normalized to
    ``actor='system'`` at the legacy tier (system is the canonical value
    for programmatic ingestion per CLAUDE.md).

    Phase-X²' polish: each entry's structural shape is validated at the
    typed surface (``entity_type`` in the allowed set, ``data`` is a
    dict) so Brain can't ship ``[{}]`` past the schema and defer the
    failure to the REST layer.
    """

    operation: Literal["batch_import"] = "batch_import"

    entries: Annotated[
        list[dict],
        Field(
            min_length=1,
            description=(
                "Non-empty list of {entity_type: 'note'|'literature'|"
                "'decision', data: {...}} entries to import."
            ),
        ),
    ]
    actor: Annotated[
        BatchImportActorLit,
        Field(
            default="system",
            description=(
                "Actor of record. 'import' is auto-normalized to 'system' "
                "(system is the canonical value for programmatic ingestion)."
            ),
        ),
    ] = "system"

    @model_validator(mode="after")
    def _enforce_entry_shape(self) -> "BatchImportArgs":
        allowed_types = {"note", "literature", "decision"}
        for idx, entry in enumerate(self.entries):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"batch_import: entries[{idx}] is not a dict."
                )
            entity_type = entry.get("entity_type")
            if entity_type not in allowed_types:
                raise ValueError(
                    f"batch_import: entries[{idx}].entity_type must be one "
                    f"of {sorted(allowed_types)} (got {entity_type!r})."
                )
            data = entry.get("data")
            if not isinstance(data, dict):
                raise ValueError(
                    f"batch_import: entries[{idx}].data must be a dict "
                    f"(got {type(data).__name__})."
                )
        return self


class RegisterManuscriptArgs(ProjectScopedArgs):
    """[ANY] Register a manuscript workspace."""

    operation: Literal["register_manuscript"] = "register_manuscript"

    venue: Annotated[
        str,
        Field(description="Submission venue (e.g. 'NeurIPS-2026')."),
    ]
    title: Annotated[
        str,
        Field(description="Manuscript title."),
    ]
    abstract: Annotated[
        Optional[str],
        Field(default=None, description="Abstract draft."),
    ] = None
    sections: Annotated[
        Optional[list[str]],
        Field(
            default=None,
            description="Section names for the manuscript skeleton.",
        ),
    ] = None


# --- missions -------------------------------------------------------------


class CreateMissionArgs(ProjectScopedArgs):
    """[BRAIN] Create a mission. Requires ``motivated_by_decision``.

    Provenance discipline: ``motivated_by_decision`` REQUIRED to preserve
    the decision -> mission causality chain (verified by
    ``verb_dispatch.dispatch_mission(action='create')``).
    """

    operation: Literal["create_mission"] = "create_mission"

    # Required body
    objective: Annotated[
        str,
        Field(description="Mission objective (PRIMARY field)."),
    ]
    motivated_by_decision: Annotated[
        str,
        Field(
            description=(
                "Decision ID this mission is grounded in. REQUIRED to "
                "preserve the decision -> mission causality chain."
            ),
        ),
    ]

    # Optional fields
    phase: Annotated[
        Optional[str],
        Field(default="execution", description="Project phase tag."),
    ] = "execution"
    tasks: Annotated[
        Optional[list[dict]],
        Field(
            default=None,
            description="Task breakdown (each: {id, description, ...}).",
        ),
    ] = None
    context: Annotated[
        Optional[str],
        Field(default=None, description="Context paragraph."),
    ] = None
    acceptance_criteria: Annotated[
        Optional[str],
        Field(default=None, description="Acceptance criteria text."),
    ] = None
    scope_boundaries: Annotated[
        Optional[str],
        Field(default=None, description="Scope boundary text."),
    ] = None
    checkpoint_triggers: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Conditions that should trigger a checkpoint (free-form "
                "string). NOTE: ``rka/models/mission.py`` MissionCreate "
                "declares this as ``str | None`` — list-of-strings will "
                "fail HTTP 422 at the REST boundary."
            ),
        ),
    ] = None
    depends_on: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Upstream mission dependencies (free-form string). NOTE: "
                "``rka/models/mission.py`` MissionCreate declares this as "
                "``str | None`` — list-of-strings will fail HTTP 422 at "
                "the REST boundary."
            ),
        ),
    ] = None
    tags: Annotated[
        Optional[list[str]],
        Field(default=None, description="Free-form tags."),
    ] = None

    @model_validator(mode="after")
    def _enforce_motivated_by_decision(self) -> "CreateMissionArgs":
        # The non-Optional declaration above already enforces this at the
        # Pydantic schema layer. This defense-in-depth check mirrors
        # dispatch_mission(action='create')'s contract for any caller
        # bypassing the schema.
        if not self.motivated_by_decision:
            raise ValueError(
                "rka_create_mission: motivated_by_decision required to "
                "preserve decision->mission causality"
            )
        return self


# --- claims/clusters ------------------------------------------------------


class CreateClusterArgs(ProjectScopedArgs):
    """[BRAIN] Create a new evidence cluster."""

    operation: Literal["create_cluster"] = "create_cluster"

    label: Annotated[
        str,
        Field(description="Cluster label (PRIMARY field)."),
    ]
    research_question_id: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Research-question decision ID this cluster supports.",
        ),
    ] = None
    synthesis: Annotated[
        Optional[str],
        Field(default=None, description="Initial synthesis text."),
    ] = None
    confidence: Annotated[
        ClusterConfLit,
        Field(default="emerging", description="Cluster confidence level."),
    ] = "emerging"
    claim_ids: Annotated[
        Optional[list[str]],
        Field(default=None, description="Claim IDs to attach at creation."),
    ] = None


class _ExtractClaimItem(BaseModel):
    """One item in an ``extract_claims`` call.

    Each claim has ``text`` (required) and ``claim_type`` (Literal-typed
    enum). Additional metadata fields (e.g. ``confidence``,
    ``related_literature``) are passed through to the legacy REST adapter
    via ``extra='allow'``.
    """

    model_config = ConfigDict(extra="allow", use_enum_values=True)

    text: Annotated[
        str,
        Field(description="Claim text."),
    ]
    claim_type: Annotated[
        ClaimTypeLit,
        Field(
            description=(
                "Type of claim: hypothesis | evidence | method | "
                "result | observation | assumption."
            ),
        ),
    ]


class ExtractClaimsArgs(ProjectScopedArgs):
    """[BRAIN] Extract claims from an existing entry."""

    operation: Literal["extract_claims"] = "extract_claims"

    entry_id: Annotated[
        str,
        Field(description="Journal entry ID to extract claims from."),
    ]
    claims: Annotated[
        list[_ExtractClaimItem],
        Field(
            min_length=1,
            description=(
                "Non-empty list of claim items. Each item has 'text' + "
                "'claim_type' (hypothesis | evidence | method | result | "
                "observation | assumption)."
            ),
        ),
    ]


# --- checkpoint / gates ---------------------------------------------------


class CreateGateArgs(ProjectScopedArgs):
    """[BRAIN] Create a validation gate (problem_framing, plan_validation,
    evidence_review, synthesis_validation).
    """

    operation: Literal["create_gate"] = "create_gate"

    mission_id: Annotated[
        str,
        Field(description="Mission ID this gate belongs to."),
    ]
    gate_type: Annotated[
        GateTypeLit,
        Field(description="Validation-gate subtype."),
    ]
    deliverables: Annotated[
        list[str],
        Field(min_length=1, description="Deliverables required for the gate."),
    ]
    pass_criteria: Annotated[
        list[str],
        Field(min_length=1, description="Criteria for passing the gate."),
    ]
    assumptions_to_verify: Annotated[
        Optional[list[str]],
        Field(default=None, description="Assumptions to verify at the gate."),
    ] = None


# --- session / project ----------------------------------------------------


class CreateProjectArgs(UnscopedArgs):
    """[PI] Bootstrap a new RKA project (UNSCOPED — does not require
    project_id).
    """

    operation: Literal["create_project"] = "create_project"

    name: Annotated[
        str,
        Field(description="Project name (PRIMARY field)."),
    ]
    description: Annotated[
        Optional[str],
        Field(default=None, description="Free-form project description."),
    ] = None


# --- hooks ----------------------------------------------------------------


class HookAddArgs(ProjectScopedArgs):
    """[PI] Add an automation hook.

    Phase-X²' polish: the well-known ``handler_type`` -> required-key
    cross-validation is enforced at the typed surface so Brain-emitted
    ``{handler_type:'webhook', handler_config:{}}`` is rejected
    pre-dispatch rather than dying at the service layer.
    """

    operation: Literal["hook_add"] = "hook_add"

    event: Annotated[
        str,
        Field(description="Event name (e.g. 'decision.created')."),
    ]
    handler_type: Annotated[
        str,
        Field(description="Handler type (e.g. 'webhook')."),
    ]
    handler_config: Annotated[
        dict[str, Any],
        Field(description="Handler-specific configuration."),
    ]
    name: Annotated[
        str,
        Field(description="Human-readable hook name."),
    ]
    enabled: Annotated[
        bool,
        Field(
            default=True,
            description="Whether the hook is enabled at creation.",
        ),
    ] = True
    created_by: Annotated[
        HookCreatedByLit,
        Field(default="pi", description="Actor of record for hook creation."),
    ] = "pi"

    @model_validator(mode="after")
    def _enforce_handler_config_shape(self) -> "HookAddArgs":
        # Minimal cross-validation for the well-known handler types.
        # Unknown handler types pass through (the service layer can
        # validate exotic handler shapes); known types check their
        # required keys here so Brain can't ship empty configs past
        # the schema.
        required_by_type: dict[str, tuple[str, ...]] = {
            "webhook": ("url",),
        }
        required_keys = required_by_type.get(self.handler_type)
        if required_keys is None:
            return self
        missing = [k for k in required_keys if not self.handler_config.get(k)]
        if missing:
            raise ValueError(
                f"hook_add: handler_type={self.handler_type!r} requires "
                f"handler_config keys {list(required_keys)} "
                f"(missing: {missing})."
            )
        return self


# ---------------------------------------------------------------------------
# Batch B partial union (for the rka_execute discriminated union)
# ---------------------------------------------------------------------------
#
# The full rka_execute union (49 ops) is assembled in the verbs module
# from per-batch contributions. This partial union exposes Batch B's
# slice so unit tests can verify it in isolation.

BatchBExecuteUnion = Annotated[
    Union[
        RecordNoteArgs,
        IngestDocumentArgs,
        RecordDecisionArgs,
        RecordLiteratureArgs,
        ImportBibtexArgs,
        BatchImportArgs,
        RegisterManuscriptArgs,
        CreateMissionArgs,
        CreateClusterArgs,
        CreateProjectArgs,
        CreateGateArgs,
        HookAddArgs,
        ExtractClaimsArgs,
    ],
    Field(discriminator="operation"),
]


# =============================================================================
# Batch D — REVIEW / MAINTENANCE / HOOKS / WORKSPACE operations (14 models)
# =============================================================================
#
# Operations (all rka_execute, all project-scoped):
#   Claims:           assign_claims_to_cluster, split_cluster,
#                     merge_clusters, review_claims, review_cluster,
#                     resolve_contradiction
#   Hooks lifecycle:  hook_enable, hook_disable, hook_delete
#   Notifications:    brain_notifications_clear
#   Workspace:        bootstrap_workspace, scan_workspace
#   Maintenance:      flag_stale, eviction_sweep
#
# Source-of-truth signatures: ``rka/mcp/operations_schema.py`` lines
# 2180-2664. Each model below mirrors the per-op
# ``required_fields + optional_fields + enums`` from that schema.


# ---------------------------------------------------------------------------
# Claims curation — assign / split / merge / review_claims / review_cluster /
# resolve_contradiction
# ---------------------------------------------------------------------------


class AssignClaimsToClusterArgs(ProjectScopedArgs):
    """[BRAIN] Attach a set of claims to an existing evidence cluster.

    Non-empty ``claim_ids`` is enforced by Pydantic ``min_length=1`` so
    the no-op case (``claim_ids=[]``) is rejected pre-dispatch.

    Related: ``create_cluster``, ``split_cluster``, ``merge_clusters``.
    """

    operation: Literal["assign_claims_to_cluster"] = "assign_claims_to_cluster"

    cluster_id: Annotated[
        str,
        Field(description="Target cluster ID (``ecl_...``)."),
    ]
    claim_ids: Annotated[
        list[str],
        Field(
            min_length=1,
            description=(
                "Claim IDs to attach (``clm_...``). Must be non-empty; "
                "an empty list would be a no-op."
            ),
        ),
    ]


class SplitClusterArgs(ProjectScopedArgs):
    """[BRAIN] Split a cluster into multiple smaller clusters.

    ``new_clusters`` is a list of ``{label, claim_ids}`` dicts; the
    service layer validates each entry's shape. Pydantic ``min_length=2``
    enforces the structural minimum — splitting into a single bucket is
    a rename, not a split.

    Related: ``merge_clusters``, ``assign_claims_to_cluster``.
    """

    operation: Literal["split_cluster"] = "split_cluster"

    source_id: Annotated[
        str,
        Field(description="Source cluster ID to split (``ecl_...``)."),
    ]
    new_clusters: Annotated[
        list[dict[str, Any]],
        Field(
            min_length=2,
            description=(
                "List of ``{label, claim_ids}`` dicts describing the new "
                "clusters. Must contain at least 2 entries (splitting "
                "into 1 bucket is a rename, not a split)."
            ),
        ),
    ]


class MergeClustersArgs(ProjectScopedArgs):
    """[BRAIN] Merge multiple clusters into a new combined cluster.

    ``source_ids`` requires >= 2 entries — merging a single cluster is a
    no-op. Pydantic ``min_length=2`` enforces this at the schema layer,
    closing the spec's named ``MergeClustersArgs.model_validator``
    structural-minimum invariant.

    Related: ``split_cluster``, ``create_cluster``.
    """

    operation: Literal["merge_clusters"] = "merge_clusters"

    source_ids: Annotated[
        list[str],
        Field(
            min_length=2,
            description=(
                "Source cluster IDs to merge (``ecl_...``). Must contain "
                "at least 2 entries (single-cluster merge is a no-op)."
            ),
        ),
    ]
    target_label: Annotated[
        str,
        Field(description="Label for the merged target cluster."),
    ]

    target_synthesis: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional synthesis statement for the merged cluster.",
        ),
    ] = None
    research_question_id: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Optional research-question ID to link the merged cluster "
                "to (``dec_...`` with kind=``research_question``)."
            ),
        ),
    ] = None


class ReviewClaimsArgs(ProjectScopedArgs):
    """[BRAIN] Curate grounding and/or evidence assessment for claims.

    ``action`` is the newly-promoted ``ReviewActionLit`` (``approve`` /
    ``reject`` / ``adjust``). Legacy ``approve`` and ``reject`` retain
    their extraction-curation behavior on ``verified``/``stale``.
    Scientific support is never inferred from those actions; callers must
    set ``evidence_status`` explicitly.

    Related: ``claims``, ``review_cluster``.
    """

    operation: Literal["review_claims"] = "review_claims"

    claim_ids: Annotated[
        list[str],
        Field(
            min_length=1,
            description=(
                "Claim IDs to review (``clm_...``). Must be non-empty."
            ),
        ),
    ]

    action: Annotated[
        ReviewActionLit,
        Field(
            default="approve",
            description=(
                "Review action. ``approve`` confirms the claim is grounded "
                "in its source, ``reject`` retires the "
                "extraction, and ``adjust`` applies one or both explicit "
                "overrides. None of these actions implicitly asserts "
                "scientific evidence support."
            ),
        ),
    ] = "approve"
    confidence_override: Annotated[
        Optional[float],
        Field(
            default=None,
            ge=0.0,
            le=1.0,
            description=(
                "Override the claim's numeric confidence (0.0-1.0). "
                "Used with action='adjust'."
            ),
        ),
    ] = None
    evidence_status: Annotated[
        Optional[EvidenceStatusLit],
        Field(
            default=None,
            description=(
                "Explicit scientific evidence assessment. Independent from "
                "verified, which only records source-grounding fidelity."
            ),
        ),
    ] = None

    @model_validator(mode="after")
    def require_adjustment(self) -> "ReviewClaimsArgs":
        """An adjust action must carry at least one concrete change."""
        if (
            self.action == "adjust"
            and self.confidence_override is None
            and self.evidence_status is None
        ):
            raise ValueError(
                "action='adjust' requires confidence_override or evidence_status"
            )
        return self


class ReviewClusterArgs(ProjectScopedArgs):
    """[BRAIN] Write the definitive synthesis on an evidence cluster.

    The Brain's primary act of cluster curation. ``confidence`` is the
    ``ClusterConfLit`` set (``strong`` / ``moderate`` / ``emerging`` /
    ``contested`` / ``refuted``) — distinct from the journal
    ``ConfidenceLit`` set despite the parameter sharing a name with the
    field on ``record_decision``.

    Related: ``clusters``, ``review_claims``, ``resolve_contradiction``.
    """

    operation: Literal["review_cluster"] = "review_cluster"

    cluster_id: Annotated[
        str,
        Field(description="Target cluster ID (``ecl_...``)."),
    ]
    confidence: Annotated[
        ClusterConfLit,
        Field(
            description=(
                "Cluster confidence level. Use ``strong`` only when the "
                "evidence base is robust and the synthesis has been "
                "ratified."
            ),
        ),
    ]
    synthesis: Annotated[
        str,
        Field(
            description=(
                "Definitive synthesis statement for the cluster. This "
                "becomes the cluster's canonical interpretation."
            ),
        ),
    ]

    gaps: Annotated[
        Optional[list[str]],
        Field(
            default=None,
            description="Known evidence gaps to flag for follow-up.",
        ),
    ] = None
    contradictions: Annotated[
        Optional[list[str]],
        Field(
            default=None,
            description=(
                "Contradiction descriptions to surface for "
                "``resolve_contradiction`` follow-up."
            ),
        ),
    ] = None
    resolve_queue_items: Annotated[
        Optional[list[str]],
        Field(
            default=None,
            description=(
                "Review-queue item IDs that this synthesis resolves "
                "(mark-done plumbing for the review queue)."
            ),
        ),
    ] = None
    research_question_id: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Optional research-question ID this cluster contributes "
                "to (``dec_...`` with kind=``research_question``)."
            ),
        ),
    ] = None


class ResolveContradictionArgs(ProjectScopedArgs):
    """[BRAIN] Resolve a contradiction inside an evidence cluster.

    ``claim_actions`` is an optional list of ``{id, action}`` dicts
    where ``action`` is one of ``retire`` / ``demote`` / ``keep`` — the
    service layer validates the enum (not pinned at the Pydantic layer
    because v2.7.0a3 OPERATIONS_SCHEMA doesn't enumerate it).

    Related: ``review_cluster``, ``contradictions``.
    """

    operation: Literal["resolve_contradiction"] = "resolve_contradiction"

    cluster_id: Annotated[
        str,
        Field(description="Cluster containing the contradiction (``ecl_...``)."),
    ]
    resolution: Annotated[
        str,
        Field(
            description=(
                "Resolution statement explaining how the contradiction "
                "is resolved (e.g., 'Newer benchmark supersedes')."
            ),
        ),
    ]

    claim_actions: Annotated[
        Optional[list[dict[str, Any]]],
        Field(
            default=None,
            description=(
                "Optional list of ``{id, action}`` dicts where action is "
                "one of ``retire`` / ``demote`` / ``keep``."
            ),
        ),
    ] = None


# ---------------------------------------------------------------------------
# Hooks lifecycle — enable / disable / delete
# ---------------------------------------------------------------------------


class HookEnableArgs(ProjectScopedArgs):
    """[PI] Enable a previously-defined hook.

    Idempotent — enabling an already-enabled hook is a no-op at the
    service layer.

    Related: ``hook_add``, ``hook_disable``.
    """

    operation: Literal["hook_enable"] = "hook_enable"

    hook_id: Annotated[
        str,
        Field(description="Hook identifier (``hk_...``)."),
    ]


class HookDisableArgs(ProjectScopedArgs):
    """[PI] Disable a hook (preserves config for later re-enable).

    Idempotent — disabling an already-disabled hook is a no-op at the
    service layer.

    Related: ``hook_enable``, ``hook_delete``.
    """

    operation: Literal["hook_disable"] = "hook_disable"

    hook_id: Annotated[
        str,
        Field(description="Hook identifier (``hk_...``)."),
    ]


class HookDeleteArgs(ProjectScopedArgs):
    """[PI] Permanently delete a hook.

    Destructive — the hook row and its handler_config are removed.
    Use ``hook_disable`` instead if you may want to re-enable later.

    Related: ``hook_disable``.
    """

    operation: Literal["hook_delete"] = "hook_delete"

    hook_id: Annotated[
        str,
        Field(description="Hook identifier (``hk_...``)."),
    ]


# ---------------------------------------------------------------------------
# Notifications — brain_notifications_clear
# ---------------------------------------------------------------------------


class BrainNotificationsClearArgs(ProjectScopedArgs):
    """[BRAIN] Clear Brain notifications by ID.

    Non-empty ``ids`` enforced at the Pydantic layer — clearing an
    empty list is a no-op the typed surface rejects pre-dispatch.

    Related: ``brain_notifications``.
    """

    operation: Literal["brain_notifications_clear"] = "brain_notifications_clear"

    ids: Annotated[
        list[str],
        Field(
            min_length=1,
            description=(
                "Notification IDs to clear (``bn_...``). Must be "
                "non-empty."
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Workspace — bootstrap_workspace / scan_workspace
# ---------------------------------------------------------------------------


class BootstrapWorkspaceArgs(ProjectScopedArgs):
    """[ANY] Bootstrap a workspace folder into the knowledge base.

    Walks ``folder_path``, extracts metadata, mints knowledge entries.
    ``dry_run=True`` simulates the bootstrap without writing.
    ``use_llm`` toggles LLM-driven categorisation; defaults True per the
    v2.7.0a3 schema (service falls back to deterministic rules when no
    LLM is configured).

    The ``folder_path`` MUST be an absolute path; tilde-prefixed paths
    (``~/...``) are rejected (mirror of the Phase D2.1 orchestrator
    fix — inside the daemon container ``~`` resolves to ``/root`` and
    the HOST_WORKSPACE_ROOT bind mount would miss).

    Related: ``workspace_scan``, ``workspace_tree``, ``bootstrap_review``.
    """

    operation: Literal["bootstrap_workspace"] = "bootstrap_workspace"

    folder_path: Annotated[
        str,
        Field(
            description=(
                "Absolute path to the workspace folder to bootstrap. "
                "Tilde-prefixed paths (``~/...``) are NOT accepted — "
                "use the fully-resolved absolute path."
            ),
        ),
    ]

    phase: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional phase identifier to tag generated entries with.",
        ),
    ] = None
    override_tags: Annotated[
        Optional[list[str]],
        Field(
            default=None,
            description=(
                "Tags to apply to every generated entry (overrides the "
                "default tagging policy)."
            ),
        ),
    ] = None
    skip_files: Annotated[
        Optional[list[str]],
        Field(
            default=None,
            description=(
                "List of file paths or glob patterns to skip during the "
                "walk."
            ),
        ),
    ] = None
    use_llm: Annotated[
        bool,
        Field(
            default=True,
            description=(
                "Enable LLM-driven categorisation. Defaults to True; "
                "falls back to deterministic rules when no LLM is "
                "configured."
            ),
        ),
    ] = True
    dry_run: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "When True, simulate the bootstrap and emit a preview "
                "without writing any rows."
            ),
        ),
    ] = False


class ScanWorkspaceArgs(ProjectScopedArgs):
    """[ANY] Execute a workspace scan (writes a ``scn_...`` row).

    Distinct from ``bootstrap_workspace`` — scan records a snapshot of
    files + hashes (used by drift detection) WITHOUT inferring
    knowledge entries from contents.

    Related: ``workspace_scan`` (query), ``bootstrap_workspace``.
    """

    operation: Literal["scan_workspace"] = "scan_workspace"

    folder_path: Annotated[
        str,
        Field(
            description=(
                "Absolute path to the workspace folder to scan. "
                "Tilde-prefixed paths (``~/...``) are NOT accepted."
            ),
        ),
    ]

    ignore_patterns: Annotated[
        Optional[list[str]],
        Field(
            default=None,
            description=(
                "Glob patterns to skip (extends the built-in "
                "``.git``/``node_modules``/``.venv`` ignore list)."
            ),
        ),
    ] = None
    max_file_size_mb: Annotated[
        float,
        Field(
            default=50.0,
            gt=0.0,
            description=(
                "Per-file size cap in megabytes. Files above this size "
                "are hashed but their contents are NOT inspected."
            ),
        ),
    ] = 50.0
    use_llm: Annotated[
        bool,
        Field(
            default=True,
            description="Enable LLM-driven file-type inference. Defaults to True.",
        ),
    ] = True


# ---------------------------------------------------------------------------
# Maintenance — flag_stale / eviction_sweep
# ---------------------------------------------------------------------------


class FlagStaleArgs(ProjectScopedArgs):
    """[BRAIN] Flag a knowledge entity as stale.

    ``staleness`` is the ``StalenessLit`` set (``yellow`` for soft
    warning, ``red`` for definitive). ``propagate=True`` (default)
    cascades the flag through provenance edges so downstream entries
    inherit the staleness signal.

    Related: ``freshness``, ``eviction_sweep``.
    """

    operation: Literal["flag_stale"] = "flag_stale"

    entity_id: Annotated[
        str,
        Field(
            description=(
                "Target entity ID. Most commonly ``jrn_`` / ``dec_`` / "
                "``clm_`` / ``ecl_`` — the service layer validates the "
                "prefix is one of the flag-supported types."
            ),
        ),
    ]
    reason: Annotated[
        str,
        Field(
            description=(
                "Free-form reason for the staleness flag (e.g., "
                "'Superseded by new benchmark')."
            ),
        ),
    ]

    staleness: Annotated[
        StalenessLit,
        Field(
            default="yellow",
            description=(
                "Staleness severity. ``yellow`` is a soft warning; "
                "``red`` indicates definitively superseded."
            ),
        ),
    ] = "yellow"
    propagate: Annotated[
        bool,
        Field(
            default=True,
            description=(
                "When True, cascade the staleness flag through "
                "provenance edges so downstream entries inherit the "
                "signal."
            ),
        ),
    ] = True


class EvictionSweepArgs(ProjectScopedArgs):
    """[BRAIN] Evict knowledge entries per the configured policy.

    Defaults to ``dry_run=True`` — the destructive ``dry_run=False``
    path is opt-in. Under the orchestrator's TWO-TAP autonomy contract,
    a ``dry_run=False`` invocation requires explicit PI ratification
    via ``pi_decision_select``.

    Related: ``flag_stale``, ``freshness``.
    """

    operation: Literal["eviction_sweep"] = "eviction_sweep"

    dry_run: Annotated[
        bool,
        Field(
            default=True,
            description=(
                "When True (default), preview what would be evicted. "
                "When False, perform the destructive sweep — requires "
                "explicit ratification under the orchestrator's TWO-TAP "
                "autonomy contract."
            ),
        ),
    ] = True


# ---------------------------------------------------------------------------
# Batch D partial union (for the rka_execute discriminated union)
# ---------------------------------------------------------------------------
#
# Mirrors the Batch B pattern: the per-batch partial union is exposed so
# unit tests can verify Batch D's slice in isolation. Phase 3 composes
# the final ExecuteArgsUnion = BatchBExecuteUnion ∪ BatchCExecuteUnion ∪
# BatchDExecuteUnion (plus the orphan ``HealthArgs`` / ``ListProjectsArgs``
# already in QueryArgsUnion).

BatchDExecuteUnion = Annotated[
    Union[
        # Claims curation
        AssignClaimsToClusterArgs,
        SplitClusterArgs,
        MergeClustersArgs,
        ReviewClaimsArgs,
        ReviewClusterArgs,
        ResolveContradictionArgs,
        # Hooks lifecycle
        HookEnableArgs,
        HookDisableArgs,
        HookDeleteArgs,
        # Notifications
        BrainNotificationsClearArgs,
        # Workspace
        BootstrapWorkspaceArgs,
        ScanWorkspaceArgs,
        # Maintenance
        FlagStaleArgs,
        EvictionSweepArgs,
    ],
    Field(discriminator="operation"),
]


# =============================================================================
# Batch C — UPDATE / LIFECYCLE / SUBMIT operations (22 models)
# =============================================================================
#
# Operations:
#   Updates:           update_note, update_decision, update_literature,
#                      update_mission, update_status, update_mission_status,
#                      bulk_update, supersede_decision
#   Decision lifecycle: present_decision, record_pi_selection, record_outcome
#   Literature lifecycle: enrich_doi, link_literature_to_zotero,
#                         process_paper, validate_reference
#   Mission lifecycle:  submit_report, advance_rq
#   Checkpoint lifecycle: submit_checkpoint, resolve_checkpoint, evaluate_gate
#   Session lifecycle:  reset_session, session_digest


# ---------------------------------------------------------------------------
# UPDATES (8)
# ---------------------------------------------------------------------------


class UpdateNoteArgs(ProjectScopedArgs):
    """Update a journal entry (content / type / confidence / links).

    Phase-X²' note: every update tool has a "no-op update" guard — at
    least one mutable field must be non-None — to keep Brain from
    dispatching id-only updates that change nothing.

    Phase-X²' regression: ``importance`` MUST be the ``ImportanceLit``
    set (bare ``str`` lets Brain emit ``importance='URGENT'`` and bypass
    the journal.importance CHECK at DB INSERT time).

    Phase-X²' provenance discipline: the ``source='pi' -> verbatim_input``
    invariant mirrored from ``RecordNoteArgs`` — silent demotion of PI
    attribution on the update path is blocked here too.
    """

    operation: Literal["update_note"] = "update_note"

    id: Annotated[
        str,
        Field(description="Journal entry id (jrn_*) to update."),
    ]

    content: Annotated[
        Optional[str],
        Field(default=None, description="New content body."),
    ] = None
    type: Annotated[
        Optional[NoteTypeLit],
        Field(default=None, description="New journal type (v2 canonical or legacy-accepted)."),
    ] = None
    confidence: Annotated[
        Optional[ConfidenceLit],
        Field(default=None, description="New confidence level."),
    ] = None
    importance: Annotated[
        Optional[ImportanceLit],
        Field(default=None, description="New importance level."),
    ] = None
    tags: Annotated[
        Optional[list[str]],
        Field(default=None, description="Replacement tag list."),
    ] = None
    phase: Annotated[
        Optional[str],
        Field(default=None, description="New phase label."),
    ] = None
    verbatim_input: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Updated verbatim PI input (REQUIRED when source=='pi').",
        ),
    ] = None
    source: Annotated[
        Optional[SourceLit],
        Field(default=None, description="Updated actor-of-record."),
    ] = None
    related_decisions: Annotated[
        Optional[list[str]],
        Field(default=None, description="Replacement related-decision ids."),
    ] = None
    related_literature: Annotated[
        Optional[list[str]],
        Field(default=None, description="Replacement related-literature ids."),
    ] = None
    related_mission: Annotated[
        Optional[str],
        Field(default=None, description="Replacement related-mission id."),
    ] = None

    @model_validator(mode="after")
    def _enforce_non_empty_update(self) -> "UpdateNoteArgs":
        mutable_fields = (
            self.content,
            self.type,
            self.confidence,
            self.importance,
            self.tags,
            self.phase,
            self.verbatim_input,
            self.source,
            self.related_decisions,
            self.related_literature,
            self.related_mission,
        )
        if all(f is None for f in mutable_fields):
            raise ValueError(
                "update_note: at least one mutable field must be non-None "
                "(content, type, confidence, importance, tags, phase, "
                "verbatim_input, source, related_decisions, related_literature, "
                "related_mission)."
            )
        return self

    @model_validator(mode="after")
    def _enforce_pi_verbatim(self) -> "UpdateNoteArgs":
        # Phase-X²' regression: silent PI-attribution demotion on the
        # update path. Mirrors ``RecordNoteArgs._enforce_pi_verbatim``.
        # Fires whenever source is being set to 'pi'; the no-op guard
        # above covers the both-None case (id-only update).
        if self.source == "pi" and (
            self.verbatim_input is None or not str(self.verbatim_input).strip()
        ):
            raise ValueError(
                "update_note(source='pi'): verbatim_input is required "
                "(preserves PI's exact wording for intellectual attribution)"
            )
        return self


class UpdateDecisionArgs(ProjectScopedArgs):
    """Update fields on an existing decision.

    Phase-X²' regression: ``status`` MUST be the ``DecisionStatusLit``
    set (bare ``str`` lets Brain emit invalid statuses that fail the
    ``decisions.status`` CHECK at DB INSERT time — HTTP 500 instead of
    422 at the typed-args layer).
    """

    operation: Literal["update_decision"] = "update_decision"

    id: Annotated[
        str,
        Field(description="Decision id (dec_*) to update."),
    ]

    status: Annotated[
        Optional[DecisionStatusLit],
        Field(default=None, description="New decision lifecycle status (active|abandoned|superseded|merged|revisit)."),
    ] = None
    chosen: Annotated[
        Optional[str],
        Field(default=None, description="Revised chosen option."),
    ] = None
    rationale: Annotated[
        Optional[str],
        Field(default=None, description="Revised rationale."),
    ] = None
    kind: Annotated[
        Optional[DecisionKindLit],
        Field(default=None, description="Revised decision kind."),
    ] = None
    related_journal: Annotated[
        Optional[list[str]],
        Field(default=None, description="Replacement related-journal ids."),
    ] = None
    parent_id: Annotated[
        Optional[str],
        Field(default=None, description="Parent decision id."),
    ] = None
    related_literature: Annotated[
        Optional[list[str]],
        Field(default=None, description="Replacement related-literature ids."),
    ] = None
    related_missions: Annotated[
        Optional[list[str]],
        Field(default=None, description="Replacement related-mission ids."),
    ] = None
    phase: Annotated[
        Optional[str],
        Field(default=None, description="New phase label."),
    ] = None
    tags: Annotated[
        Optional[list[str]],
        Field(default=None, description="Replacement tag list."),
    ] = None
    assumptions: Annotated[
        Optional[list[str]],
        Field(default=None, description="Revised assumption list."),
    ] = None
    abandonment_reason: Annotated[
        Optional[str],
        Field(default=None, description="Reason for abandoning (when status transitions)."),
    ] = None

    @model_validator(mode="after")
    def _enforce_non_empty_update(self) -> "UpdateDecisionArgs":
        mutable_fields = (
            self.status,
            self.chosen,
            self.rationale,
            self.kind,
            self.related_journal,
            self.parent_id,
            self.related_literature,
            self.related_missions,
            self.phase,
            self.tags,
            self.assumptions,
            self.abandonment_reason,
        )
        if all(f is None for f in mutable_fields):
            raise ValueError(
                "update_decision: at least one mutable field must be non-None."
            )
        return self


class UpdateLiteratureArgs(ProjectScopedArgs):
    """Update fields on a literature entry.

    Phase-X²' polish: ``key_findings`` is ``list[str]`` to match
    ``rka/models/literature.py`` ``LiteratureUpdate.key_findings`` —
    previously typed as ``str`` here, which fails REST PATCH with HTTP
    422 ``Input should be a valid list``.
    """

    operation: Literal["update_literature"] = "update_literature"

    id: Annotated[
        str,
        Field(description="Literature entry id (lit_*) to update."),
    ]

    title: Annotated[
        Optional[str],
        Field(default=None, description="Revised title."),
    ] = None
    authors: Annotated[
        Optional[list[str]],
        Field(default=None, description="Replacement author list."),
    ] = None
    year: Annotated[
        Optional[int],
        Field(default=None, description="Publication year."),
    ] = None
    venue: Annotated[
        Optional[str],
        Field(default=None, description="Publication venue."),
    ] = None
    doi: Annotated[
        Optional[str],
        Field(default=None, description="DOI string."),
    ] = None
    url: Annotated[
        Optional[str],
        Field(default=None, description="Canonical URL."),
    ] = None
    bibtex: Annotated[
        Optional[str],
        Field(default=None, description="Raw BibTeX entry."),
    ] = None
    pdf_path: Annotated[
        Optional[str],
        Field(default=None, description="Local PDF path."),
    ] = None
    abstract: Annotated[
        Optional[str],
        Field(default=None, description="Abstract text."),
    ] = None
    status: Annotated[
        Optional[LitStatusLit],
        Field(default=None, description="New reading-lifecycle status."),
    ] = None
    key_findings: Annotated[
        Optional[list[str]],
        Field(default=None, description="Reader-noted key findings (list of strings)."),
    ] = None
    methodology_notes: Annotated[
        Optional[str],
        Field(default=None, description="Methodology notes."),
    ] = None
    relevance: Annotated[
        Optional[str],
        Field(default=None, description="Relevance prose."),
    ] = None
    relevance_score: Annotated[
        Optional[float],
        Field(default=None, description="Numeric relevance score."),
    ] = None
    related_decisions: Annotated[
        Optional[list[str]],
        Field(default=None, description="Linked decision ids."),
    ] = None
    notes: Annotated[
        Optional[str],
        Field(default=None, description="Free-form notes."),
    ] = None
    tags: Annotated[
        Optional[list[str]],
        Field(default=None, description="Replacement tag list."),
    ] = None

    @model_validator(mode="after")
    def _enforce_non_empty_update(self) -> "UpdateLiteratureArgs":
        mutable_fields = (
            self.title,
            self.authors,
            self.year,
            self.venue,
            self.doi,
            self.url,
            self.bibtex,
            self.pdf_path,
            self.abstract,
            self.status,
            self.key_findings,
            self.methodology_notes,
            self.relevance,
            self.relevance_score,
            self.related_decisions,
            self.notes,
            self.tags,
        )
        if all(f is None for f in mutable_fields):
            raise ValueError(
                "update_literature: at least one mutable field must be non-None."
            )
        return self


class UpdateMissionArgs(ProjectScopedArgs):
    """Update mission fields (objective, context, criteria, etc.)."""

    operation: Literal["update_mission"] = "update_mission"

    mission_id: Annotated[
        str,
        Field(description="Mission id (mis_*) to update."),
    ]

    phase: Annotated[
        Optional[str],
        Field(default=None, description="New mission phase label."),
    ] = None
    objective: Annotated[
        Optional[str],
        Field(default=None, description="Revised objective."),
    ] = None
    context: Annotated[
        Optional[str],
        Field(default=None, description="Revised context."),
    ] = None
    acceptance_criteria: Annotated[
        Optional[str],
        Field(default=None, description="Revised acceptance criteria."),
    ] = None
    scope_boundaries: Annotated[
        Optional[str],
        Field(default=None, description="Revised scope boundaries."),
    ] = None
    checkpoint_triggers: Annotated[
        Optional[list[str]],
        Field(default=None, description="Revised checkpoint-trigger conditions."),
    ] = None
    depends_on: Annotated[
        Optional[list[str]],
        Field(default=None, description="Replacement upstream-dependency ids."),
    ] = None
    parent_mission_id: Annotated[
        Optional[str],
        Field(default=None, description="Parent mission id (for hierarchy)."),
    ] = None
    motivated_by_decision: Annotated[
        Optional[str],
        Field(default=None, description="Decision id that motivates this mission."),
    ] = None
    tags: Annotated[
        Optional[list[str]],
        Field(default=None, description="Replacement tag list."),
    ] = None

    @model_validator(mode="after")
    def _enforce_non_empty_update(self) -> "UpdateMissionArgs":
        mutable_fields = (
            self.phase,
            self.objective,
            self.context,
            self.acceptance_criteria,
            self.scope_boundaries,
            self.checkpoint_triggers,
            self.depends_on,
            self.parent_mission_id,
            self.motivated_by_decision,
            self.tags,
        )
        if all(f is None for f in mutable_fields):
            raise ValueError(
                "update_mission: at least one mutable field must be non-None."
            )
        return self


class UpdateStatusArgs(ProjectScopedArgs):
    """Update the project status (phase, focus, blockers)."""

    operation: Literal["update_status"] = "update_status"

    current_phase: Annotated[
        Optional[str],
        Field(default=None, description="New project-level phase label."),
    ] = None
    summary: Annotated[
        Optional[str],
        Field(default=None, description="Status summary text."),
    ] = None
    blockers: Annotated[
        Optional[list[str]],
        Field(default=None, description="Replacement blockers list."),
    ] = None
    metrics: Annotated[
        Optional[dict[str, Any]],
        Field(default=None, description="Replacement metrics dict."),
    ] = None

    @model_validator(mode="after")
    def _enforce_non_empty_update(self) -> "UpdateStatusArgs":
        if (
            self.current_phase is None
            and self.summary is None
            and self.blockers is None
            and self.metrics is None
        ):
            raise ValueError(
                "update_status: at least one of (current_phase, summary, "
                "blockers, metrics) must be non-None."
            )
        return self


class UpdateMissionStatusArgs(ProjectScopedArgs):
    """Move a mission through its lifecycle states."""

    operation: Literal["update_mission_status"] = "update_mission_status"

    mission_id: Annotated[
        str,
        Field(description="Mission id (mis_*) whose status to transition."),
    ]
    status: Annotated[
        MissionStatusLit,
        Field(description="New lifecycle state (pending|active|complete|partial|blocked|cancelled)."),
    ]

    tasks: Annotated[
        Optional[list[dict[str, Any]]],
        Field(
            default=None,
            description="Optional task list update accompanying the status transition.",
        ),
    ] = None


class BulkUpdateArgs(ProjectScopedArgs):
    """Update many entities in one atomic call."""

    operation: Literal["bulk_update"] = "bulk_update"

    updates: Annotated[
        list[dict[str, Any]],
        Field(
            min_length=1,
            description=(
                "List of update dicts. Each dict MUST include an 'id' "
                "key plus the fields to update for that entity."
            ),
        ),
    ]

    @model_validator(mode="after")
    def _enforce_id_on_every_item(self) -> "BulkUpdateArgs":
        for idx, item in enumerate(self.updates):
            if not isinstance(item, dict):
                raise ValueError(
                    f"bulk_update: updates[{idx}] is not a dict."
                )
            if "id" not in item or not item["id"]:
                raise ValueError(
                    f"bulk_update: updates[{idx}] missing required 'id' key."
                )
        return self


class SupersedeDecisionArgs(ProjectScopedArgs):
    """Replace an old decision with a new one (atomically links the two).

    Phase-X²' provenance discipline: ``related_journal`` REQUIRED non-empty
    on the supersede path — supersede CREATES a new decision and the same
    provenance rule that applies to ``RecordDecisionArgs.related_journal``
    must apply here. Without it, Brain can supersede a decision into a
    provenance-orphaned successor.
    """

    operation: Literal["supersede_decision"] = "supersede_decision"

    old_decision_id: Annotated[
        str,
        Field(description="The decision id (dec_*) being superseded."),
    ]
    question: Annotated[str, Field(description="Revised decision question.")]
    chosen: Annotated[str, Field(description="Newly chosen option label.")]
    rationale: Annotated[str, Field(description="Rationale for the new choice.")]

    # Required provenance (mirrors RecordDecisionArgs).
    related_journal: Annotated[
        list[str],
        Field(
            min_length=1,
            description=(
                "Journal IDs justifying the new (superseding) decision. "
                "REQUIRED non-empty (provenance discipline preserved from "
                "RecordDecisionArgs)."
            ),
        ),
    ]

    decided_by: Annotated[
        Optional[DecidedByLit],
        Field(
            default="brain",
            description="Who decided (PI for ratified, Brain for proposed).",
        ),
    ] = "brain"
    phase: Annotated[
        Optional[str],
        Field(default=None, description="Phase label."),
    ] = None
    kind: Annotated[
        Optional[DecisionKindLit],
        Field(
            default="decision",
            description="Decision kind (decision|design_choice|research_question|operational).",
        ),
    ] = "decision"

    @model_validator(mode="after")
    def _enforce_related_journal_nonempty(self) -> "SupersedeDecisionArgs":
        # Defense-in-depth (mirrors RecordDecisionArgs validator).
        if not self.related_journal:
            raise ValueError(
                "supersede_decision: related_journal must be a non-empty "
                "list — superseding decisions need justifying journal "
                "entries (provenance discipline preserved from Phase-X²)."
            )
        return self


# ---------------------------------------------------------------------------
# DECISION LIFECYCLE (3)
# ---------------------------------------------------------------------------


class PresentDecisionArgs(ProjectScopedArgs):
    """Present a decision to the PI for ratification.

    Phase-X²' polish: ``options`` MUST be non-empty (TWO-TAP autonomy
    contract is semantically void if there are no choices to ratify).
    Each option dict MUST carry an ``id`` key so downstream
    ``record_pi_selection.selected_option_id`` references are
    dereferenceable.
    """

    operation: Literal["present_decision"] = "present_decision"

    decision_id: Annotated[
        str,
        Field(description="Decision id (dec_*) being presented."),
    ]
    confirmation_brief: Annotated[
        str,
        Field(description="Short brief explaining the choice + tradeoffs to the PI."),
    ]
    options: Annotated[
        list[dict[str, Any]],
        Field(
            min_length=1,
            description=(
                "Non-empty list of option dicts (each MUST include an 'id' "
                "key; typical shape {id, label, ...})."
            ),
        ),
    ]
    pi_preference: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional PI-stated preference hint (verbatim).",
        ),
    ] = None

    @model_validator(mode="after")
    def _enforce_id_on_every_option(self) -> "PresentDecisionArgs":
        # Mirrors BulkUpdateArgs._enforce_id_on_every_item — downstream
        # record_pi_selection.selected_option_id must be dereferenceable.
        for idx, opt in enumerate(self.options):
            if not isinstance(opt, dict):
                raise ValueError(
                    f"present_decision: options[{idx}] is not a dict."
                )
            if "id" not in opt or not opt["id"]:
                raise ValueError(
                    f"present_decision: options[{idx}] missing required "
                    "'id' key (TWO-TAP record_pi_selection references "
                    "options by id)."
                )
        return self


class RecordPiSelectionArgs(ProjectScopedArgs):
    """Record the PI's selection on a presented decision."""

    operation: Literal["record_pi_selection"] = "record_pi_selection"

    decision_id: Annotated[
        str,
        Field(description="Decision id (dec_*) the PI is selecting on."),
    ]

    selected_option_id: Annotated[
        Optional[str],
        Field(
            default=None,
            description="The PI's chosen option id from the presented options.",
        ),
    ] = None
    override_rationale: Annotated[
        Optional[str],
        Field(
            default=None,
            description="PI-provided rationale (used to record an override or annotate the choice).",
        ),
    ] = None

    @model_validator(mode="after")
    def _require_selection_or_rationale(self) -> "RecordPiSelectionArgs":
        if self.selected_option_id is None and self.override_rationale is None:
            raise ValueError(
                "record_pi_selection: at least one of selected_option_id or "
                "override_rationale required."
            )
        return self


class RecordOutcomeArgs(ProjectScopedArgs):
    """Record the calibration outcome of a past decision.

    Phase-X²' polish: ``recorded_by`` typed as ``RecordedByLit`` (was
    bare ``str``) so Brain cannot emit ``recorded_by='SUPERVISOR'`` and
    pollute the calibration provenance. The calibration_outcomes table
    has no DB-level CHECK constraint on ``recorded_by``, so the typed
    surface is the authoritative gate.
    """

    operation: Literal["record_outcome"] = "record_outcome"

    decision_id: Annotated[
        str,
        Field(description="Decision id (dec_*) whose outcome is being recorded."),
    ]
    outcome: Annotated[
        OutcomeLit,
        Field(description="Calibration outcome (succeeded|failed|mixed|unresolved)."),
    ]

    outcome_details: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Free-form details on the outcome.",
        ),
    ] = None
    recorded_by: Annotated[
        Optional[RecordedByLit],
        Field(
            default="pi",
            description="Actor recording the outcome (pi|brain|executor|system); typically 'pi'.",
        ),
    ] = "pi"


# ---------------------------------------------------------------------------
# LITERATURE LIFECYCLE (4)
# ---------------------------------------------------------------------------


class EnrichDoiArgs(ProjectScopedArgs):
    """Enrich a literature entry's metadata from its DOI."""

    operation: Literal["enrich_doi"] = "enrich_doi"

    lit_id: Annotated[
        str,
        Field(description="Literature entry id (lit_*) whose DOI is the lookup key."),
    ]


class LinkLiteratureToZoteroArgs(ProjectScopedArgs):
    """Link a literature entry to a Zotero item."""

    operation: Literal["link_literature_to_zotero"] = "link_literature_to_zotero"

    lit_id: Annotated[
        str,
        Field(description="Literature entry id (lit_*) to link."),
    ]

    zotero_key: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Optional Zotero item key. If omitted, the service looks "
                "up by DOI / title via the configured Zotero adapter."
            ),
        ),
    ] = None


class ProcessPaperArgs(ProjectScopedArgs):
    """Ingest paper annotations into the literature row.

    Phase-X²' polish: ``annotations`` MUST be non-empty (zero annotations
    is a no-op); each annotation dict MUST carry a ``text`` key.
    """

    operation: Literal["process_paper"] = "process_paper"

    lit_id: Annotated[
        str,
        Field(description="Literature entry id (lit_*) receiving the annotations."),
    ]
    annotations: Annotated[
        list[dict[str, Any]],
        Field(
            min_length=1,
            description=(
                "Non-empty list of annotation dicts (each MUST include a "
                "'text' key; typical shape {text, page, ...})."
            ),
        ),
    ]

    summary: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional narrative summary derived from the annotations.",
        ),
    ] = None

    @model_validator(mode="after")
    def _enforce_text_on_every_annotation(self) -> "ProcessPaperArgs":
        for idx, ann in enumerate(self.annotations):
            if not isinstance(ann, dict):
                raise ValueError(
                    f"process_paper: annotations[{idx}] is not a dict."
                )
            if "text" not in ann or not ann["text"]:
                raise ValueError(
                    f"process_paper: annotations[{idx}] missing required "
                    "'text' key (annotations without text are meaningless)."
                )
        return self


class ValidateReferenceArgs(ProjectScopedArgs):
    """Validate a manuscript reference (by DOI or title)."""

    operation: Literal["validate_reference"] = "validate_reference"

    manuscript_id: Annotated[
        str,
        Field(description="Manuscript journal id (jrn_*) whose reference is being validated."),
    ]

    doi: Annotated[
        Optional[str],
        Field(default=None, description="DOI to validate."),
    ] = None
    title: Annotated[
        Optional[str],
        Field(default=None, description="Title to validate."),
    ] = None
    author: Annotated[
        Optional[list[dict[str, str]]],
        Field(
            default=None,
            description=(
                "Optional CSL-JSON author list. Supplying authors enables "
                "Stage E disambiguation."
            ),
        ),
    ] = None
    literature_id: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional same-project lit_ record to bind to the attestation.",
        ),
    ] = None

    @model_validator(mode="after")
    def _require_doi_or_title(self) -> "ValidateReferenceArgs":
        if self.doi is None and self.title is None:
            raise ValueError(
                "validate_reference: at least one of doi or title required."
            )
        return self


# ---------------------------------------------------------------------------
# MISSION LIFECYCLE (2)
# ---------------------------------------------------------------------------


class SubmitReportArgs(ProjectScopedArgs):
    """Submit a mission's final report (closes the mission).

    Phase-X²' alias rule: canonical body field is ``summary``; legacy
    callers using ``content`` are accepted. Both None -> raise.

    Phase-X²' polish (drift fix): ``findings``/``anomalies``/``questions``
    are ``list[str]`` here to match ``rka/models/mission.py``
    ``MissionReportCreate``. ``codebase_state``/``recommended_next``
    default to ``None`` (not ``""``) so ``model_dump(exclude_none=True)``
    truly omits unsupplied fields per the dispatcher contract.
    """

    operation: Literal["submit_report"] = "submit_report"

    mission_id: Annotated[
        str,
        Field(description="Mission id (mis_*) being closed."),
    ]

    summary: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Report narrative body (CANONICAL). One of summary or "
                "content is required."
            ),
        ),
    ] = None
    content: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Phase-X²' alias for `summary`. If both are supplied, "
                "`summary` wins (canonical)."
            ),
        ),
    ] = None

    findings: Annotated[
        Optional[list[str]],
        Field(default=None, description="Findings (list of strings)."),
    ] = None
    anomalies: Annotated[
        Optional[list[str]],
        Field(default=None, description="Anomalies (list of strings)."),
    ] = None
    questions: Annotated[
        Optional[list[str]],
        Field(default=None, description="Open questions (list of strings)."),
    ] = None
    codebase_state: Annotated[
        Optional[str],
        Field(default=None, description="Codebase state notes."),
    ] = None
    recommended_next: Annotated[
        Optional[str],
        Field(default=None, description="Recommended next mission."),
    ] = None

    @model_validator(mode="after")
    def _require_summary_or_content(self) -> "SubmitReportArgs":
        if self.summary is None and self.content is None:
            raise ValueError(
                "submit_report: one of 'summary' or 'content' is required "
                "(summary is canonical; content is a Phase-X²' alias)."
            )
        # Canonical-wins normalisation: when both are supplied, null the
        # alias so model_dump(exclude_none=True) emits only `summary`.
        if self.summary is not None and self.content is not None:
            self.content = None
        return self


class AdvanceRqArgs(ProjectScopedArgs):
    """Advance a research question through its lifecycle."""

    operation: Literal["advance_rq"] = "advance_rq"

    rq_id: Annotated[
        str,
        Field(description="Research-question id (dec_*) being advanced."),
    ]
    status: Annotated[
        RQStatusLit,
        Field(description="New RQ status (open|partially_answered|answered|reframed|closed)."),
    ]

    conclusion: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional conclusion text (recommended when status='answered').",
        ),
    ] = None
    evidence_cluster_ids: Annotated[
        Optional[list[str]],
        Field(
            default=None,
            description="Optional evidence-cluster ids (ecl_*) supporting the advance.",
        ),
    ] = None


# ---------------------------------------------------------------------------
# CHECKPOINT LIFECYCLE (3)
# ---------------------------------------------------------------------------


class SubmitCheckpointArgs(ProjectScopedArgs):
    """Raise a checkpoint when blocked or needing input.

    Phase-X²' alias rule (2026-06-01 hyperscaler-auditing PA-2):
    canonical body field is ``description``; legacy callers using
    ``content`` are accepted. Both None -> raise.
    """

    operation: Literal["submit_checkpoint"] = "submit_checkpoint"

    mission_id: Annotated[
        str,
        Field(description="Mission id (mis_*) the checkpoint is raised on."),
    ]
    type: Annotated[
        ChkTypeLit,
        Field(description="Checkpoint type (decision|clarification|inspection|gate)."),
    ]

    description: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Checkpoint description (CANONICAL). One of description "
                "or content is required."
            ),
        ),
    ] = None
    content: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Phase-X²' alias for `description`. If both are supplied, "
                "`description` wins (canonical) and `content` is silently "
                "nulled. Common Brain hallucination class — alias provided "
                "for back-compat."
            ),
        ),
    ] = None

    task_reference: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional task-reference string within the mission.",
        ),
    ] = None
    context: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional context payload (free-form).",
        ),
    ] = None
    options: Annotated[
        Optional[list[dict[str, Any]]],
        Field(
            default=None,
            description="Optional list of option dicts presented to the resolver.",
        ),
    ] = None
    recommendation: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional recommended resolution.",
        ),
    ] = None
    blocking: Annotated[
        Optional[bool],
        Field(
            default=True,
            description="Whether the checkpoint blocks the mission (default True).",
        ),
    ] = True

    @model_validator(mode="after")
    def _require_description_or_content(self) -> "SubmitCheckpointArgs":
        if self.description is None and self.content is None:
            raise ValueError(
                "submit_checkpoint: one of 'description' or 'content' is "
                "required (description is canonical; content is a Phase-X²' alias)."
            )
        # Canonical-wins normalisation: when both are supplied, null the
        # alias so model_dump(exclude_none=True) emits only `description`
        # and downstream callers don't see a stale `content` value.
        if self.description is not None and self.content is not None:
            self.content = None
        return self


class ResolveCheckpointArgs(ProjectScopedArgs):
    """Resolve a checkpoint with a resolution + rationale.

    Phase-X²' drift fix: ``resolved_by`` is the narrower
    ``CheckpointResolvedByLit`` (``pi``/``brain``) — matches both
    ``rka/models/checkpoint.py`` ``CheckpointResolve.resolved_by`` and
    the DB CHECK on ``checkpoints.resolved_by`` (schema.sql line 156 +
    migration 015). The previously-used ``DecidedByLit`` included
    ``'executor'`` which would pass the typed surface but fail the DB
    CHECK at INSERT time (HTTP 500 instead of 422).
    """

    operation: Literal["resolve_checkpoint"] = "resolve_checkpoint"

    id: Annotated[
        str,
        Field(description="Checkpoint id (chk_*) to resolve."),
    ]
    resolution: Annotated[
        str,
        Field(description="Resolution text."),
    ]
    resolved_by: Annotated[
        CheckpointResolvedByLit,
        Field(description="Who resolved this (pi|brain). 'executor' is rejected by the DB CHECK."),
    ]

    rationale: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional rationale narrative.",
        ),
    ] = None
    create_decision: Annotated[
        Optional[bool],
        Field(
            default=False,
            description=(
                "If True, the resolution is also recorded as a Decision "
                "node with provenance back to the checkpoint."
            ),
        ),
    ] = False


class EvaluateGateArgs(ProjectScopedArgs):
    """Evaluate a gate with a verdict + notes."""

    operation: Literal["evaluate_gate"] = "evaluate_gate"

    gate_id: Annotated[
        str,
        Field(description="Gate id (typically chk_* for a gate-type checkpoint)."),
    ]
    verdict: Annotated[
        VerdictLit,
        Field(description="Gate verdict (go|kill|hold|recycle)."),
    ]
    notes: Annotated[
        str,
        Field(description="Evaluation notes."),
    ]

    assumption_status: Annotated[
        Optional[dict[str, Any]],
        Field(
            default=None,
            description=(
                "Optional per-assumption status dict (e.g., "
                "{'assumption_text': 'verified|refuted|untested'})."
            ),
        ),
    ] = None


# ---------------------------------------------------------------------------
# SESSION LIFECYCLE (2)
# ---------------------------------------------------------------------------


class ResetSessionArgs(UnscopedArgs):
    """Reset the in-process session tracker (UNSCOPED).

    Discriminator-only model.
    """

    operation: Literal["reset_session"] = "reset_session"


class SessionDigestArgs(ProjectScopedArgs):
    """Compact session summary (mutates session state)."""

    operation: Literal["session_digest"] = "session_digest"


# ---------------------------------------------------------------------------
# Batch C partial union (for the rka_execute discriminated union)
# ---------------------------------------------------------------------------

BatchCExecuteUnion = Annotated[
    Union[
        # Updates
        UpdateNoteArgs,
        UpdateDecisionArgs,
        UpdateLiteratureArgs,
        UpdateMissionArgs,
        UpdateStatusArgs,
        UpdateMissionStatusArgs,
        BulkUpdateArgs,
        SupersedeDecisionArgs,
        # Decision lifecycle
        PresentDecisionArgs,
        RecordPiSelectionArgs,
        RecordOutcomeArgs,
        # Literature lifecycle
        EnrichDoiArgs,
        LinkLiteratureToZoteroArgs,
        ProcessPaperArgs,
        ValidateReferenceArgs,
        # Mission lifecycle
        SubmitReportArgs,
        AdvanceRqArgs,
        # Checkpoint lifecycle
        SubmitCheckpointArgs,
        ResolveCheckpointArgs,
        EvaluateGateArgs,
        # Session lifecycle
        ResetSessionArgs,
        SessionDigestArgs,
    ],
    Field(discriminator="operation"),
]


# =============================================================================
# Final ExecuteArgsUnion — composes B + C + D (49 models total)
# =============================================================================
#
# Phase 3 assembly: the discriminated union for `rka_execute`. FastMCP
# renders this as `oneOf` with per-branch enum + required arrays. The
# discriminator field (`operation: Literal['<op_name>']`) is the sole
# union key.

ExecuteArgsUnion = Annotated[
    Union[
        # ===== Batch B — RECORD/CREATE (13) =====
        RecordNoteArgs,
        IngestDocumentArgs,
        RecordDecisionArgs,
        RecordLiteratureArgs,
        ImportBibtexArgs,
        BatchImportArgs,
        RegisterManuscriptArgs,
        CreateMissionArgs,
        CreateClusterArgs,
        CreateProjectArgs,
        CreateGateArgs,
        HookAddArgs,
        ExtractClaimsArgs,
        # ===== Batch C — UPDATE/LIFECYCLE/SUBMIT (22) =====
        UpdateNoteArgs,
        UpdateDecisionArgs,
        UpdateLiteratureArgs,
        UpdateMissionArgs,
        UpdateStatusArgs,
        UpdateMissionStatusArgs,
        BulkUpdateArgs,
        SupersedeDecisionArgs,
        PresentDecisionArgs,
        RecordPiSelectionArgs,
        RecordOutcomeArgs,
        EnrichDoiArgs,
        LinkLiteratureToZoteroArgs,
        ProcessPaperArgs,
        ValidateReferenceArgs,
        SubmitReportArgs,
        AdvanceRqArgs,
        SubmitCheckpointArgs,
        ResolveCheckpointArgs,
        EvaluateGateArgs,
        ResetSessionArgs,
        SessionDigestArgs,
        # ===== Batch D — REVIEW/MAINT/HOOKS/WORKSPACE (14) =====
        AssignClaimsToClusterArgs,
        SplitClusterArgs,
        MergeClustersArgs,
        ReviewClaimsArgs,
        ReviewClusterArgs,
        ResolveContradictionArgs,
        HookEnableArgs,
        HookDisableArgs,
        HookDeleteArgs,
        BrainNotificationsClearArgs,
        BootstrapWorkspaceArgs,
        ScanWorkspaceArgs,
        FlagStaleArgs,
        EvictionSweepArgs,
    ],
    Field(discriminator="operation"),
]


__all__ = [
    # Bases
    "ProjectScopedArgs",
    "UnscopedArgs",
    "PaginatedFiltersMixin",
    # Batch A — Query models
    "QueryStatusArgs",
    "QueryContextArgs",
    "QuerySearchArgs",
    "QueryEntityArgs",
    "QueryJournalArgs",
    "QueryLiteratureArgs",
    "QueryMissionArgs",
    "QueryReportArgs",
    "QueryCheckpointsArgs",
    "QueryDecisionTreeArgs",
    "QueryCalibrationMetricsArgs",
    "QueryHooksArgs",
    "QueryHookExecutionsArgs",
    "QueryBrainNotificationsArgs",
    "QueryResearchMapArgs",
    "QueryReviewQueueArgs",
    "QueryClustersArgs",
    "QueryClaimsArgs",
    "QueryManuscriptArgs",
    "QueryGraphArgs",
    "QueryEgoGraphArgs",
    "QueryGraphStatsArgs",
    "QueryGraphMermaidArgs",
    "QueryProvenanceArgs",
    "QueryMultiHopArgs",
    "QueryCollectReportContextArgs",
    "QueryStalenessImpactArgs",
    "QueryMissionGuardArgs",
    "QueryBeliefAsOfArgs",
    "QuerySummarizeArgs",
    "QueryGenerateSummaryArgs",
    "QueryEvidenceArgs",
    "QueryFreshnessArgs",
    "QueryContradictionsArgs",
    "QueryIntegrityArgs",
    "QueryPendingMaintenanceArgs",
    "QueryChangelogArgs",
    "QueryBootstrapReviewArgs",
    "QueryWorkspaceTreeArgs",
    "QueryWorkspaceScanArgs",
    "QueryListProjectsArgs",
    "QueryHealthArgs",
    # Union
    "QueryArgsUnion",
    # Batch B — Record/Create write models
    "RecordNoteArgs",
    "IngestDocumentArgs",
    "RecordDecisionArgs",
    "RecordLiteratureArgs",
    "ImportBibtexArgs",
    "BatchImportArgs",
    "RegisterManuscriptArgs",
    "CreateMissionArgs",
    "CreateClusterArgs",
    "CreateProjectArgs",
    "CreateGateArgs",
    "HookAddArgs",
    "ExtractClaimsArgs",
    # Batch B partial union
    "BatchBExecuteUnion",
    # Batch D — Review / Maintenance / Hooks / Workspace write models
    "AssignClaimsToClusterArgs",
    "SplitClusterArgs",
    "MergeClustersArgs",
    "ReviewClaimsArgs",
    "ReviewClusterArgs",
    "ResolveContradictionArgs",
    "HookEnableArgs",
    "HookDisableArgs",
    "HookDeleteArgs",
    "BrainNotificationsClearArgs",
    "BootstrapWorkspaceArgs",
    "ScanWorkspaceArgs",
    "FlagStaleArgs",
    "EvictionSweepArgs",
    # Batch D partial union
    "BatchDExecuteUnion",
    # Batch C — UPDATE / LIFECYCLE / SUBMIT write models
    "UpdateNoteArgs",
    "UpdateDecisionArgs",
    "UpdateLiteratureArgs",
    "UpdateMissionArgs",
    "UpdateStatusArgs",
    "UpdateMissionStatusArgs",
    "BulkUpdateArgs",
    "SupersedeDecisionArgs",
    "PresentDecisionArgs",
    "RecordPiSelectionArgs",
    "RecordOutcomeArgs",
    "EnrichDoiArgs",
    "LinkLiteratureToZoteroArgs",
    "ProcessPaperArgs",
    "ValidateReferenceArgs",
    "SubmitReportArgs",
    "AdvanceRqArgs",
    "SubmitCheckpointArgs",
    "ResolveCheckpointArgs",
    "EvaluateGateArgs",
    "ResetSessionArgs",
    "SessionDigestArgs",
    # Batch C partial union
    "BatchCExecuteUnion",
    # Final execute union
    "ExecuteArgsUnion",
]
