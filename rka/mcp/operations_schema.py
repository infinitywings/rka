"""v2.7.0a3 — OPERATIONS_SCHEMA for rka_describe.

The single source of truth for the schema-lookup surface that pairs with
the rka_query / rka_execute always-on verbs. Each entry documents one
operation that the LLM can pass to either rka_query(operation=...) or
rka_execute(operation=...) (or, in this PR, one of the legacy v2.7.0a2
verbs while they remain callable).

Schema for one entry::

    {
        "operation":            str   # canonical operation name
        "tool":                 str   # 'rka_query' | 'rka_execute'
        "category":             str   # 'journal' | 'decision' | ...
        "summary":              str   # one-line "what this does"
        "signature":            str   # human-readable call shape
        "required_fields":      list[str]
        "optional_fields":      list[str]
        "enums":                dict[str, list[str]]
        "examples":             list[{"description": str, "call": dict}]
        "related_operations":   list[str]  # cross-references
        "role_tag":             str   # 'BRAIN' | 'EXECUTOR' | 'PI' | 'ANY'
        "notes":                str | None  # optional pitfall/guidance
    }

Design choices (decision #3 in the project locked-decisions list):

- Hand-curated, NOT reflection-derived. Reflection from Pydantic models +
  function signatures loses the role-tag guidance, the cross-operation
  hints, and the Phase-X²' canonical-field-name lessons (e.g. the
  `description=` vs `content=` checkpoint pitfall from the 2026-06-01
  hyperscaler-auditing PA-2 bug).
- Single dict, one entry per operation. Total ~85 entries.
- Enum value-sets reference rka.mcp._enums for drift-detection — the
  enums dict here cites the values directly (mirror of _enums.py) so
  consumers don't need to import _enums. The lock-test in
  tests/test_mcp/ pins them.
- Examples demonstrate canonical field names (the names operators
  empirically get wrong) and provenance shapes (related_journal,
  motivated_by_decision, verbatim_input).

This module is consumed by ``rka.mcp.server.rka_describe`` and by the
lock-tests in tests/test_mcp/test_v270a3_describe.py.
"""

from __future__ import annotations

import difflib
import json
from typing import Any


# ---------------------------------------------------------------------------
# Enum value sets — kept in sync with rka/mcp/_enums.py
# ---------------------------------------------------------------------------

_ENUMS = {
    "confidence": [
        "hypothesis", "tested", "verified", "superseded", "retracted",
    ],
    "importance": [
        "critical", "high", "normal", "low", "archived",
    ],
    "source": ["brain", "executor", "pi", "web_ui", "llm"],
    "note_type": [
        "note", "log", "directive",
        "finding", "insight", "pi_instruction", "exploration",
        "idea", "observation", "hypothesis", "methodology", "summary",
    ],
    "decided_by": ["pi", "brain", "executor"],
    "decision_kind": [
        "research_question", "design_choice", "decision", "operational",
    ],
    "lit_status": ["to_read", "reading", "read", "cited", "excluded"],
    "lit_added_by": ["brain", "executor", "pi", "import", "web_ui"],
    "mission_status": [
        "pending", "active", "complete", "partial", "blocked", "cancelled",
    ],
    "checkpoint_type": [
        "decision", "clarification", "inspection", "gate",
    ],
    "gate_type": [
        "problem_framing", "plan_validation", "evidence_review",
        "synthesis_validation",
    ],
    "verdict": ["go", "kill", "hold", "recycle"],
    "claim_type": [
        "hypothesis", "evidence", "method", "result", "observation",
        "assumption",
    ],
    "cluster_confidence": [
        "strong", "moderate", "emerging", "contested", "refuted",
    ],
    "rq_status": [
        "open", "partially_answered", "answered", "reframed", "closed",
    ],
    "outcome": ["succeeded", "failed", "mixed", "unresolved"],
    "staleness": ["yellow", "red"],
    "ingest_source": ["brain", "executor", "pi", "import", "web_ui"],
    "resolved_by": ["pi", "brain", "executor"],
    "review_action": ["approve", "reject", "adjust"],
}


def _e(*names: str) -> dict[str, list[str]]:
    """Build a sub-enum dict from named entries in ``_ENUMS``."""
    return {n: list(_ENUMS[n]) for n in names}


# ---------------------------------------------------------------------------
# OPERATIONS_SCHEMA — the curated table.
# ---------------------------------------------------------------------------
#
# Operation name keys MUST match the canonical sets in the project
# locked-decisions taxonomy. Drift between this table and the v2.7.0a3
# rka_query/rka_execute Literal enums is detected by the lock-tests.

OPERATIONS_SCHEMA: dict[str, dict[str, Any]] = {

    # =====================================================================
    # rka_query — read operations
    # =====================================================================

    "status": {
        "operation": "status",
        "tool": "rka_query",
        "category": "core",
        "role_tag": "ANY",
        "summary": "Current phase, focus, blockers — the minimal session-start probe.",
        "signature": "rka_query(operation='status', *, project_id)",
        "required_fields": ["project_id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Standard session-start status probe.",
                "call": {"operation": "status", "project_id": "prj_01ABC..."},
            },
        ],
        "related_operations": ["context", "pending_maintenance", "checkpoints"],
        "notes": None,
    },

    "context": {
        "operation": "context",
        "tool": "rka_query",
        "category": "core",
        "role_tag": "ANY",
        "summary": "Load current project state + recent knowledge for a topic.",
        "signature": (
            "rka_query(operation='context', *, project_id, query=None, "
            "filters={'phase': str}, options={'depth': 'summary'|'detailed'})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["query", "filters", "options"],
        "enums": {"depth": ["summary", "detailed"]},
        "examples": [
            {
                "description": "Pull current project context.",
                "call": {"operation": "context", "project_id": "prj_01ABC..."},
            },
            {
                "description": "Topic-scoped detailed context.",
                "call": {
                    "operation": "context",
                    "project_id": "prj_01ABC...",
                    "query": "RAG benchmark methodology",
                    "options": {"depth": "detailed"},
                },
            },
        ],
        "related_operations": ["status", "summarize", "search"],
        "notes": None,
    },

    "search": {
        "operation": "search",
        "tool": "rka_query",
        "category": "core",
        "role_tag": "ANY",
        "summary": "Full-text + semantic search across journal/decision/literature/clusters.",
        "signature": (
            "rka_query(operation='search', *, project_id, query, "
            "limit=20, filters={'entity_types': [str]})"
        ),
        "required_fields": ["project_id", "query"],
        "optional_fields": ["limit", "filters"],
        "enums": {
            "entity_types": [
                "journal", "decision", "literature", "mission",
                "claim", "cluster", "checkpoint",
            ],
        },
        "examples": [
            {
                "description": "Search 2-4 keyword terms.",
                "call": {
                    "operation": "search",
                    "project_id": "prj_01ABC...",
                    "query": "RAG retrieval latency",
                    "limit": 20,
                },
            },
        ],
        "related_operations": ["multi_hop", "context", "entity"],
        "notes": "Pass 2-4 keyword terms; longer queries reduce recall.",
    },

    "entity": {
        "operation": "entity",
        "tool": "rka_query",
        "category": "core",
        "role_tag": "ANY",
        "summary": "Fetch a single entity by ID (jrn_/dec_/lit_/mis_/clm_/ecl_/chk_).",
        "signature": "rka_query(operation='entity', *, project_id, id)",
        "required_fields": ["project_id", "id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Fetch a decision by ID.",
                "call": {
                    "operation": "entity",
                    "project_id": "prj_01ABC...",
                    "id": "dec_01XYZ...",
                },
            },
        ],
        "related_operations": ["provenance", "search"],
        "notes": "Entity prefix is auto-routed (jrn_, dec_, lit_, mis_, clm_, ecl_, chk_).",
    },

    "journal": {
        "operation": "journal",
        "tool": "rka_query",
        "category": "journal",
        "role_tag": "ANY",
        "summary": "List journal entries (notes, logs, directives).",
        "signature": (
            "rka_query(operation='journal', *, project_id, limit=20, "
            "filters={'type', 'phase', 'confidence', 'status', 'since', 'source', 'tags'})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["limit", "filters"],
        "enums": _e("note_type", "confidence", "source"),
        "examples": [
            {
                "description": "Recent journal entries.",
                "call": {
                    "operation": "journal",
                    "project_id": "prj_01ABC...",
                    "limit": 20,
                },
            },
            {
                "description": "Only verified findings.",
                "call": {
                    "operation": "journal",
                    "project_id": "prj_01ABC...",
                    "filters": {"confidence": "verified"},
                },
            },
        ],
        "related_operations": ["entity", "search", "record_note"],
        "notes": None,
    },

    "literature": {
        "operation": "literature",
        "tool": "rka_query",
        "category": "literature",
        "role_tag": "ANY",
        "summary": "List literature entries.",
        "signature": (
            "rka_query(operation='literature', *, project_id, query=None, "
            "limit=20, filters={'status', 'tag'})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["query", "limit", "filters"],
        "enums": _e("lit_status"),
        "examples": [
            {
                "description": "List to-read papers.",
                "call": {
                    "operation": "literature",
                    "project_id": "prj_01ABC...",
                    "filters": {"status": "to_read"},
                },
            },
        ],
        "related_operations": ["entity", "record_literature"],
        "notes": None,
    },

    "mission": {
        "operation": "mission",
        "tool": "rka_query",
        "category": "mission",
        "role_tag": "ANY",
        "summary": "Fetch a specific mission (by ID) or the current active/pending mission.",
        "signature": "rka_query(operation='mission', *, project_id, id=None)",
        "required_fields": ["project_id"],
        "optional_fields": ["id"],
        "enums": {},
        "examples": [
            {
                "description": "Get current active/pending mission.",
                "call": {"operation": "mission", "project_id": "prj_01ABC..."},
            },
            {
                "description": "Get a specific mission by ID.",
                "call": {
                    "operation": "mission",
                    "project_id": "prj_01ABC...",
                    "id": "mis_01XYZ...",
                },
            },
        ],
        "related_operations": ["report", "create_mission", "update_mission"],
        "notes": "Omit `id` to auto-locate the most recent active or pending mission.",
    },

    "report": {
        "operation": "report",
        "tool": "rka_query",
        "category": "mission",
        "role_tag": "ANY",
        "summary": "Fetch a mission's submitted report.",
        "signature": "rka_query(operation='report', *, project_id, id)",
        "required_fields": ["project_id", "id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Get a mission's report.",
                "call": {
                    "operation": "report",
                    "project_id": "prj_01ABC...",
                    "id": "mis_01XYZ...",
                },
            },
        ],
        "related_operations": ["mission", "submit_report"],
        "notes": "`id` is the mission_id, not a report_id.",
    },

    "checkpoints": {
        "operation": "checkpoints",
        "tool": "rka_query",
        "category": "checkpoint",
        "role_tag": "ANY",
        "summary": "List checkpoints (default: open).",
        "signature": (
            "rka_query(operation='checkpoints', *, project_id, "
            "filters={'status': 'open'|'resolved'|'all'})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["filters"],
        "enums": {"status": ["open", "resolved", "all"]},
        "examples": [
            {
                "description": "List open checkpoints.",
                "call": {
                    "operation": "checkpoints",
                    "project_id": "prj_01ABC...",
                    "filters": {"status": "open"},
                },
            },
        ],
        "related_operations": [
            "submit_checkpoint", "resolve_checkpoint", "entity",
        ],
        "notes": None,
    },

    "decision_tree": {
        "operation": "decision_tree",
        "tool": "rka_query",
        "category": "decision",
        "role_tag": "ANY",
        "summary": "Render the decision tree, optionally rooted at a decision.",
        "signature": (
            "rka_query(operation='decision_tree', *, project_id, id=None, "
            "filters={'phase', 'active_only'})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["id", "filters"],
        "enums": {},
        "examples": [
            {
                "description": "Full active decision tree.",
                "call": {
                    "operation": "decision_tree",
                    "project_id": "prj_01ABC...",
                    "filters": {"active_only": True},
                },
            },
        ],
        "related_operations": ["entity", "graph", "research_map"],
        "notes": None,
    },

    "calibration_metrics": {
        "operation": "calibration_metrics",
        "tool": "rka_query",
        "category": "calibration",
        "role_tag": "BRAIN",
        "summary": "Aggregate calibration outcomes for decisions you've made.",
        "signature": "rka_query(operation='calibration_metrics', *, project_id)",
        "required_fields": ["project_id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Fetch project-wide calibration stats.",
                "call": {
                    "operation": "calibration_metrics",
                    "project_id": "prj_01ABC...",
                },
            },
        ],
        "related_operations": ["record_outcome"],
        "notes": None,
    },

    "hooks": {
        "operation": "hooks",
        "tool": "rka_query",
        "category": "hooks",
        "role_tag": "ANY",
        "summary": "List configured hooks.",
        "signature": (
            "rka_query(operation='hooks', *, project_id, "
            "filters={'event', 'enabled_only'})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["filters"],
        "enums": {},
        "examples": [
            {
                "description": "List all hooks.",
                "call": {"operation": "hooks", "project_id": "prj_01ABC..."},
            },
        ],
        "related_operations": [
            "hook_executions", "hook_add", "hook_enable", "hook_disable",
        ],
        "notes": None,
    },

    "hook_executions": {
        "operation": "hook_executions",
        "tool": "rka_query",
        "category": "hooks",
        "role_tag": "ANY",
        "summary": "Recent hook execution history.",
        "signature": (
            "rka_query(operation='hook_executions', *, project_id, limit=100, "
            "filters={'hook_id', 'since', 'status'})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["limit", "filters"],
        "enums": {},
        "examples": [
            {
                "description": "Last 100 executions.",
                "call": {
                    "operation": "hook_executions",
                    "project_id": "prj_01ABC...",
                },
            },
        ],
        "related_operations": ["hooks"],
        "notes": None,
    },

    "brain_notifications": {
        "operation": "brain_notifications",
        "tool": "rka_query",
        "category": "notifications",
        "role_tag": "BRAIN",
        "summary": "Notifications queued for the Brain.",
        "signature": (
            "rka_query(operation='brain_notifications', *, project_id, "
            "limit=100, filters={'since', 'include_cleared'})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["limit", "filters"],
        "enums": {},
        "examples": [
            {
                "description": "Outstanding notifications.",
                "call": {
                    "operation": "brain_notifications",
                    "project_id": "prj_01ABC...",
                },
            },
        ],
        "related_operations": ["brain_notifications_clear"],
        "notes": None,
    },

    "research_map": {
        "operation": "research_map",
        "tool": "rka_query",
        "category": "research_map",
        "role_tag": "ANY",
        "summary": "Top-level research map: RQs -> clusters -> claims with synthesis.",
        "signature": "rka_query(operation='research_map', *, project_id)",
        "required_fields": ["project_id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Render the research map.",
                "call": {
                    "operation": "research_map",
                    "project_id": "prj_01ABC...",
                },
            },
        ],
        "related_operations": ["clusters", "claims", "decision_tree"],
        "notes": None,
    },

    "review_queue": {
        "operation": "review_queue",
        "tool": "rka_query",
        "category": "review",
        "role_tag": "BRAIN",
        "summary": "Pending review items (claims, clusters needing synthesis, etc.).",
        "signature": (
            "rka_query(operation='review_queue', *, project_id, limit=20, "
            "filters={'status': 'pending'|'reviewed'|'all', 'target_type'})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["limit", "filters"],
        "enums": {"status": ["pending", "reviewed", "all"]},
        "examples": [
            {
                "description": "Pending review items.",
                "call": {
                    "operation": "review_queue",
                    "project_id": "prj_01ABC...",
                    "filters": {"status": "pending"},
                },
            },
        ],
        "related_operations": ["review_claims", "review_cluster"],
        "notes": None,
    },

    "clusters": {
        "operation": "clusters",
        "tool": "rka_query",
        "category": "claims",
        "role_tag": "ANY",
        "summary": "List evidence clusters.",
        "signature": (
            "rka_query(operation='clusters', *, project_id, limit=50, "
            "filters={'research_question_id', 'confidence'})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["limit", "filters"],
        "enums": _e("cluster_confidence"),
        "examples": [
            {
                "description": "Strong-confidence clusters.",
                "call": {
                    "operation": "clusters",
                    "project_id": "prj_01ABC...",
                    "filters": {"confidence": "strong"},
                },
            },
        ],
        "related_operations": [
            "claims", "create_cluster", "review_cluster",
            "assign_claims_to_cluster",
        ],
        "notes": None,
    },

    "claims": {
        "operation": "claims",
        "tool": "rka_query",
        "category": "claims",
        "role_tag": "ANY",
        "summary": "List claims.",
        "signature": (
            "rka_query(operation='claims', *, project_id, limit=20, "
            "filters={'source_entry_id', 'cluster_id', 'claim_type', "
            "'verified', 'stale'})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["limit", "filters"],
        "enums": _e("claim_type"),
        "examples": [
            {
                "description": "Claims from a journal entry.",
                "call": {
                    "operation": "claims",
                    "project_id": "prj_01ABC...",
                    "filters": {"source_entry_id": "jrn_01XYZ..."},
                },
            },
        ],
        "related_operations": [
            "clusters", "extract_claims", "review_claims",
        ],
        "notes": None,
    },

    "manuscript": {
        "operation": "manuscript",
        "tool": "rka_query",
        "category": "manuscript",
        "role_tag": "ANY",
        "summary": "Fetch a registered manuscript.",
        "signature": "rka_query(operation='manuscript', *, project_id, id)",
        "required_fields": ["project_id", "id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Fetch by manuscript id.",
                "call": {
                    "operation": "manuscript",
                    "project_id": "prj_01ABC...",
                    "id": "msc_01XYZ...",
                },
            },
        ],
        "related_operations": ["register_manuscript"],
        "notes": None,
    },

    "graph": {
        "operation": "graph",
        "tool": "rka_query",
        "category": "graph",
        "role_tag": "ANY",
        "summary": "Subset of the research-knowledge graph (nodes + edges).",
        "signature": (
            "rka_query(operation='graph', *, project_id, limit=500, "
            "filters={'include_types', 'phase'})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["limit", "filters"],
        "enums": {},
        "examples": [
            {
                "description": "Decision/journal subgraph.",
                "call": {
                    "operation": "graph",
                    "project_id": "prj_01ABC...",
                    "filters": {"include_types": ["decision", "journal"]},
                },
            },
        ],
        "related_operations": [
            "ego_graph", "graph_stats", "graph_mermaid",
        ],
        "notes": None,
    },

    "ego_graph": {
        "operation": "ego_graph",
        "tool": "rka_query",
        "category": "graph",
        "role_tag": "ANY",
        "summary": "Local neighborhood graph centered on one entity.",
        "signature": (
            "rka_query(operation='ego_graph', *, project_id, id, "
            "filters={'depth': int})"
        ),
        "required_fields": ["project_id", "id"],
        "optional_fields": ["filters"],
        "enums": {},
        "examples": [
            {
                "description": "1-hop neighborhood of a decision.",
                "call": {
                    "operation": "ego_graph",
                    "project_id": "prj_01ABC...",
                    "id": "dec_01XYZ...",
                    "filters": {"depth": 1},
                },
            },
        ],
        "related_operations": ["graph", "provenance"],
        "notes": None,
    },

    "graph_stats": {
        "operation": "graph_stats",
        "tool": "rka_query",
        "category": "graph",
        "role_tag": "ANY",
        "summary": "Top-level node/edge counts.",
        "signature": "rka_query(operation='graph_stats', *, project_id)",
        "required_fields": ["project_id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Project graph cardinality.",
                "call": {
                    "operation": "graph_stats",
                    "project_id": "prj_01ABC...",
                },
            },
        ],
        "related_operations": ["graph"],
        "notes": None,
    },

    "graph_mermaid": {
        "operation": "graph_mermaid",
        "tool": "rka_query",
        "category": "graph",
        "role_tag": "ANY",
        "summary": "Render the decision tree as Mermaid graph syntax.",
        "signature": (
            "rka_query(operation='graph_mermaid', *, project_id, "
            "filters={'phase', 'active_only'})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["filters"],
        "enums": {},
        "examples": [
            {
                "description": "Active-only decision tree as Mermaid.",
                "call": {
                    "operation": "graph_mermaid",
                    "project_id": "prj_01ABC...",
                    "filters": {"active_only": True},
                },
            },
        ],
        "related_operations": ["graph", "decision_tree"],
        "notes": None,
    },

    "provenance": {
        "operation": "provenance",
        "tool": "rka_query",
        "category": "graph",
        "role_tag": "ANY",
        "summary": "Trace the reasoning chain that produced an entity.",
        "signature": (
            "rka_query(operation='provenance', *, project_id, id, "
            "filters={'direction': 'forward'|'backward'|'both', 'max_depth'})"
        ),
        "required_fields": ["project_id", "id"],
        "optional_fields": ["filters"],
        "enums": {"direction": ["forward", "backward", "both"]},
        "examples": [
            {
                "description": "Trace what justifies a decision.",
                "call": {
                    "operation": "provenance",
                    "project_id": "prj_01ABC...",
                    "id": "dec_01XYZ...",
                    "filters": {"direction": "backward"},
                },
            },
        ],
        "related_operations": ["ego_graph", "entity"],
        "notes": None,
    },

    "multi_hop": {
        "operation": "multi_hop",
        "tool": "rka_query",
        "category": "graph",
        "role_tag": "BRAIN",
        "summary": "Multi-hop graph retrieval seeded by query or explicit seed IDs.",
        "signature": (
            "rka_query(operation='multi_hop', *, project_id, query, "
            "filters={'seeds', 'max_depth', 'max_nodes', 'edge_weights'})"
        ),
        "required_fields": ["project_id", "query"],
        "optional_fields": ["filters"],
        "enums": {},
        "examples": [
            {
                "description": "Retrieve a topic-relevant subgraph.",
                "call": {
                    "operation": "multi_hop",
                    "project_id": "prj_01ABC...",
                    "query": "embedding-model selection rationale",
                    "filters": {"max_depth": 3, "max_nodes": 50},
                },
            },
        ],
        "related_operations": ["search", "provenance"],
        "notes": "Pass `filters.seeds=[...]` to override the query-based seeding.",
    },

    "collect_report_context": {
        "operation": "collect_report_context",
        "tool": "rka_query",
        "category": "graph",
        "role_tag": "ANY",
        "summary": (
            "Collect the node set relevant to a report described in prose — "
            "multi-angle search seeding + link-graph expansion with seed "
            "protection and per-node inclusion provenance."
        ),
        "signature": (
            "rka_query(operation='collect_report_context', *, project_id, "
            "query, filters={'angle_queries', 'max_depth', 'max_nodes', "
            "'seed_limit'})"
        ),
        "required_fields": ["project_id", "query"],
        "optional_fields": ["filters"],
        "enums": {},
        "examples": [
            {
                "description": (
                    "Assemble report context with angle decomposition "
                    "(ALWAYS provide angle_queries — short 1-4 word queries "
                    "from different angles of the description)."
                ),
                "call": {
                    "operation": "collect_report_context",
                    "project_id": "prj_01ABC...",
                    "query": (
                        "Report on how the embedding stack became pluggable: "
                        "motivation, backends, config persistence, dimension "
                        "fix, bugs found"
                    ),
                    "filters": {
                        "angle_queries": [
                            "pluggable embeddings", "fastembed",
                            "embedding config", "dimension mismatch",
                        ],
                        "max_depth": 2, "max_nodes": 60,
                    },
                },
            },
        ],
        "related_operations": ["multi_hop", "search", "ego_graph"],
        "notes": (
            "Each returned node carries `included_via` (angle query + rank, "
            "or parent + link_type) so the bundle is auditable. Follow up: "
            "verify borderline nodes by content, re-search thin dimensions."
        ),
    },

    "staleness_impact": {
        "operation": "staleness_impact",
        "tool": "rka_query",
        "category": "graph",
        "role_tag": "ANY",
        "summary": (
            "Downstream blast-radius of a stale entity: everything whose "
            "reasoning rests on it, via dependent-direction links."
        ),
        "signature": (
            "rka_query(operation='staleness_impact', *, project_id, id, "
            "filters={'max_depth': 3})"
        ),
        "required_fields": ["project_id", "id"],
        "optional_fields": ["filters"],
        "enums": {},
        "examples": [
            {
                "description": "What rests on a decision about to be superseded?",
                "call": {
                    "operation": "staleness_impact",
                    "project_id": "prj_01ABC...",
                    "id": "dec_01ABC...",
                },
            },
        ],
        "related_operations": ["ego_graph", "multi_hop", "freshness"],
        "notes": "Raw observations (produced links) are immutable and excluded.",
    },

    "mission_guard": {
        "operation": "mission_guard",
        "tool": "rka_query",
        "category": "mission",
        "role_tag": "EXECUTOR",
        "summary": (
            "Negative knowledge for mission pickup: retracted/superseded "
            "findings and unresolved contradictions relevant to the objective."
        ),
        "signature": "rka_query(operation='mission_guard', *, project_id, id)",
        "required_fields": ["project_id", "id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Guard check at mission pickup.",
                "call": {
                    "operation": "mission_guard",
                    "project_id": "prj_01ABC...",
                    "id": "mis_01ABC...",
                },
            },
        ],
        "related_operations": ["mission", "context", "contradictions"],
        "notes": "Call alongside mission context; warnings list approaches already falsified.",
    },

    "belief_as_of": {
        "operation": "belief_as_of",
        "tool": "rka_query",
        "category": "graph",
        "role_tag": "ANY",
        "summary": (
            "Reconstruct the believed-current decisions and journal at a past "
            "date, plus what changed since."
        ),
        "signature": "rka_query(operation='belief_as_of', *, project_id, query='<ISO date>')",
        "required_fields": ["project_id", "query"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "What did we believe in mid-March?",
                "call": {
                    "operation": "belief_as_of",
                    "project_id": "prj_01ABC...",
                    "query": "2026-03-15",
                },
            },
        ],
        "related_operations": ["changelog", "staleness_impact"],
        "notes": (
            "Supersession transitions are exact (successor created_at); "
            "retraction transitions are approximated by updated_at."
        ),
    },

    "summarize": {
        "operation": "summarize",
        "tool": "rka_query",
        "category": "summary",
        "role_tag": "ANY",
        "summary": "Topic-scoped summarization across the knowledge graph.",
        "signature": (
            "rka_query(operation='summarize', *, project_id, query=None, "
            "filters={'topic', 'phase', 'entity_ids'})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["query", "filters"],
        "enums": {},
        "examples": [
            {
                "description": "Summarize a topic.",
                "call": {
                    "operation": "summarize",
                    "project_id": "prj_01ABC...",
                    "query": "RAG latency findings",
                },
            },
        ],
        "related_operations": ["generate_summary", "context"],
        "notes": None,
    },

    "generate_summary": {
        "operation": "generate_summary",
        "tool": "rka_query",
        "category": "summary",
        "role_tag": "ANY",
        "summary": "Render a structured summary (project / mission / decision scope).",
        "signature": (
            "rka_query(operation='generate_summary', *, project_id, id=None, "
            "filters={'scope_type': 'project'|'mission'|'decision', "
            "'scope_id', 'granularity'})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["id", "filters"],
        "enums": {
            "scope_type": ["project", "mission", "decision"],
            "granularity": ["paragraph", "outline", "bullet_list"],
        },
        "examples": [
            {
                "description": "Project-scoped paragraph summary.",
                "call": {
                    "operation": "generate_summary",
                    "project_id": "prj_01ABC...",
                    "filters": {"scope_type": "project"},
                },
            },
        ],
        "related_operations": ["summarize"],
        "notes": (
            "v2.4.0 removed the LLM-driven path; this scope is a stub "
            "until it is rewired through the orchestrator."
        ),
    },

    "evidence": {
        "operation": "evidence",
        "tool": "rka_query",
        "category": "claims",
        "role_tag": "BRAIN",
        "summary": "Assemble structured evidence supporting a research question.",
        "signature": (
            "rka_query(operation='evidence', *, project_id, id, "
            "filters={'format': 'progress_report'|'briefing'|'audit'})"
        ),
        "required_fields": ["project_id", "id"],
        "optional_fields": ["filters"],
        "enums": {
            "format": ["progress_report", "briefing", "audit"],
        },
        "examples": [
            {
                "description": "Progress report for a RQ.",
                "call": {
                    "operation": "evidence",
                    "project_id": "prj_01ABC...",
                    "id": "dec_01XYZ...",
                    "filters": {"format": "progress_report"},
                },
            },
        ],
        "related_operations": ["clusters", "claims", "advance_rq"],
        "notes": "`id` is the research_question_id (stored as a decision id with kind='research_question').",
    },

    "freshness": {
        "operation": "freshness",
        "tool": "rka_query",
        "category": "maintenance",
        "role_tag": "BRAIN",
        "summary": "Check freshness/staleness of claims and clusters.",
        "signature": (
            "rka_query(operation='freshness', *, project_id, "
            "filters={'days_threshold': int})"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["filters"],
        "enums": {},
        "examples": [
            {
                "description": "Check 30-day freshness.",
                "call": {
                    "operation": "freshness",
                    "project_id": "prj_01ABC...",
                    "filters": {"days_threshold": 30},
                },
            },
        ],
        "related_operations": ["flag_stale", "pending_maintenance"],
        "notes": None,
    },

    "contradictions": {
        "operation": "contradictions",
        "tool": "rka_query",
        "category": "maintenance",
        "role_tag": "BRAIN",
        "summary": "Detect contradicting evidence near a given entity.",
        "signature": (
            "rka_query(operation='contradictions', *, project_id, id, "
            "filters={'similarity_threshold': float, 'max_results': int})"
        ),
        "required_fields": ["project_id", "id"],
        "optional_fields": ["filters"],
        "enums": {},
        "examples": [
            {
                "description": "Find contradictions near a claim.",
                "call": {
                    "operation": "contradictions",
                    "project_id": "prj_01ABC...",
                    "id": "clm_01XYZ...",
                },
            },
        ],
        "related_operations": ["resolve_contradiction"],
        "notes": None,
    },

    "integrity": {
        "operation": "integrity",
        "tool": "rka_query",
        "category": "maintenance",
        "role_tag": "BRAIN",
        "summary": "Database integrity probe (orphans, broken links).",
        "signature": "rka_query(operation='integrity', *, project_id)",
        "required_fields": ["project_id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Quick integrity scan.",
                "call": {
                    "operation": "integrity",
                    "project_id": "prj_01ABC...",
                },
            },
        ],
        "related_operations": ["pending_maintenance"],
        "notes": None,
    },

    "pending_maintenance": {
        "operation": "pending_maintenance",
        "tool": "rka_query",
        "category": "maintenance",
        "role_tag": "BRAIN",
        "summary": "Provenance gaps, untagged entries, orphans, etc.",
        "signature": "rka_query(operation='pending_maintenance', *, project_id)",
        "required_fields": ["project_id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "List maintenance work.",
                "call": {
                    "operation": "pending_maintenance",
                    "project_id": "prj_01ABC...",
                },
            },
        ],
        "related_operations": ["integrity", "freshness", "contradictions"],
        "notes": None,
    },

    "changelog": {
        "operation": "changelog",
        "tool": "rka_query",
        "category": "core",
        "role_tag": "ANY",
        "summary": "Project changelog since a given date.",
        "signature": (
            "rka_query(operation='changelog', *, project_id, limit=50, "
            "filters={'since': ISO8601})"
        ),
        "required_fields": ["project_id", "since"],
        "optional_fields": ["limit"],
        "enums": {},
        "examples": [
            {
                "description": "Recent changes.",
                "call": {
                    "operation": "changelog",
                    "project_id": "prj_01ABC...",
                    "filters": {"since": "2026-05-01"},
                },
            },
        ],
        "related_operations": ["status"],
        "notes": "`filters.since` is REQUIRED.",
    },

    "bootstrap_review": {
        "operation": "bootstrap_review",
        "tool": "rka_query",
        "category": "workspace",
        "role_tag": "ANY",
        "summary": "Review the proposed bootstrap result for a workspace scan.",
        "signature": "rka_query(operation='bootstrap_review', *, project_id, id)",
        "required_fields": ["project_id", "id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Review a scan's bootstrap proposal.",
                "call": {
                    "operation": "bootstrap_review",
                    "project_id": "prj_01ABC...",
                    "id": "scn_01XYZ...",
                },
            },
        ],
        "related_operations": ["bootstrap_workspace", "workspace_scan"],
        "notes": "`id` is the scan_id (scn_...).",
    },

    "workspace_tree": {
        "operation": "workspace_tree",
        "tool": "rka_query",
        "category": "workspace",
        "role_tag": "ANY",
        "summary": "Read-only file-tree probe of a workspace folder.",
        "signature": (
            "rka_query(operation='workspace_tree', *, project_id, "
            "filters={'folder_path': str, 'max_depth': int})"
        ),
        "required_fields": ["project_id", "folder_path"],
        "optional_fields": ["max_depth"],
        "enums": {},
        "examples": [
            {
                "description": "Shallow tree probe.",
                "call": {
                    "operation": "workspace_tree",
                    "project_id": "prj_01ABC...",
                    "filters": {
                        "folder_path": "/Users/me/Research/proj",
                        "max_depth": 2,
                    },
                },
            },
        ],
        "related_operations": ["workspace_scan"],
        "notes": None,
    },

    "workspace_scan": {
        "operation": "workspace_scan",
        "tool": "rka_query",
        "category": "workspace",
        "role_tag": "ANY",
        "summary": "Deep workspace scan (full file contents for ingestion).",
        "signature": (
            "rka_query(operation='workspace_scan', *, project_id, "
            "filters={'folder_path', 'ignore_patterns', "
            "'max_file_size_mb', 'use_llm'})"
        ),
        "required_fields": ["project_id", "folder_path"],
        "optional_fields": [
            "ignore_patterns", "max_file_size_mb", "use_llm",
        ],
        "enums": {},
        "examples": [
            {
                "description": "Scan a workspace.",
                "call": {
                    "operation": "workspace_scan",
                    "project_id": "prj_01ABC...",
                    "filters": {
                        "folder_path": "/Users/me/Research/proj",
                        "max_file_size_mb": 50,
                    },
                },
            },
        ],
        "related_operations": ["workspace_tree", "bootstrap_workspace"],
        "notes": None,
    },

    "list_projects": {
        "operation": "list_projects",
        "tool": "rka_query",
        "category": "session",
        "role_tag": "ANY",
        "summary": "List all available projects (UNSCOPED).",
        "signature": "rka_query(operation='list_projects')",
        "required_fields": [],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Discover available projects.",
                "call": {"operation": "list_projects"},
            },
        ],
        "related_operations": ["status", "create_project"],
        "notes": "UNSCOPED — does not require project_id.",
    },

    "health": {
        "operation": "health",
        "tool": "rka_query",
        "category": "session",
        "role_tag": "ANY",
        "summary": "API health probe (UNSCOPED).",
        "signature": "rka_query(operation='health')",
        "required_fields": [],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Probe API health.",
                "call": {"operation": "health"},
            },
        ],
        "related_operations": ["status"],
        "notes": "UNSCOPED.",
    },

    # =====================================================================
    # rka_execute — write/lifecycle operations
    # =====================================================================

    # --- journal / notes ------------------------------------------------

    "record_note": {
        "operation": "record_note",
        "tool": "rka_execute",
        "category": "journal",
        "role_tag": "ANY",
        "summary": "RECORD a journal entry (note, log, directive).",
        "signature": (
            "rka_execute(operation='record_note', *, project_id, content, "
            "source='executor', type='note', confidence='hypothesis', "
            "importance='normal', verbatim_input=None, phase=None, "
            "tags=None, provenance={'related_decisions':[...], "
            "'related_literature':[...], 'related_mission':..., "
            "'supersedes':...})"
        ),
        "required_fields": ["project_id", "content"],
        "optional_fields": [
            "source", "type", "confidence", "importance",
            "verbatim_input", "phase", "tags", "provenance",
        ],
        "enums": _e("source", "note_type", "confidence", "importance"),
        "examples": [
            {
                "description": "Executor records a finding linked to a mission.",
                "call": {
                    "operation": "record_note",
                    "project_id": "prj_01ABC...",
                    "content": "RAG p99 latency 2.3s on benchmark X.",
                    "type": "note",
                    "source": "executor",
                    "confidence": "tested",
                    "provenance": {"related_mission": "mis_01XYZ..."},
                },
            },
            {
                "description": "PI directive with verbatim input (REQUIRED when source='pi').",
                "call": {
                    "operation": "record_note",
                    "project_id": "prj_01ABC...",
                    "content": "PI: prioritise latency over recall.",
                    "type": "directive",
                    "source": "pi",
                    "verbatim_input": "Prioritise latency over recall.",
                },
            },
        ],
        "related_operations": [
            "update_note", "ingest_document", "record_decision",
        ],
        "notes": (
            "Phase-X²' rule: source='pi' REQUIRES verbatim_input. The "
            "verb rejects calls without it pre-flight."
        ),
    },

    "ingest_document": {
        "operation": "ingest_document",
        "tool": "rka_execute",
        "category": "journal",
        "role_tag": "ANY",
        "summary": "Ingest a markdown document into many journal entries.",
        "signature": (
            "rka_execute(operation='ingest_document', *, project_id, content, "
            "source='executor', default_type='finding', split_by_headings=True, "
            "phase=None, tags=None, provenance={...})"
        ),
        "required_fields": ["project_id", "content"],
        "optional_fields": [
            "source", "default_type", "split_by_headings",
            "phase", "tags", "provenance",
        ],
        "enums": _e("ingest_source", "note_type"),
        "examples": [
            {
                "description": "Ingest a markdown doc split by H1/H2.",
                "call": {
                    "operation": "ingest_document",
                    "project_id": "prj_01ABC...",
                    "content": "# Findings\n...\n## Anomalies\n...",
                    "split_by_headings": True,
                    "default_type": "finding",
                },
            },
        ],
        "related_operations": ["record_note", "batch_import"],
        "notes": None,
    },

    "update_note": {
        "operation": "update_note",
        "tool": "rka_execute",
        "category": "journal",
        "role_tag": "BRAIN",
        "summary": "Update a journal entry (content, type, confidence, links).",
        "signature": (
            "rka_execute(operation='update_note', *, project_id, id, "
            "content=None, type=None, confidence=None, importance=None, "
            "tags=None, phase=None, related_decisions=None, "
            "related_literature=None, related_mission=None)"
        ),
        "required_fields": ["project_id", "id"],
        "optional_fields": [
            "content", "type", "confidence", "importance",
            "tags", "phase", "verbatim_input", "source",
            "related_decisions", "related_literature", "related_mission",
        ],
        "enums": _e("confidence", "importance", "source", "note_type"),
        "examples": [
            {
                "description": "Promote a finding to verified.",
                "call": {
                    "operation": "update_note",
                    "project_id": "prj_01ABC...",
                    "id": "jrn_01XYZ...",
                    "confidence": "verified",
                },
            },
        ],
        "related_operations": ["record_note", "bulk_update"],
        "notes": None,
    },

    # --- decisions ------------------------------------------------------

    "record_decision": {
        "operation": "record_decision",
        "tool": "rka_execute",
        "category": "decision",
        "role_tag": "BRAIN",
        "summary": "RECORD a decision node. Provenance-required.",
        "signature": (
            "rka_execute(operation='record_decision', *, project_id, "
            "question, chosen, rationale, decided_by, kind, "
            "related_journal=[...], options=None, supersedes_decision_id=None, "
            "confidence='tested', tags=None, phase=None, parent_id=None, "
            "related_literature=None, assumptions=None)"
        ),
        "required_fields": [
            "project_id", "question", "chosen", "rationale",
            "decided_by", "kind", "related_journal",
        ],
        "optional_fields": [
            "options", "supersedes_decision_id", "confidence", "tags",
            "phase", "parent_id", "related_literature", "assumptions",
        ],
        "enums": _e("decided_by", "decision_kind", "confidence"),
        "examples": [
            {
                "description": "PI records a design choice with provenance.",
                "call": {
                    "operation": "record_decision",
                    "project_id": "prj_01ABC...",
                    "question": "Which embedding model for v2?",
                    "chosen": "nomic-embed-text-v1.5",
                    "rationale": "Best recall/latency tradeoff in benchmarks A, B.",
                    "decided_by": "pi",
                    "kind": "design_choice",
                    "related_journal": ["jrn_01XYZ...", "jrn_01ABC..."],
                },
            },
        ],
        "related_operations": [
            "update_decision", "supersede_decision", "present_decision",
            "record_pi_selection",
        ],
        "notes": (
            "Provenance discipline: related_journal MUST be non-empty. "
            "Common Brain hallucination: confidence='confirmed' is NOT "
            "valid; use 'verified' or 'tested'."
        ),
    },

    "update_decision": {
        "operation": "update_decision",
        "tool": "rka_execute",
        "category": "decision",
        "role_tag": "BRAIN",
        "summary": "Update fields on an existing decision.",
        "signature": (
            "rka_execute(operation='update_decision', *, project_id, id, "
            "status=None, chosen=None, rationale=None, kind=None, "
            "related_journal=None, parent_id=None, related_literature=None, "
            "related_missions=None, phase=None, tags=None, assumptions=None, "
            "abandonment_reason=None)"
        ),
        "required_fields": ["project_id", "id"],
        "optional_fields": [
            "status", "chosen", "rationale", "kind", "related_journal",
            "parent_id", "related_literature", "related_missions",
            "phase", "tags", "assumptions", "abandonment_reason",
        ],
        "enums": _e("decision_kind"),
        "examples": [
            {
                "description": "Update a decision's rationale.",
                "call": {
                    "operation": "update_decision",
                    "project_id": "prj_01ABC...",
                    "id": "dec_01XYZ...",
                    "rationale": "Refined after benchmark Y.",
                },
            },
        ],
        "related_operations": [
            "record_decision", "supersede_decision",
        ],
        "notes": None,
    },

    "supersede_decision": {
        "operation": "supersede_decision",
        "tool": "rka_execute",
        "category": "decision",
        "role_tag": "BRAIN",
        "summary": "Replace an old decision with a new one (atomically links the two).",
        "signature": (
            "rka_execute(operation='supersede_decision', *, project_id, "
            "old_decision_id, question, chosen, rationale, "
            "decided_by='brain', phase='', kind='decision')"
        ),
        "required_fields": [
            "project_id", "old_decision_id",
            "question", "chosen", "rationale",
        ],
        "optional_fields": ["decided_by", "phase", "kind"],
        "enums": _e("decided_by", "decision_kind"),
        "examples": [
            {
                "description": "Overturn a prior decision.",
                "call": {
                    "operation": "supersede_decision",
                    "project_id": "prj_01ABC...",
                    "old_decision_id": "dec_01OLD...",
                    "question": "Which embedding model for v2 (revised)?",
                    "chosen": "bge-m3",
                    "rationale": "New benchmarks reverse the prior choice.",
                    "decided_by": "brain",
                    "kind": "design_choice",
                },
            },
        ],
        "related_operations": ["record_decision", "update_decision"],
        "notes": (
            "Also reachable as rka_execute(operation='record_decision', "
            "supersedes_decision_id='dec_...')."
        ),
    },

    "present_decision": {
        "operation": "present_decision",
        "tool": "rka_execute",
        "category": "decision",
        "role_tag": "BRAIN",
        "summary": "Present a decision to the PI for ratification.",
        "signature": (
            "rka_execute(operation='present_decision', *, project_id, "
            "decision_id, confirmation_brief, options, pi_preference=None)"
        ),
        "required_fields": [
            "project_id", "decision_id", "confirmation_brief", "options",
        ],
        "optional_fields": ["pi_preference"],
        "enums": {},
        "examples": [
            {
                "description": "Brain presents a decision for PI selection.",
                "call": {
                    "operation": "present_decision",
                    "project_id": "prj_01ABC...",
                    "decision_id": "dec_01XYZ...",
                    "confirmation_brief": "Choose embedding model for v2.",
                    "options": [
                        {"id": "A", "label": "nomic-embed-v1.5"},
                        {"id": "B", "label": "bge-m3"},
                    ],
                },
            },
        ],
        "related_operations": ["record_pi_selection", "record_decision"],
        "notes": (
            "In orchestrator-driven flows, ratification is performed via "
            "the pi_decision_select interrupt (TWO-TAP gate), not via "
            "direct presentation."
        ),
    },

    "record_pi_selection": {
        "operation": "record_pi_selection",
        "tool": "rka_execute",
        "category": "decision",
        "role_tag": "PI",
        "summary": "Record the PI's selection on a presented decision.",
        "signature": (
            "rka_execute(operation='record_pi_selection', *, project_id, "
            "decision_id, selected_option_id=None, override_rationale=None)"
        ),
        "required_fields": ["project_id", "decision_id"],
        "optional_fields": ["selected_option_id", "override_rationale"],
        "enums": {},
        "examples": [
            {
                "description": "PI selects option B with rationale.",
                "call": {
                    "operation": "record_pi_selection",
                    "project_id": "prj_01ABC...",
                    "decision_id": "dec_01XYZ...",
                    "selected_option_id": "B",
                    "override_rationale": "B aligns with the latency budget.",
                },
            },
        ],
        "related_operations": ["present_decision"],
        "notes": None,
    },

    "record_outcome": {
        "operation": "record_outcome",
        "tool": "rka_execute",
        "category": "decision",
        "role_tag": "PI",
        "summary": "Record the calibration outcome of a past decision.",
        "signature": (
            "rka_execute(operation='record_outcome', *, project_id, "
            "decision_id, outcome, outcome_details=None, recorded_by='pi')"
        ),
        "required_fields": ["project_id", "decision_id", "outcome"],
        "optional_fields": ["outcome_details", "recorded_by"],
        "enums": _e("outcome"),
        "examples": [
            {
                "description": "Mark a decision succeeded with details.",
                "call": {
                    "operation": "record_outcome",
                    "project_id": "prj_01ABC...",
                    "decision_id": "dec_01XYZ...",
                    "outcome": "succeeded",
                    "outcome_details": "Latency budget met.",
                },
            },
        ],
        "related_operations": ["calibration_metrics", "record_decision"],
        "notes": None,
    },

    # --- literature -----------------------------------------------------

    "record_literature": {
        "operation": "record_literature",
        "tool": "rka_execute",
        "category": "literature",
        "role_tag": "ANY",
        "summary": "Add a literature entry (title-based create).",
        "signature": (
            "rka_execute(operation='record_literature', *, project_id, "
            "title, authors=None, year=None, venue=None, doi=None, "
            "url=None, abstract=None, status='to_read', tags=None, "
            "related_decisions=None)"
        ),
        "required_fields": ["project_id", "title"],
        "optional_fields": [
            "authors", "year", "venue", "doi", "url", "abstract",
            "status", "tags", "related_decisions",
        ],
        "enums": _e("lit_status"),
        "examples": [
            {
                "description": "Bootstrap a paper from title + DOI.",
                "call": {
                    "operation": "record_literature",
                    "project_id": "prj_01ABC...",
                    "title": "Attention Is All You Need",
                    "doi": "10.48550/arXiv.1706.03762",
                    "status": "to_read",
                },
            },
        ],
        "related_operations": [
            "update_literature", "import_bibtex", "enrich_doi",
            "link_literature_to_zotero",
        ],
        "notes": None,
    },

    "update_literature": {
        "operation": "update_literature",
        "tool": "rka_execute",
        "category": "literature",
        "role_tag": "BRAIN",
        "summary": "Update fields on a literature entry.",
        "signature": (
            "rka_execute(operation='update_literature', *, project_id, id, "
            "title=None, authors=None, year=None, venue=None, doi=None, "
            "url=None, bibtex=None, pdf_path=None, abstract=None, "
            "status=None, key_findings=None, methodology_notes=None, "
            "relevance=None, relevance_score=None, related_decisions=None, "
            "notes=None, tags=None)"
        ),
        "required_fields": ["project_id", "id"],
        "optional_fields": [
            "title", "authors", "year", "venue", "doi", "url",
            "bibtex", "pdf_path", "abstract", "status", "key_findings",
            "methodology_notes", "relevance", "relevance_score",
            "related_decisions", "notes", "tags",
        ],
        "enums": _e("lit_status"),
        "examples": [
            {
                "description": "Mark a paper as read with findings.",
                "call": {
                    "operation": "update_literature",
                    "project_id": "prj_01ABC...",
                    "id": "lit_01XYZ...",
                    "status": "read",
                    "key_findings": "Self-attention scales O(n^2).",
                },
            },
        ],
        "related_operations": ["record_literature", "process_paper"],
        "notes": None,
    },

    "import_bibtex": {
        "operation": "import_bibtex",
        "tool": "rka_execute",
        "category": "literature",
        "role_tag": "ANY",
        "summary": "Bulk-import literature entries from BibTeX.",
        "signature": (
            "rka_execute(operation='import_bibtex', *, project_id, bibtex, "
            "default_status='to_read')"
        ),
        "required_fields": ["project_id", "bibtex"],
        "optional_fields": ["default_status"],
        "enums": _e("lit_status"),
        "examples": [
            {
                "description": "Import a BibTeX library.",
                "call": {
                    "operation": "import_bibtex",
                    "project_id": "prj_01ABC...",
                    "bibtex": "@article{...}",
                },
            },
        ],
        "related_operations": ["record_literature", "batch_import"],
        "notes": None,
    },

    "enrich_doi": {
        "operation": "enrich_doi",
        "tool": "rka_execute",
        "category": "literature",
        "role_tag": "ANY",
        "summary": "Enrich a literature entry's metadata from its DOI.",
        "signature": (
            "rka_execute(operation='enrich_doi', *, project_id, lit_id)"
        ),
        "required_fields": ["project_id", "lit_id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Fill in metadata from DOI.",
                "call": {
                    "operation": "enrich_doi",
                    "project_id": "prj_01ABC...",
                    "lit_id": "lit_01XYZ...",
                },
            },
        ],
        "related_operations": ["record_literature", "update_literature"],
        "notes": None,
    },

    "link_literature_to_zotero": {
        "operation": "link_literature_to_zotero",
        "tool": "rka_execute",
        "category": "literature",
        "role_tag": "ANY",
        "summary": "Link a literature entry to a Zotero item.",
        "signature": (
            "rka_execute(operation='link_literature_to_zotero', *, "
            "project_id, lit_id, zotero_key=None)"
        ),
        "required_fields": ["project_id", "lit_id"],
        "optional_fields": ["zotero_key"],
        "enums": {},
        "examples": [
            {
                "description": "Link the literature row to Zotero.",
                "call": {
                    "operation": "link_literature_to_zotero",
                    "project_id": "prj_01ABC...",
                    "lit_id": "lit_01XYZ...",
                },
            },
        ],
        "related_operations": ["record_literature", "update_literature"],
        "notes": None,
    },

    "process_paper": {
        "operation": "process_paper",
        "tool": "rka_execute",
        "category": "literature",
        "role_tag": "ANY",
        "summary": "Ingest paper annotations into the literature row.",
        "signature": (
            "rka_execute(operation='process_paper', *, project_id, lit_id, "
            "annotations, summary=None)"
        ),
        "required_fields": ["project_id", "lit_id", "annotations"],
        "optional_fields": ["summary"],
        "enums": {},
        "examples": [
            {
                "description": "Process a paper's annotations.",
                "call": {
                    "operation": "process_paper",
                    "project_id": "prj_01ABC...",
                    "lit_id": "lit_01XYZ...",
                    "annotations": [{"text": "...", "page": 3}],
                    "summary": "Self-attention enables global context.",
                },
            },
        ],
        "related_operations": ["update_literature", "extract_claims"],
        "notes": None,
    },

    "validate_reference": {
        "operation": "validate_reference",
        "tool": "rka_execute",
        "category": "literature",
        "role_tag": "ANY",
        "summary": "Validate a manuscript reference (by DOI or title).",
        "signature": (
            "rka_execute(operation='validate_reference', *, project_id, "
            "manuscript_id, doi=None, title=None)"
        ),
        "required_fields": ["project_id", "manuscript_id"],
        "optional_fields": ["doi", "title"],
        "enums": {},
        "examples": [
            {
                "description": "Validate by DOI.",
                "call": {
                    "operation": "validate_reference",
                    "project_id": "prj_01ABC...",
                    "manuscript_id": "msc_01XYZ...",
                    "doi": "10.48550/arXiv.1706.03762",
                },
            },
        ],
        "related_operations": ["register_manuscript", "record_literature"],
        "notes": "At least one of `doi` or `title` is required.",
    },

    "batch_import": {
        "operation": "batch_import",
        "tool": "rka_execute",
        "category": "ingestion",
        "role_tag": "ANY",
        "summary": "Bulk import mixed entity types in one call.",
        "signature": (
            "rka_execute(operation='batch_import', *, project_id, "
            "entries, actor='system')"
        ),
        "required_fields": ["project_id", "entries"],
        "optional_fields": ["actor"],
        "enums": _e("source"),
        "examples": [
            {
                "description": "Import a batch of journal entries.",
                "call": {
                    "operation": "batch_import",
                    "project_id": "prj_01ABC...",
                    "entries": [{"type": "note", "content": "..."}],
                    "actor": "system",
                },
            },
        ],
        "related_operations": ["ingest_document", "import_bibtex"],
        "notes": (
            "actor='import' is auto-normalized to actor='system' "
            "(system is the canonical value for programmatic ingestion)."
        ),
    },

    "register_manuscript": {
        "operation": "register_manuscript",
        "tool": "rka_execute",
        "category": "manuscript",
        "role_tag": "ANY",
        "summary": "Register a manuscript workspace.",
        "signature": (
            "rka_execute(operation='register_manuscript', *, project_id, "
            "venue, title, abstract=None, sections=None)"
        ),
        "required_fields": ["project_id", "venue", "title"],
        "optional_fields": ["abstract", "sections"],
        "enums": {},
        "examples": [
            {
                "description": "Register a NeurIPS submission.",
                "call": {
                    "operation": "register_manuscript",
                    "project_id": "prj_01ABC...",
                    "venue": "NeurIPS-2026",
                    "title": "Edge LLM latency budgets",
                },
            },
        ],
        "related_operations": ["manuscript", "validate_reference"],
        "notes": None,
    },

    "update_status": {
        "operation": "update_status",
        "tool": "rka_execute",
        "category": "core",
        "role_tag": "BRAIN",
        "summary": "Update the project status (phase, focus, blockers).",
        "signature": (
            "rka_execute(operation='update_status', *, project_id, "
            "current_phase=None, summary=None, blockers=None, metrics=None)"
        ),
        "required_fields": ["project_id"],
        "optional_fields": [
            "current_phase", "summary", "blockers", "metrics",
        ],
        "enums": {},
        "examples": [
            {
                "description": "Move to evaluation phase.",
                "call": {
                    "operation": "update_status",
                    "project_id": "prj_01ABC...",
                    "current_phase": "evaluation",
                    "summary": "Running benchmark suite.",
                },
            },
        ],
        "related_operations": ["status"],
        "notes": None,
    },

    "bulk_update": {
        "operation": "bulk_update",
        "tool": "rka_execute",
        "category": "core",
        "role_tag": "BRAIN",
        "summary": "Update many entities in one atomic call.",
        "signature": (
            "rka_execute(operation='bulk_update', *, project_id, updates)"
        ),
        "required_fields": ["project_id", "updates"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Bulk-tag many entities.",
                "call": {
                    "operation": "bulk_update",
                    "project_id": "prj_01ABC...",
                    "updates": [
                        {"id": "jrn_01...", "tags": ["v2"]},
                        {"id": "jrn_02...", "tags": ["v2"]},
                    ],
                },
            },
        ],
        "related_operations": ["update_note", "update_decision"],
        "notes": None,
    },

    # --- missions -------------------------------------------------------

    "create_mission": {
        "operation": "create_mission",
        "tool": "rka_execute",
        "category": "mission",
        "role_tag": "BRAIN",
        "summary": "Create a mission. Requires motivated_by_decision.",
        "signature": (
            "rka_execute(operation='create_mission', *, project_id, "
            "objective, motivated_by_decision, phase='execution', "
            "tasks=None, context=None, acceptance_criteria=None, "
            "scope_boundaries=None, checkpoint_triggers=None, "
            "depends_on=None, tags=None)"
        ),
        "required_fields": [
            "project_id", "objective", "motivated_by_decision",
        ],
        "optional_fields": [
            "phase", "tasks", "context", "acceptance_criteria",
            "scope_boundaries", "checkpoint_triggers",
            "depends_on", "tags",
        ],
        "enums": {},
        "examples": [
            {
                "description": "Create an execution mission tied to a decision.",
                "call": {
                    "operation": "create_mission",
                    "project_id": "prj_01ABC...",
                    "objective": "Implement and benchmark embedding-model swap.",
                    "motivated_by_decision": "dec_01XYZ...",
                    "phase": "execution",
                },
            },
        ],
        "related_operations": [
            "update_mission", "update_mission_status",
            "submit_report", "mission",
        ],
        "notes": (
            "Provenance discipline: motivated_by_decision is REQUIRED "
            "to preserve the decision -> mission causality chain."
        ),
    },

    "update_mission": {
        "operation": "update_mission",
        "tool": "rka_execute",
        "category": "mission",
        "role_tag": "BRAIN",
        "summary": "Update mission fields (objective, context, criteria, etc.).",
        "signature": (
            "rka_execute(operation='update_mission', *, project_id, "
            "mission_id, phase=None, objective=None, context=None, "
            "acceptance_criteria=None, scope_boundaries=None, "
            "checkpoint_triggers=None, depends_on=None, "
            "parent_mission_id=None, motivated_by_decision=None, tags=None)"
        ),
        "required_fields": ["project_id", "mission_id"],
        "optional_fields": [
            "phase", "objective", "context", "acceptance_criteria",
            "scope_boundaries", "checkpoint_triggers", "depends_on",
            "parent_mission_id", "motivated_by_decision", "tags",
        ],
        "enums": {},
        "examples": [
            {
                "description": "Refine acceptance criteria.",
                "call": {
                    "operation": "update_mission",
                    "project_id": "prj_01ABC...",
                    "mission_id": "mis_01XYZ...",
                    "acceptance_criteria": "p99 < 2s on benchmark X.",
                },
            },
        ],
        "related_operations": ["create_mission", "update_mission_status"],
        "notes": None,
    },

    "update_mission_status": {
        "operation": "update_mission_status",
        "tool": "rka_execute",
        "category": "mission",
        "role_tag": "EXECUTOR",
        "summary": "Move a mission through its lifecycle states.",
        "signature": (
            "rka_execute(operation='update_mission_status', *, project_id, "
            "mission_id, status, tasks=None)"
        ),
        "required_fields": ["project_id", "mission_id", "status"],
        "optional_fields": ["tasks"],
        "enums": _e("mission_status"),
        "examples": [
            {
                "description": "Activate a pending mission.",
                "call": {
                    "operation": "update_mission_status",
                    "project_id": "prj_01ABC...",
                    "mission_id": "mis_01XYZ...",
                    "status": "active",
                },
            },
        ],
        "related_operations": ["mission", "submit_report"],
        "notes": (
            "Lifecycle: pending -> active -> complete (via submit_report). "
            "Also: partial, blocked, cancelled."
        ),
    },

    "submit_report": {
        "operation": "submit_report",
        "tool": "rka_execute",
        "category": "mission",
        "role_tag": "EXECUTOR",
        "summary": "Submit a mission's final report (closes the mission).",
        "signature": (
            "rka_execute(operation='submit_report', *, project_id, "
            "mission_id, summary, findings='', anomalies='', questions='', "
            "codebase_state='', recommended_next='')"
        ),
        "required_fields": [
            "project_id", "mission_id", "summary",
        ],
        "optional_fields": [
            "findings", "anomalies", "questions",
            "codebase_state", "recommended_next",
        ],
        "enums": {},
        "examples": [
            {
                "description": "Close a mission with a structured report.",
                "call": {
                    "operation": "submit_report",
                    "project_id": "prj_01ABC...",
                    "mission_id": "mis_01XYZ...",
                    "summary": "Embedding-model swap landed; latency budget met.",
                    "findings": "p99 dropped 30%.",
                    "recommended_next": "Run scale test.",
                },
            },
        ],
        "related_operations": ["mission", "update_mission_status", "report"],
        "notes": (
            "Canonical field is `summary` (the report's narrative body); "
            "Phase-X²' adapter also accepts `content` as an alias."
        ),
    },

    "advance_rq": {
        "operation": "advance_rq",
        "tool": "rka_execute",
        "category": "mission",
        "role_tag": "BRAIN",
        "summary": "Advance a research question through its lifecycle.",
        "signature": (
            "rka_execute(operation='advance_rq', *, project_id, "
            "rq_id, status, conclusion=None, evidence_cluster_ids=None)"
        ),
        "required_fields": ["project_id", "rq_id", "status"],
        "optional_fields": ["conclusion", "evidence_cluster_ids"],
        "enums": _e("rq_status"),
        "examples": [
            {
                "description": "Mark a research question answered.",
                "call": {
                    "operation": "advance_rq",
                    "project_id": "prj_01ABC...",
                    "rq_id": "dec_01RQ...",
                    "status": "answered",
                    "conclusion": "Embedding model nomic-v1.5 wins.",
                },
            },
        ],
        "related_operations": ["evidence", "clusters"],
        "notes": None,
    },

    # --- checkpoints + gates -------------------------------------------

    "submit_checkpoint": {
        "operation": "submit_checkpoint",
        "tool": "rka_execute",
        "category": "checkpoint",
        "role_tag": "EXECUTOR",
        "summary": "Raise a checkpoint when blocked or needing input.",
        "signature": (
            "rka_execute(operation='submit_checkpoint', *, project_id, "
            "mission_id, type, description, task_reference=None, "
            "context=None, options=None, recommendation=None, blocking=True)"
        ),
        "required_fields": [
            "project_id", "mission_id", "type", "description",
        ],
        "optional_fields": [
            "task_reference", "context", "options",
            "recommendation", "blocking",
        ],
        "enums": _e("checkpoint_type"),
        "examples": [
            {
                "description": "Raise a decision checkpoint.",
                "call": {
                    "operation": "submit_checkpoint",
                    "project_id": "prj_01ABC...",
                    "mission_id": "mis_01XYZ...",
                    "type": "decision",
                    "description": "Need PI input on benchmark thresholds.",
                    "blocking": True,
                },
            },
        ],
        "related_operations": [
            "resolve_checkpoint", "checkpoints", "create_gate",
        ],
        "notes": (
            "Canonical field is `description` (NOT `content` — common "
            "Brain hallucination from the 2026-06-01 hyperscaler-auditing PA-2)."
        ),
    },

    "resolve_checkpoint": {
        "operation": "resolve_checkpoint",
        "tool": "rka_execute",
        "category": "checkpoint",
        "role_tag": "PI",
        "summary": "Resolve a checkpoint with a resolution + rationale.",
        "signature": (
            "rka_execute(operation='resolve_checkpoint', *, project_id, id, "
            "resolution, resolved_by, rationale=None, create_decision=False)"
        ),
        "required_fields": [
            "project_id", "id", "resolution", "resolved_by",
        ],
        "optional_fields": ["rationale", "create_decision"],
        "enums": _e("resolved_by"),
        "examples": [
            {
                "description": "PI resolves a checkpoint.",
                "call": {
                    "operation": "resolve_checkpoint",
                    "project_id": "prj_01ABC...",
                    "id": "chk_01XYZ...",
                    "resolution": "Proceed with option B.",
                    "resolved_by": "pi",
                    "rationale": "B fits the latency budget.",
                },
            },
        ],
        "related_operations": ["submit_checkpoint", "checkpoints"],
        "notes": None,
    },

    "create_gate": {
        "operation": "create_gate",
        "tool": "rka_execute",
        "category": "checkpoint",
        "role_tag": "BRAIN",
        "summary": "Create a validation gate (problem framing, evidence review, etc.).",
        "signature": (
            "rka_execute(operation='create_gate', *, project_id, "
            "mission_id, gate_type, deliverables, pass_criteria, "
            "assumptions_to_verify=None)"
        ),
        "required_fields": [
            "project_id", "mission_id", "gate_type",
            "deliverables", "pass_criteria",
        ],
        "optional_fields": ["assumptions_to_verify"],
        "enums": _e("gate_type"),
        "examples": [
            {
                "description": "Create a plan_validation gate.",
                "call": {
                    "operation": "create_gate",
                    "project_id": "prj_01ABC...",
                    "mission_id": "mis_01XYZ...",
                    "gate_type": "plan_validation",
                    "deliverables": ["plan doc"],
                    "pass_criteria": ["plan reviewed by PI"],
                },
            },
        ],
        "related_operations": ["evaluate_gate"],
        "notes": None,
    },

    "evaluate_gate": {
        "operation": "evaluate_gate",
        "tool": "rka_execute",
        "category": "checkpoint",
        "role_tag": "BRAIN",
        "summary": "Evaluate a gate with a verdict + notes.",
        "signature": (
            "rka_execute(operation='evaluate_gate', *, project_id, "
            "gate_id, verdict, notes, assumption_status=None)"
        ),
        "required_fields": [
            "project_id", "gate_id", "verdict", "notes",
        ],
        "optional_fields": ["assumption_status"],
        "enums": _e("verdict"),
        "examples": [
            {
                "description": "Evaluate a gate as go.",
                "call": {
                    "operation": "evaluate_gate",
                    "project_id": "prj_01ABC...",
                    "gate_id": "chk_01GATE...",
                    "verdict": "go",
                    "notes": "Plan meets pass criteria.",
                },
            },
        ],
        "related_operations": ["create_gate"],
        "notes": None,
    },

    # --- claims / clusters ---------------------------------------------

    "extract_claims": {
        "operation": "extract_claims",
        "tool": "rka_execute",
        "category": "claims",
        "role_tag": "BRAIN",
        "summary": "Extract claims from an existing entry.",
        "signature": (
            "rka_execute(operation='extract_claims', *, project_id, "
            "entry_id, claims)"
        ),
        "required_fields": ["project_id", "entry_id", "claims"],
        "optional_fields": [],
        "enums": _e("claim_type"),
        "examples": [
            {
                "description": "Extract evidence + assumption claims.",
                "call": {
                    "operation": "extract_claims",
                    "project_id": "prj_01ABC...",
                    "entry_id": "jrn_01XYZ...",
                    "claims": [
                        {"text": "Latency improves linearly.",
                         "claim_type": "evidence"},
                    ],
                },
            },
        ],
        "related_operations": ["claims", "review_claims", "create_cluster"],
        "notes": None,
    },

    "review_claims": {
        "operation": "review_claims",
        "tool": "rka_execute",
        "category": "claims",
        "role_tag": "BRAIN",
        "summary": "Approve, reject, or adjust a set of claims.",
        "signature": (
            "rka_execute(operation='review_claims', *, project_id, "
            "claim_ids, action='approve', confidence_override=None)"
        ),
        "required_fields": ["project_id", "claim_ids"],
        "optional_fields": ["action", "confidence_override"],
        "enums": _e("review_action", "confidence"),
        "examples": [
            {
                "description": "Approve a batch of claims.",
                "call": {
                    "operation": "review_claims",
                    "project_id": "prj_01ABC...",
                    "claim_ids": ["clm_01...", "clm_02..."],
                    "action": "approve",
                },
            },
        ],
        "related_operations": ["claims", "review_cluster"],
        "notes": None,
    },

    "create_cluster": {
        "operation": "create_cluster",
        "tool": "rka_execute",
        "category": "claims",
        "role_tag": "BRAIN",
        "summary": "Create a new evidence cluster.",
        "signature": (
            "rka_execute(operation='create_cluster', *, project_id, label, "
            "research_question_id=None, synthesis=None, "
            "confidence='emerging', claim_ids=None)"
        ),
        "required_fields": ["project_id", "label"],
        "optional_fields": [
            "research_question_id", "synthesis", "confidence", "claim_ids",
        ],
        "enums": _e("cluster_confidence"),
        "examples": [
            {
                "description": "Bootstrap a cluster tied to an RQ.",
                "call": {
                    "operation": "create_cluster",
                    "project_id": "prj_01ABC...",
                    "label": "Latency wins from embedding swap",
                    "research_question_id": "dec_01RQ...",
                    "confidence": "emerging",
                },
            },
        ],
        "related_operations": [
            "clusters", "assign_claims_to_cluster", "review_cluster",
        ],
        "notes": None,
    },

    "assign_claims_to_cluster": {
        "operation": "assign_claims_to_cluster",
        "tool": "rka_execute",
        "category": "claims",
        "role_tag": "BRAIN",
        "summary": "Attach a set of claims to an existing cluster.",
        "signature": (
            "rka_execute(operation='assign_claims_to_cluster', *, "
            "project_id, cluster_id, claim_ids)"
        ),
        "required_fields": ["project_id", "cluster_id", "claim_ids"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Add 2 claims to a cluster.",
                "call": {
                    "operation": "assign_claims_to_cluster",
                    "project_id": "prj_01ABC...",
                    "cluster_id": "ecl_01XYZ...",
                    "claim_ids": ["clm_01...", "clm_02..."],
                },
            },
        ],
        "related_operations": [
            "create_cluster", "split_cluster", "merge_clusters",
        ],
        "notes": None,
    },

    "split_cluster": {
        "operation": "split_cluster",
        "tool": "rka_execute",
        "category": "claims",
        "role_tag": "BRAIN",
        "summary": "Split a cluster into multiple smaller clusters.",
        "signature": (
            "rka_execute(operation='split_cluster', *, project_id, "
            "source_id, new_clusters)"
        ),
        "required_fields": ["project_id", "source_id", "new_clusters"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Split a cluster.",
                "call": {
                    "operation": "split_cluster",
                    "project_id": "prj_01ABC...",
                    "source_id": "ecl_01SRC...",
                    "new_clusters": [
                        {"label": "A", "claim_ids": ["clm_01..."]},
                        {"label": "B", "claim_ids": ["clm_02..."]},
                    ],
                },
            },
        ],
        "related_operations": [
            "merge_clusters", "assign_claims_to_cluster",
        ],
        "notes": None,
    },

    "merge_clusters": {
        "operation": "merge_clusters",
        "tool": "rka_execute",
        "category": "claims",
        "role_tag": "BRAIN",
        "summary": "Merge multiple clusters into a new combined cluster.",
        "signature": (
            "rka_execute(operation='merge_clusters', *, project_id, "
            "source_ids, target_label, target_synthesis=None, "
            "research_question_id=None)"
        ),
        "required_fields": ["project_id", "source_ids", "target_label"],
        "optional_fields": ["target_synthesis", "research_question_id"],
        "enums": {},
        "examples": [
            {
                "description": "Merge two clusters.",
                "call": {
                    "operation": "merge_clusters",
                    "project_id": "prj_01ABC...",
                    "source_ids": ["ecl_01A...", "ecl_01B..."],
                    "target_label": "Unified latency findings",
                },
            },
        ],
        "related_operations": ["split_cluster", "create_cluster"],
        "notes": None,
    },

    "review_cluster": {
        "operation": "review_cluster",
        "tool": "rka_execute",
        "category": "claims",
        "role_tag": "BRAIN",
        "summary": "Write the definitive synthesis on a cluster.",
        "signature": (
            "rka_execute(operation='review_cluster', *, project_id, "
            "cluster_id, confidence, synthesis, gaps=None, "
            "contradictions=None, resolve_queue_items=None, "
            "research_question_id=None)"
        ),
        "required_fields": [
            "project_id", "cluster_id", "confidence", "synthesis",
        ],
        "optional_fields": [
            "gaps", "contradictions", "resolve_queue_items",
            "research_question_id",
        ],
        "enums": _e("cluster_confidence"),
        "examples": [
            {
                "description": "Synthesize a strong-confidence cluster.",
                "call": {
                    "operation": "review_cluster",
                    "project_id": "prj_01ABC...",
                    "cluster_id": "ecl_01XYZ...",
                    "confidence": "strong",
                    "synthesis": "Embedding swap yields 30% p99 reduction.",
                },
            },
        ],
        "related_operations": [
            "clusters", "review_claims", "resolve_contradiction",
        ],
        "notes": None,
    },

    "resolve_contradiction": {
        "operation": "resolve_contradiction",
        "tool": "rka_execute",
        "category": "claims",
        "role_tag": "BRAIN",
        "summary": "Resolve a contradiction inside an evidence cluster.",
        "signature": (
            "rka_execute(operation='resolve_contradiction', *, project_id, "
            "cluster_id, resolution, claim_actions=None)"
        ),
        "required_fields": ["project_id", "cluster_id", "resolution"],
        "optional_fields": ["claim_actions"],
        "enums": {},
        "examples": [
            {
                "description": "Resolve a contradiction by retiring a claim.",
                "call": {
                    "operation": "resolve_contradiction",
                    "project_id": "prj_01ABC...",
                    "cluster_id": "ecl_01XYZ...",
                    "resolution": "Newer benchmark supersedes the older.",
                    "claim_actions": [
                        {"id": "clm_01OLD...", "action": "retire"},
                    ],
                },
            },
        ],
        "related_operations": ["review_cluster", "contradictions"],
        "notes": None,
    },

    # --- hooks ----------------------------------------------------------

    "hook_add": {
        "operation": "hook_add",
        "tool": "rka_execute",
        "category": "hooks",
        "role_tag": "PI",
        "summary": "Add an automation hook.",
        "signature": (
            "rka_execute(operation='hook_add', *, project_id, "
            "event, handler_type, handler_config, name, "
            "enabled=True, created_by='pi')"
        ),
        "required_fields": [
            "project_id", "event", "handler_type",
            "handler_config", "name",
        ],
        "optional_fields": ["enabled", "created_by"],
        "enums": {},
        "examples": [
            {
                "description": "Add a hook that fires on decision creation.",
                "call": {
                    "operation": "hook_add",
                    "project_id": "prj_01ABC...",
                    "event": "decision.created",
                    "handler_type": "webhook",
                    "handler_config": {"url": "https://..."},
                    "name": "notify-pi",
                },
            },
        ],
        "related_operations": [
            "hooks", "hook_enable", "hook_disable", "hook_delete",
        ],
        "notes": None,
    },

    "hook_enable": {
        "operation": "hook_enable",
        "tool": "rka_execute",
        "category": "hooks",
        "role_tag": "PI",
        "summary": "Enable a hook.",
        "signature": (
            "rka_execute(operation='hook_enable', *, project_id, hook_id)"
        ),
        "required_fields": ["project_id", "hook_id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Enable a hook.",
                "call": {
                    "operation": "hook_enable",
                    "project_id": "prj_01ABC...",
                    "hook_id": "hk_01XYZ...",
                },
            },
        ],
        "related_operations": ["hook_add", "hook_disable"],
        "notes": None,
    },

    "hook_disable": {
        "operation": "hook_disable",
        "tool": "rka_execute",
        "category": "hooks",
        "role_tag": "PI",
        "summary": "Disable a hook (preserves config).",
        "signature": (
            "rka_execute(operation='hook_disable', *, project_id, hook_id)"
        ),
        "required_fields": ["project_id", "hook_id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Disable a hook.",
                "call": {
                    "operation": "hook_disable",
                    "project_id": "prj_01ABC...",
                    "hook_id": "hk_01XYZ...",
                },
            },
        ],
        "related_operations": ["hook_enable", "hook_delete"],
        "notes": None,
    },

    "hook_delete": {
        "operation": "hook_delete",
        "tool": "rka_execute",
        "category": "hooks",
        "role_tag": "PI",
        "summary": "Permanently delete a hook.",
        "signature": (
            "rka_execute(operation='hook_delete', *, project_id, hook_id)"
        ),
        "required_fields": ["project_id", "hook_id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Delete a hook.",
                "call": {
                    "operation": "hook_delete",
                    "project_id": "prj_01ABC...",
                    "hook_id": "hk_01XYZ...",
                },
            },
        ],
        "related_operations": ["hook_disable"],
        "notes": None,
    },

    "brain_notifications_clear": {
        "operation": "brain_notifications_clear",
        "tool": "rka_execute",
        "category": "notifications",
        "role_tag": "BRAIN",
        "summary": "Clear Brain notifications by ID.",
        "signature": (
            "rka_execute(operation='brain_notifications_clear', *, "
            "project_id, ids)"
        ),
        "required_fields": ["project_id", "ids"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Clear two notifications.",
                "call": {
                    "operation": "brain_notifications_clear",
                    "project_id": "prj_01ABC...",
                    "ids": ["bn_01...", "bn_02..."],
                },
            },
        ],
        "related_operations": ["brain_notifications"],
        "notes": None,
    },

    # --- workspace + maintenance ---------------------------------------

    "bootstrap_workspace": {
        "operation": "bootstrap_workspace",
        "tool": "rka_execute",
        "category": "workspace",
        "role_tag": "ANY",
        "summary": "Bootstrap a workspace into the knowledge base.",
        "signature": (
            "rka_execute(operation='bootstrap_workspace', *, project_id, "
            "folder_path, phase=None, override_tags=None, skip_files=None, "
            "use_llm=True, dry_run=False)"
        ),
        "required_fields": ["project_id", "folder_path"],
        "optional_fields": [
            "phase", "override_tags", "skip_files", "use_llm", "dry_run",
        ],
        "enums": {},
        "examples": [
            {
                "description": "Dry-run bootstrap of a workspace folder.",
                "call": {
                    "operation": "bootstrap_workspace",
                    "project_id": "prj_01ABC...",
                    "folder_path": "/Users/me/Research/proj",
                    "dry_run": True,
                },
            },
        ],
        "related_operations": [
            "workspace_scan", "workspace_tree", "bootstrap_review",
        ],
        "notes": None,
    },

    "scan_workspace": {
        "operation": "scan_workspace",
        "tool": "rka_execute",
        "category": "workspace",
        "role_tag": "ANY",
        "summary": "Execute a workspace scan (writes scn_... row).",
        "signature": (
            "rka_execute(operation='scan_workspace', *, project_id, "
            "folder_path, ignore_patterns=None, max_file_size_mb=50.0, "
            "use_llm=True)"
        ),
        "required_fields": ["project_id", "folder_path"],
        "optional_fields": [
            "ignore_patterns", "max_file_size_mb", "use_llm",
        ],
        "enums": {},
        "examples": [
            {
                "description": "Scan a workspace.",
                "call": {
                    "operation": "scan_workspace",
                    "project_id": "prj_01ABC...",
                    "folder_path": "/Users/me/Research/proj",
                },
            },
        ],
        "related_operations": ["workspace_scan", "bootstrap_workspace"],
        "notes": None,
    },

    "flag_stale": {
        "operation": "flag_stale",
        "tool": "rka_execute",
        "category": "maintenance",
        "role_tag": "BRAIN",
        "summary": "Flag a knowledge entity as stale (yellow/red).",
        "signature": (
            "rka_execute(operation='flag_stale', *, project_id, "
            "entity_id, reason, staleness='yellow', propagate=True)"
        ),
        "required_fields": ["project_id", "entity_id", "reason"],
        "optional_fields": ["staleness", "propagate"],
        "enums": _e("staleness"),
        "examples": [
            {
                "description": "Flag a finding as stale.",
                "call": {
                    "operation": "flag_stale",
                    "project_id": "prj_01ABC...",
                    "entity_id": "jrn_01XYZ...",
                    "reason": "Superseded by new benchmark.",
                    "staleness": "red",
                },
            },
        ],
        "related_operations": ["freshness", "eviction_sweep"],
        "notes": None,
    },

    "eviction_sweep": {
        "operation": "eviction_sweep",
        "tool": "rka_execute",
        "category": "maintenance",
        "role_tag": "BRAIN",
        "summary": "Evict knowledge per policy (defaults to dry_run).",
        "signature": (
            "rka_execute(operation='eviction_sweep', *, project_id, "
            "dry_run=True)"
        ),
        "required_fields": ["project_id"],
        "optional_fields": ["dry_run"],
        "enums": {},
        "examples": [
            {
                "description": "Preview an eviction sweep.",
                "call": {
                    "operation": "eviction_sweep",
                    "project_id": "prj_01ABC...",
                    "dry_run": True,
                },
            },
        ],
        "related_operations": ["flag_stale", "freshness"],
        "notes": None,
    },

    # --- session (unscoped + project lifecycle) ------------------------

    "create_project": {
        "operation": "create_project",
        "tool": "rka_execute",
        "category": "session",
        "role_tag": "PI",
        "summary": "Bootstrap a new RKA project (UNSCOPED — no project_id required).",
        "signature": (
            "rka_execute(operation='create_project', *, name, "
            "description=None)"
        ),
        "required_fields": ["name"],
        "optional_fields": ["description"],
        "enums": {},
        "examples": [
            {
                "description": "Create a new project.",
                "call": {
                    "operation": "create_project",
                    "name": "iot-edge-llm",
                    "description": "Edge-deployed LLM latency study.",
                },
            },
        ],
        "related_operations": ["list_projects", "status"],
        "notes": "UNSCOPED — does not require project_id.",
    },

    "reset_session": {
        "operation": "reset_session",
        "tool": "rka_execute",
        "category": "session",
        "role_tag": "ANY",
        "summary": "Reset the in-process session tracker (UNSCOPED).",
        "signature": "rka_execute(operation='reset_session')",
        "required_fields": [],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Reset session tracking.",
                "call": {"operation": "reset_session"},
            },
        ],
        "related_operations": ["status"],
        "notes": "UNSCOPED.",
    },

    "session_digest": {
        "operation": "session_digest",
        "tool": "rka_execute",
        "category": "session",
        "role_tag": "ANY",
        "summary": "Compact session summary (mutates session state).",
        "signature": (
            "rka_execute(operation='session_digest', *, project_id)"
        ),
        "required_fields": ["project_id"],
        "optional_fields": [],
        "enums": {},
        "examples": [
            {
                "description": "Fetch a session digest.",
                "call": {
                    "operation": "session_digest",
                    "project_id": "prj_01ABC...",
                },
            },
        ],
        "related_operations": ["reset_session", "status"],
        "notes": None,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_operation_schema(operation: str) -> dict[str, Any] | None:
    """Return the schema dict for ``operation`` or None if unknown."""
    return OPERATIONS_SCHEMA.get(operation)


def list_operations_grouped() -> dict[str, list[dict[str, Any]]]:
    """Return operations grouped by tool (rka_query / rka_execute), then category.

    Each leaf entry: ``{operation, category, summary, role_tag, required_fields}``.
    Used by ``rka_describe()`` with no argument to produce the operations index.
    """
    out: dict[str, dict[str, list[dict[str, Any]]]] = {
        "rka_query": {},
        "rka_execute": {},
    }
    for op, entry in OPERATIONS_SCHEMA.items():
        bucket = out.setdefault(entry["tool"], {})
        cat_list = bucket.setdefault(entry["category"], [])
        cat_list.append(
            {
                "operation": op,
                "category": entry["category"],
                "summary": entry["summary"],
                "role_tag": entry["role_tag"],
                "required_fields": entry["required_fields"],
            }
        )
    # Sort within each category
    for tool_bucket in out.values():
        for cat_list in tool_bucket.values():
            cat_list.sort(key=lambda d: d["operation"])
    return out


def suggest_operations(query: str, *, top_n: int = 5) -> list[str]:
    """Return up to ``top_n`` best fuzzy matches for an unknown operation."""
    if not query:
        return []
    return difflib.get_close_matches(
        query.lower().strip(),
        list(OPERATIONS_SCHEMA),
        n=top_n,
        cutoff=0.4,
    )


def list_operations_compact() -> dict[str, list[str]]:
    """v2.7.0 NO-COMPROMISE compromise-#3 mitigation.

    Returns a flat ``{tool: [op_name, ...]}`` map for the
    ``rka_describe('')`` browse mode. Strips summaries, required_fields,
    enums, examples, related_operations from the response — those
    surfaces are now visible directly in the Pydantic-derived
    ``inputSchema`` of ``rka_query`` / ``rka_execute`` (v2.7.0
    discriminated union), so the browse-mode index can collapse to
    <250 tokens.

    Callers wanting per-operation summary + examples pass the
    operation name explicitly: ``rka_describe('record_decision')``.
    """
    out: dict[str, list[str]] = {"rka_query": [], "rka_execute": []}
    for op_name, entry in OPERATIONS_SCHEMA.items():
        tool = entry["tool"]
        out.setdefault(tool, []).append(op_name)
    for ops_list in out.values():
        ops_list.sort()
    return out


async def dispatch_describe(operation: str | None) -> str:
    """Render the rka_describe response as a JSON string.

    Behavior:
      - operation in OPERATIONS_SCHEMA -> return full schema as indented JSON.
      - operation is None or empty -> return the compact operations index
        (v2.7.0 NO-COMPROMISE compromise-#3 mitigation: stripped to
        operation name + ≤12-word summary, grouped by tool; target
        <250 tokens total). Full per-op schema is reachable via
        ``rka_describe('<op_name>')`` or via the Pydantic-derived
        inputSchema FastMCP renders for ``rka_query`` / ``rka_execute``.
      - operation is unknown -> return ``{error, operation, did_you_mean}``.
    """
    if not operation:
        # NO-COMPROMISE: shrink to under ~250 tokens by joining names
        # into a single comma-separated string per tool. Full per-op
        # schema is reachable via the FastMCP-rendered inputSchema or
        # via `rka_describe('<op_name>')`.
        compact = list_operations_compact()
        return json.dumps(
            {
                "rka_query": ", ".join(compact.get("rka_query", [])),
                "rka_execute": ", ".join(compact.get("rka_execute", [])),
                "total": len(OPERATIONS_SCHEMA),
                "hint": (
                    "rka_describe('<op>') for schema; rka_query/_execute "
                    "inputSchema already carries per-branch enums."
                ),
            },
            indent=2,
        )

    op = operation.strip()
    entry = OPERATIONS_SCHEMA.get(op)
    if entry is None:
        return json.dumps(
            {
                "error": "unknown_operation",
                "operation": operation,
                "did_you_mean": suggest_operations(op),
                "hint": (
                    "Pass operation='' (empty string) to list every known "
                    "operation grouped by tool and category."
                ),
            },
            indent=2,
        )

    return json.dumps(entry, indent=2)


__all__ = [
    "OPERATIONS_SCHEMA",
    "dispatch_describe",
    "get_operation_schema",
    "list_operations_grouped",
    "list_operations_compact",
    "suggest_operations",
]
