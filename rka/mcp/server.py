"""MCP server — thin HTTP proxy to the RKA REST API.

All tools are prefixed with `rka_` for namespace isolation.
The server keeps lightweight per-session state for session digest.
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps

from mcp.server.fastmcp import FastMCP
import httpx

from rka.models.mission import MissionTask

RKA_INSTRUCTIONS = """\
Research Knowledge Agent (RKA) is a structured research knowledge base shared by the
Brain, Executor, and PI. It stores journal entries, decisions, literature, missions,
claims, evidence clusters, and a provenance-linked research map.

Detailed operating guidance now lives in the role skill files shipped with the repo:
- `skills/SKILL.md`
- `skills/brain/SKILL.md`
- `skills/executor/SKILL.md`
- `skills/pi/SKILL.md`

Use this MCP instruction block as a fallback only.

## Minimal Session Start
1. `rka_get_context()` — load current project state and recent knowledge
2. `rka_get_status()` — current phase, focus, blockers
3. `rka_get_pending_maintenance()` — provenance gaps and stale knowledge
4. `rka_get_checkpoints(status="open")` — unresolved blockers
5. `rka_get_review_queue()` and `rka_get_research_map()` — Brain/PI review surfaces

## Core Provenance Rules
- Decisions require `related_journal=[...]`
- Missions require `motivated_by_decision=...`
- Notes should set `related_decisions=[...]` and/or `related_mission=...` when applicable
- PI input must use `source="pi"` and `verbatim_input="..."` with exact wording

## High-Value Tools
- Project: `rka_list_projects`, `rka_set_project`, `rka_get_status`
- Recording: `rka_add_note`, `rka_add_decision`, `rka_add_literature`
- Execution: `rka_create_mission`, `rka_submit_checkpoint`, `rka_submit_report`
- Research map: `rka_get_research_map`, `rka_review_cluster`, `rka_resolve_contradiction`
- Retrieval: `rka_search`, `rka_trace_provenance`, `rka_get_journal`

## Multi-Project
If project scope is unclear, call `rka_list_projects()` and `rka_set_project(id)` first.
All tools operate on the active project.
"""

mcp = FastMCP("Research Knowledge Agent", instructions=RKA_INSTRUCTIONS)
API_URL = os.environ.get("RKA_API_URL", "http://localhost:9712")
API_TIMEOUT = httpx.Timeout(connect=30.0, read=120.0, write=120.0, pool=30.0)


@dataclass
class MCPSessionState:
    """Tracks state across tool calls in a single MCP stdio session."""

    tool_calls: int = 0
    session_start: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    project_id: str | None = field(
        default_factory=lambda: os.environ.get("RKA_PROJECT") or None
    )
    entities_created: list[dict[str, str]] = field(default_factory=list)
    decisions_made: list[str] = field(default_factory=list)
    checkpoints_raised: list[str] = field(default_factory=list)

    @property
    def verbosity(self) -> str:
        return "full"


_session = MCPSessionState()


def _tick() -> MCPSessionState:
    _session.tool_calls += 1
    return _session


def _record_entity(entity_type: str, entity_id: str, summary: str) -> None:
    _session.entities_created.append(
        {"type": entity_type, "id": entity_id, "summary": summary[:80]}
    )


def tool():
    """Register an MCP tool and increment session state on every invocation."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            _tick()
            return await func(*args, **kwargs)

        return mcp.tool()(wrapper)

    return decorator


def _client() -> httpx.AsyncClient:
    headers = {}
    if _session.project_id:
        headers["X-RKA-Project"] = _session.project_id
    return httpx.AsyncClient(base_url=API_URL, timeout=API_TIMEOUT, headers=headers)


def _raise_with_detail(r: httpx.Response) -> None:
    """Like _raise_with_detail(r) but includes the response body in the error."""
    if r.is_success:
        return
    try:
        detail = r.json().get("detail", r.text)
    except Exception:
        detail = r.text
    raise Exception(f"API error {r.status_code}: {detail}")


# ============================================================
# Knowledge Management
# ============================================================

@tool()
async def rka_add_note(
    content: str,
    type: str = "note",
    source: str = "executor",
    phase: str | None = None,
    verbatim_input: str | None = None,
    related_decisions: list[str] | None = None,
    related_literature: list[str] | None = None,
    related_mission: str | None = None,
    supersedes: str | None = None,
    confidence: str = "hypothesis",
    importance: str = "normal",
    tags: list[str] | None = None,
) -> str:
    """Add a research journal entry.

    Args:
        content: The note content (Brain's analysis when recording PI input)
        type: Entry type — note | log | directive (legacy types like finding/insight/methodology are auto-mapped)
        source: Who created this — brain | executor | pi | llm | web_ui | system
        phase: Research phase (uses current if omitted)
        verbatim_input: PI's exact words when recording PI input (preserves intellectual attribution)
        related_decisions: Decision IDs this note relates to
        related_literature: Literature IDs this note references
        related_mission: Mission ID this note belongs to
        supersedes: ID of an older note this one replaces
        confidence: hypothesis | tested | verified | superseded | retracted
        importance: critical | high | normal | low
        tags: Optional tags for categorization (e.g. ["anomaly-detection", "methodology"])
    """
    async with _client() as c:
        body = {
            "content": content, "type": type, "source": source,
            "phase": phase, "verbatim_input": verbatim_input,
            "related_decisions": related_decisions,
            "related_literature": related_literature,
            "related_mission": related_mission, "supersedes": supersedes,
            "confidence": confidence, "importance": importance,
            "tags": tags,
        }
        r = await c.post("/api/notes", json={k: v for k, v in body.items() if v is not None})
        _raise_with_detail(r)
        d = r.json()
        _record_entity("journal", d["id"], content)
        return f"Created {d['id']} [{d['type']}] confidence={d['confidence']}"


@tool()
async def rka_update_note(
    id: str,
    content: str | None = None,
    type: str | None = None,
    confidence: str | None = None,
    importance: str | None = None,
    verbatim_input: str | None = None,
    related_decisions: list[str] | None = None,
    related_literature: list[str] | None = None,
    related_mission: str | None = None,
    tags: list[str] | None = None,
    phase: str | None = None,
    source: str | None = None,
) -> str:
    """Update an existing journal entry.

    Args:
        id: The note ID to update
        content: New content
        type: New type — note | log | directive
        confidence: New confidence level — hypothesis | tested | verified | superseded | retracted
        importance: New importance level — critical | high | normal | low
        verbatim_input: PI's exact words (preserves intellectual attribution)
        related_decisions: Decision IDs this note relates to
        related_literature: Literature IDs this note references
        related_mission: Mission ID this note belongs to
        tags: Tags for categorization
        phase: Research phase (e.g. planning | development | design | experiment)
        source: Who created this — brain | executor | pi | llm | web_ui
    """
    async with _client() as c:
        body = {
            "content": content, "type": type, "confidence": confidence,
            "importance": importance, "verbatim_input": verbatim_input,
            "related_decisions": related_decisions,
            "related_literature": related_literature,
            "related_mission": related_mission, "tags": tags,
            "phase": phase, "source": source,
        }
        filtered = {k: v for k, v in body.items() if v is not None}
        r = await c.put(f"/api/notes/{id}", json=filtered)
        _raise_with_detail(r)
        changed = list(filtered.keys())
        return f"Updated {id} fields={','.join(changed)}"


@tool()
async def rka_add_literature(
    title: str,
    authors: list[str] | None = None,
    year: int | None = None,
    venue: str | None = None,
    doi: str | None = None,
    url: str | None = None,
    bibtex: str | None = None,
    abstract: str | None = None,
    key_findings: list[str] | None = None,
    relevance: str | None = None,
    pdf_path: str | None = None,
    added_by: str = "brain",
) -> str:
    """Add a literature entry (paper, article, etc.).

    Args:
        title: Paper title
        authors: Author list
        year: Publication year
        venue: Conference or journal name
        doi: Digital Object Identifier
        url: URL to the paper
        bibtex: Raw BibTeX entry
        abstract: Paper abstract
        key_findings: List of key findings
        relevance: How it relates to this project
        pdf_path: Local path to PDF
        added_by: Who added this — brain | executor | pi
    """
    async with _client() as c:
        body = {
            "title": title, "authors": authors, "year": year, "venue": venue,
            "doi": doi, "url": url, "bibtex": bibtex, "abstract": abstract,
            "key_findings": key_findings, "relevance": relevance,
            "pdf_path": pdf_path, "added_by": added_by,
        }
        r = await c.post("/api/literature", json={k: v for k, v in body.items() if v is not None})
        _raise_with_detail(r)
        d = r.json()
        _record_entity("literature", d["id"], d["title"])
        return f"Created {d['id']}: {d['title']}"


@tool()
async def rka_update_literature(
    id: str,
    title: str | None = None,
    authors: list[str] | None = None,
    year: int | None = None,
    venue: str | None = None,
    doi: str | None = None,
    url: str | None = None,
    bibtex: str | None = None,
    pdf_path: str | None = None,
    abstract: str | None = None,
    status: str | None = None,
    key_findings: list[str] | None = None,
    methodology_notes: str | None = None,
    relevance: str | None = None,
    relevance_score: float | None = None,
    related_decisions: list[str] | None = None,
    notes: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Update a literature entry. Only provide fields you want to change.

    Args:
        id: Literature ID
        title: Updated paper title
        authors: Updated author list
        year: Updated publication year
        venue: Updated conference or journal name
        doi: Updated DOI
        url: Updated URL
        bibtex: Updated raw BibTeX entry
        pdf_path: Local path to PDF file
        abstract: Updated paper abstract
        status: to_read | reading | read | cited | excluded
        key_findings: Updated key findings list
        methodology_notes: Notes on methodology used in the paper
        relevance: How it relates to this project
        relevance_score: 0.0-1.0 relevance score
        related_decisions: Decision IDs this literature informs
        notes: Researcher annotations
        tags: Tags for categorization
    """
    async with _client() as c:
        body = {
            "title": title, "authors": authors, "year": year,
            "venue": venue, "doi": doi, "url": url, "bibtex": bibtex,
            "pdf_path": pdf_path, "abstract": abstract, "status": status,
            "key_findings": key_findings, "methodology_notes": methodology_notes,
            "relevance": relevance, "relevance_score": relevance_score,
            "related_decisions": related_decisions, "notes": notes, "tags": tags,
        }
        r = await c.put(f"/api/literature/{id}", json={k: v for k, v in body.items() if v is not None})
        _raise_with_detail(r)
        return f"Updated {id}"


@tool()
async def rka_add_decision(
    question: str,
    phase: str,
    decided_by: str,
    options: list[dict] | None = None,
    chosen: str | None = None,
    rationale: str | None = None,
    parent_id: str | None = None,
    related_literature: list[str] | None = None,
    related_journal: list[str] | None = None,
    kind: str = "decision",
) -> str:
    """Add a decision node to the research decision tree.

    Args:
        question: The decision question
        phase: Research phase
        decided_by: pi | brain | executor
        options: List of options [{label, description}]
        chosen: Label of chosen option
        rationale: Why this was chosen
        parent_id: Parent decision ID for tree structure
        related_literature: Literature IDs informing this decision
        related_journal: Journal entry IDs that justify this decision (creates justified_by links)
        kind: research_question | design_choice | decision | operational
    """
    async with _client() as c:
        body = {
            "question": question, "phase": phase, "decided_by": decided_by,
            "options": options, "chosen": chosen, "rationale": rationale,
            "parent_id": parent_id, "related_literature": related_literature,
            "related_journal": related_journal, "kind": kind,
        }
        r = await c.post("/api/decisions", json={k: v for k, v in body.items() if v is not None})
        _raise_with_detail(r)
        d = r.json()
        _session.decisions_made.append(d["id"])
        return f"Created decision {d['id']}: {d['question'][:80]}"


@tool()
async def rka_update_decision(
    id: str,
    status: str | None = None,
    chosen: str | None = None,
    rationale: str | None = None,
    abandonment_reason: str | None = None,
    kind: str | None = None,
    related_journal: list[str] | None = None,
    parent_id: str | None = None,
    related_literature: list[str] | None = None,
    related_missions: list[str] | None = None,
    phase: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Update a decision node.

    Args:
        id: Decision ID
        status: active | abandoned | superseded | merged | revisit
        chosen: Updated chosen option
        rationale: Updated rationale
        abandonment_reason: Why this branch was abandoned
        kind: research_question | design_choice | decision | operational
        related_journal: Journal entry IDs that justify this decision
        parent_id: Parent decision ID for tree structure (set to "" to clear)
        related_literature: Literature IDs informing this decision
        related_missions: Mission IDs related to this decision
        phase: Research phase
        tags: Tags for categorization
    """
    async with _client() as c:
        body = {
            "status": status, "chosen": chosen, "rationale": rationale,
            "abandonment_reason": abandonment_reason, "kind": kind,
            "related_journal": related_journal, "parent_id": parent_id,
            "related_literature": related_literature,
            "related_missions": related_missions, "phase": phase, "tags": tags,
        }
        filtered = {k: v for k, v in body.items() if v is not None}
        r = await c.put(f"/api/decisions/{id}", json=filtered)
        _raise_with_detail(r)
        changed = list(filtered.keys())
        return f"Updated decision {id} fields={','.join(changed)}"


@tool()
async def rka_bulk_update(
    updates: list[dict],
) -> str:
    """Bulk update multiple entities in one call.

    Each update must have 'entity_type', 'id', and 'data' fields.
    Supported entity_types: 'note', 'decision', 'literature'.

    Args:
        updates: List of updates, e.g. [{"entity_type": "note", "id": "jrn_01...", "data": {"type": "note", "confidence": "verified", "tags": ["v1.6-audit"]}}]
    """
    async with _client() as c:
        results = []
        errors = []
        for i, upd in enumerate(updates):
            etype = upd.get("entity_type")
            eid = upd.get("id")
            data = upd.get("data", {})

            if not etype or not eid:
                errors.append(f"[{i}] missing entity_type or id")
                continue

            endpoint_map = {
                "note": f"/api/notes/{eid}",
                "journal": f"/api/notes/{eid}",
                "decision": f"/api/decisions/{eid}",
                "literature": f"/api/literature/{eid}",
            }
            endpoint = endpoint_map.get(etype)
            if not endpoint:
                errors.append(f"[{i}] unknown entity_type: {etype}")
                continue

            try:
                r = await c.put(endpoint, json=data)
                if r.status_code < 300:
                    results.append(f"[{i}] {etype} {eid} OK")
                else:
                    errors.append(f"[{i}] {etype} {eid} -> {r.status_code}: {r.text[:100]}")
            except Exception as e:
                errors.append(f"[{i}] {etype} {eid} -> error: {str(e)[:100]}")

        summary = f"Updated {len(results)}/{len(updates)}"
        if errors:
            summary += f" ({len(errors)} errors)"
        lines = [summary, ""]
        if results:
            lines.append("Successes:")
            lines.extend(results[:20])
            if len(results) > 20:
                lines.append(f"  ... and {len(results) - 20} more")
        if errors:
            lines.append("Errors:")
            lines.extend(errors)
        return "\n".join(lines)


# ============================================================
# Mission Lifecycle
# ============================================================

@tool()
async def rka_create_mission(
    phase: str,
    objective: str,
    tasks: list[MissionTask] | None = None,
    context: str | None = None,
    acceptance_criteria: str | None = None,
    scope_boundaries: str | None = None,
    checkpoint_triggers: str | None = None,
    depends_on: str | None = None,
    motivated_by_decision: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Create a new mission for the Executor.

    PROVENANCE: Always provide `motivated_by_decision` to link the triggering decision.
    Include relevant decision IDs, journal entry IDs, and literature IDs in the `context`
    field so the Executor can read the full reasoning chain before starting work.

    Args:
        phase: Research phase
        objective: Clear mission objective
        tasks: Task list [{description, status}]
        context: Background context for the Executor — include decision IDs, journal IDs, and literature IDs that inform this mission
        acceptance_criteria: How to know when done
        scope_boundaries: What NOT to do
        checkpoint_triggers: When to escalate
        depends_on: Mission ID this depends on
        motivated_by_decision: Decision ID that triggered this mission (REQUIRED for provenance — creates motivated link)
        tags: Optional explicit tags for categorization
    """
    async with _client() as c:
        body = {
            "phase": phase,
            "objective": objective,
            "tasks": [task.model_dump() for task in tasks] if tasks else None,
            "context": context, "acceptance_criteria": acceptance_criteria,
            "scope_boundaries": scope_boundaries,
            "checkpoint_triggers": checkpoint_triggers,
            "depends_on": depends_on,
            "motivated_by_decision": motivated_by_decision,
            "tags": tags,
        }
        r = await c.post("/api/missions", json={k: v for k, v in body.items() if v is not None})
        _raise_with_detail(r)
        d = r.json()
        n_tasks = len(d.get("tasks") or [])
        mid = d["id"]
        _record_entity("mission", mid, d["objective"])
        lines = [
            "MISSION CREATED",
            "",
            f"  ID:        {mid}",
            f"  Status:    {d.get('status', 'pending')}",
            f"  Enrich:    {d.get('enrichment_status', 'ready')}",
            f"  Objective: {d['objective'][:500]}",
            f"  Tasks:     {n_tasks}",
            "",
            f"Pass this ID to the Executor: {mid}",
        ]
        return "\n".join(lines)


@tool()
async def rka_get_mission(id: str | None = None) -> str:
    """Get a mission. Returns the active mission if no ID given.

    Args:
        id: Mission ID (optional — defaults to currently active mission)
    """
    async with _client() as c:
        if id:
            r = await c.get(f"/api/missions/{id}")
            _raise_with_detail(r)
            return json.dumps(r.json(), indent=2)
        # No ID given: prefer active, fall back to most recent pending
        for status in ("active", "pending"):
            r = await c.get("/api/missions", params={"status": status, "limit": 1})
            _raise_with_detail(r)
            missions = r.json()
            if missions:
                return json.dumps(missions[0], indent=2)
        return "No active or pending mission."


@tool()
async def rka_update_mission_status(
    id: str,
    status: str,
    tasks: list[MissionTask] | None = None,
) -> str:
    """Update mission status and task progress.

    Args:
        id: Mission ID
        status: pending | active | complete | partial | blocked | cancelled
        tasks: Updated task list with progress
    """
    async with _client() as c:
        body = {"status": status}
        if tasks:
            body["tasks"] = [task.model_dump() for task in tasks]
        r = await c.put(f"/api/missions/{id}", json=body)
        _raise_with_detail(r)
        return f"Mission {id} → {status}"


@tool()
async def rka_submit_report(
    mission_id: str,
    summary: str,
    findings: str = "",
    anomalies: str = "",
    questions: str = "",
    codebase_state: str = "",
    recommended_next: str = "",
) -> str:
    """Submit an execution report for a completed mission.

    The summary is the main report body — put the full narrative there.
    Other fields are optional structured sections (one item per line).

    Args:
        mission_id: Mission ID
        summary: Full report text (methodology, results, what was done)
        findings: Key findings, one per line (optional)
        anomalies: Unexpected observations or issues, one per line (optional)
        questions: Open questions for the PI, one per line (optional)
        codebase_state: Description of codebase state after mission (optional)
        recommended_next: Suggested next steps as a single string (optional)
    """
    def _split(text: str) -> list[str] | None:
        if not text or not text.strip():
            return None
        return [line.strip() for line in text.strip().splitlines() if line.strip()]

    body: dict = {
        "tasks_completed": [summary],
        "findings": _split(findings),
        "anomalies": _split(anomalies),
        "questions": _split(questions),
        "codebase_state": codebase_state.strip() or None,
        "recommended_next": recommended_next.strip() or None,
    }
    body = {k: v for k, v in body.items() if v is not None}

    async with _client() as c:
        r = await c.post(
            f"/api/missions/{mission_id}/report",
            json=body,
        )
        _raise_with_detail(r)
        return f"Report submitted for mission {mission_id}"


@tool()
async def rka_get_report(mission_id: str | None = None) -> str:
    """Get mission report. Defaults to latest complete mission.

    Args:
        mission_id: Mission ID (optional)
    """
    async with _client() as c:
        if mission_id:
            r = await c.get(f"/api/missions/{mission_id}/report")
        else:
            # Get latest complete mission
            r = await c.get("/api/missions", params={"status": "complete", "limit": 1})
            _raise_with_detail(r)
            missions = r.json()
            if not missions:
                return "No completed missions."
            r = await c.get(f"/api/missions/{missions[0]['id']}/report")
        _raise_with_detail(r)
        data = r.json()
        if data is None:
            return "No report found."
        return json.dumps(data, indent=2)


# ============================================================
# Checkpoints
# ============================================================

@tool()
async def rka_submit_checkpoint(
    mission_id: str,
    type: str,
    description: str,
    task_reference: str | None = None,
    context: str | None = None,
    options: list[dict] | None = None,
    recommendation: str | None = None,
    blocking: bool = True,
) -> str:
    """Submit a checkpoint — escalate a decision/question to Brain/PI.

    Args:
        mission_id: Current mission ID
        type: decision | clarification | inspection
        description: What needs resolving
        task_reference: Which task triggered this
        context: Additional context
        options: Possible options [{label, description, consequence}]
        recommendation: Executor's non-binding recommendation
        blocking: Whether this blocks further progress
    """
    async with _client() as c:
        body = {
            "mission_id": mission_id, "type": type, "description": description,
            "task_reference": task_reference, "context": context,
            "options": options, "recommendation": recommendation,
            "blocking": blocking,
        }
        r = await c.post("/api/checkpoints", json={k: v for k, v in body.items() if v is not None})
        _raise_with_detail(r)
        d = r.json()
        _session.checkpoints_raised.append(d["id"])
        return f"Checkpoint {d['id']} created ({type}, {'blocking' if blocking else 'non-blocking'})"


@tool()
async def rka_get_checkpoints(status: str = "open") -> str:
    """Get checkpoints. Defaults to open checkpoints.

    Args:
        status: open | resolved | dismissed
    """
    async with _client() as c:
        r = await c.get("/api/checkpoints", params={"status": status})
        _raise_with_detail(r)
        chks = r.json()
        if not chks:
            return f"No {status} checkpoints."
        lines = []
        for chk in chks:
            flag = "🔴 BLOCKING" if chk.get("blocking") else "🟡"
            lines.append(f"{flag} {chk['id']} [{chk['type']}]: {chk['description'][:300]}")
        return "\n".join(lines)


@tool()
async def rka_resolve_checkpoint(
    id: str,
    resolution: str,
    resolved_by: str,
    rationale: str | None = None,
    create_decision: bool = False,
) -> str:
    """Resolve a checkpoint.

    Args:
        id: Checkpoint ID
        resolution: The resolution decision
        resolved_by: pi | brain
        rationale: Why this resolution
        create_decision: Also create a linked decision node
    """
    async with _client() as c:
        body = {
            "resolution": resolution, "resolved_by": resolved_by,
            "rationale": rationale, "create_decision": create_decision,
        }
        r = await c.put(f"/api/checkpoints/{id}/resolve", json=body)
        _raise_with_detail(r)
        return f"Checkpoint {id} resolved by {resolved_by}"


# ============================================================
# Retrieval & Search
# ============================================================

@tool()
async def rka_search(
    query: str,
    entity_types: list[str] | None = None,
    limit: int = 20,
) -> str:
    """Search across all research knowledge.

    Results show truncated snippets. Use rka_get(id) to read the full content of any result.

    Args:
        query: Search query
        entity_types: Filter by type — decision | literature | journal | mission
        limit: Max results
    """
    session = _session
    async with _client() as c:
        body = {"query": query, "entity_types": entity_types, "limit": limit}
        r = await c.post("/api/search", json=body)
        _raise_with_detail(r)
        results = r.json()
        if not results:
            return f"No results for '{query}'"
        lines = []
        for res in results:
            lines.append(f"[{res['entity_type']}] {res['entity_id']}: {res['title']}")
            if res.get("snippet"):
                lines.append(f"  {res['snippet'][:500]}")
        return "\n".join(lines)


@tool()
async def rka_get(
    id: str,
) -> str:
    """Get the full content of any entity by ID.

    Use this when listing tools (rka_get_journal, rka_search, etc.) truncate
    content and you need to see the complete text. Supports all entity types.

    Args:
        id: Entity ID (e.g. jrn_01..., dec_01..., lit_01..., clm_01..., ecl_01..., mis_01...)
    """
    prefix = id.split("_")[0] if "_" in id else ""
    endpoint_map = {
        "jrn": f"/api/notes/{id}",
        "dec": f"/api/decisions/{id}",
        "lit": f"/api/literature/{id}",
        "clm": f"/api/claims/{id}",
        "ecl": f"/api/clusters/{id}",
        "mis": f"/api/missions/{id}",
    }
    endpoint = endpoint_map.get(prefix)
    if not endpoint:
        return f"Unknown ID prefix '{prefix}'. Expected: jrn_, dec_, lit_, clm_, ecl_, mis_"
    params = {}
    if prefix == "ecl":
        params["include_claims"] = "true"
    async with _client() as c:
        r = await c.get(endpoint, params=params)
        _raise_with_detail(r)
        data = r.json()
        # Format cluster claims inline for readability
        if prefix == "ecl" and data.get("claims"):
            claims = data["claims"]
            claim_summaries = []
            for cl in claims:
                content = cl.get("content", "")[:100]
                if len(cl.get("content", "")) > 100:
                    content += "…"
                v = "✓" if cl.get("verified") else "○"
                claim_summaries.append({
                    "id": cl["id"],
                    "type": cl.get("claim_type"),
                    "confidence": cl.get("confidence"),
                    "verified": v,
                    "content": content,
                })
            data["claims"] = claim_summaries
        return json.dumps(data, indent=2, default=str)


@tool()
async def rka_get_decision_tree(
    root_id: str | None = None,
    phase: str | None = None,
    active_only: bool = False,
) -> str:
    """Get the decision tree with linked entities at each node.

    Shows hierarchical decisions with children, chosen options,
    and linked missions/journal entries/literature from entity_links.
    Use rka_get(id) to read the full content of any decision.

    Args:
        root_id: Optional decision ID to get subtree only
        phase: Filter by phase
        active_only: Only show active decisions
    """
    async with _client() as c:
        params = {}
        if root_id:
            params["root_id"] = root_id
        r = await c.get("/api/graph/decision-tree", params=params)
        _raise_with_detail(r)
        tree = r.json()

        def fmt_node(node, indent=0):
            prefix = "  " * indent
            status = node.get("status", "?")
            chosen = node.get("chosen", "?")
            # Filter by phase/active if requested
            if phase and node.get("phase") != phase:
                return []
            if active_only and status != "active":
                return []
            decided_by = node.get("decided_by", "")
            decided_tag = f", {decided_by}" if decided_by else ""
            lines = [f"{prefix}[{status}{decided_tag}] {node['id']}: {node['question'][:300]}"]
            if chosen:
                lines.append(f"{prefix}  → Chosen: {chosen}")
            for le in node.get("linked_entities", []):
                lines.append(f"{prefix}  ↔ [{le['type']}] {le['id']} ({le['link_type']})")
            for child in node.get("children", []):
                lines.extend(fmt_node(child, indent + 1))
            return lines

        output = []
        for root in tree:
            output.extend(fmt_node(root))
        return "\n".join(output) if output else "No decisions found."


@tool()
async def rka_get_literature(
    status: str | None = None,
    query: str | None = None,
    limit: int = 20,
) -> str:
    """Get literature entries.

    Titles are truncated in listings. Use rka_get(id) to read the full record including abstract.

    Args:
        status: to_read | reading | read | cited | excluded
        query: Search in title/abstract
        limit: Max results
    """
    async with _client() as c:
        params = {"limit": limit}
        if status:
            params["status"] = status
        if query:
            params["query"] = query
        r = await c.get("/api/literature", params=params)
        _raise_with_detail(r)
        entries = r.json()
        if not entries:
            return "No literature entries found."
        lines = []
        for e in entries:
            authors = ", ".join(e.get("authors") or [])[:40]
            lines.append(f"{e['id']} [{e['status']}] {e['title'][:300]}")
            if authors:
                lines.append(f"  {authors} ({e.get('year', '?')})")
        return "\n".join(lines)


@tool()
async def rka_get_journal(
    type: str | None = None,
    phase: str | None = None,
    confidence: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> str:
    """Get journal entries.

    Content is truncated in listings. Use rka_get(id) to read the full content of any entry.

    Args:
        type: note | log | directive (legacy types like finding/insight also accepted)
        phase: Filter by phase
        confidence: hypothesis | tested | verified | superseded | retracted
        status: draft | active | superseded | retracted
        since: ISO date to filter from
        limit: Max results
    """
    async with _client() as c:
        params = {"limit": limit, "hide_superseded": True}
        if type:
            params["type"] = type
        if phase:
            params["phase"] = phase
        if confidence:
            params["confidence"] = confidence
        if status:
            params["status"] = status
        if since:
            params["since"] = since
        r = await c.get("/api/notes", params=params)
        _raise_with_detail(r)
        entries = r.json()
        if not entries:
            return "No journal entries found."
        lines = []
        for e in entries:
            pi_marker = " [PI]" if e.get("source") == "pi" else ""
            lines.append(f"{e['id']} [{e['type']}]{pi_marker} ({e['confidence']}) {e['content'][:500]}")
        return "\n".join(lines)


# ============================================================
# Project Selection
# ============================================================

@tool()
async def rka_list_projects() -> str:
    """List all available projects. Shows which project is currently active."""
    async with _client() as c:
        r = await c.get("/api/projects")
        _raise_with_detail(r)
        projects = r.json()

    active = _session.project_id or "proj_default"
    lines = ["## Projects", ""]
    for p in projects:
        marker = " (active)" if p["id"] == active else ""
        desc = f" — {p['description']}" if p.get("description") else ""
        lines.append(f"- **{p['id']}**: {p['name']}{desc}{marker}")
    if not projects:
        lines.append("No projects found.")
    return "\n".join(lines)


@tool()
async def rka_set_project(project_id: str) -> str:
    """Switch the active project for this MCP session.

    All subsequent tool calls will operate on the selected project.

    Args:
        project_id: Project ID or name to switch to (e.g. "prj_01KK...", "rka_development")
    """
    # Validate project exists — accept ID or name
    async with _client() as c:
        r = await c.get("/api/projects")
        _raise_with_detail(r)
        projects = r.json()

    # Try exact ID match first, then name match
    resolved_id = None
    for p in projects:
        if p["id"] == project_id:
            resolved_id = p["id"]
            break
    if resolved_id is None:
        for p in projects:
            if p["name"].lower() == project_id.lower():
                resolved_id = p["id"]
                break

    if resolved_id is None:
        available = "\n".join(f"  - `{p['id']}`: {p['name']}" for p in projects)
        return f"Project '{project_id}' not found. Available:\n{available}"

    _session.project_id = resolved_id

    # Fetch project status to confirm
    async with _client() as c:
        status_r = await c.get("/api/status")
        if status_r.is_success:
            status = status_r.json()
            name = status.get("project_name", resolved_id)
            phase = status.get("current_phase", "not set")
            return f"Switched to project **{name}** (`{resolved_id}`). Phase: {phase}"

    return f"Switched to project `{resolved_id}`."


@tool()
async def rka_create_project(
    name: str,
    description: str | None = None,
) -> str:
    """Create a new research project and switch to it.

    Args:
        name: Human-readable project name (e.g. "Climate Policy Analysis")
        description: Brief description of the research project
    """
    async with _client() as c:
        body = {"name": name}
        if description:
            body["description"] = description
        r = await c.post("/api/projects", json=body)
        _raise_with_detail(r)
        project = r.json()

    # Auto-switch to the new project
    _session.project_id = project["id"]

    return (
        f"Created project **{project['name']}** (`{project['id']}`).\n"
        f"Session switched to this project. All subsequent tool calls will target it."
    )


# ============================================================
# Project State
# ============================================================

@tool()
async def rka_get_status() -> str:
    """Get full project state: phase, active mission, open checkpoints, metrics."""
    async with _client() as c:
        # Gather all status info in parallel-ish (sequential for simplicity)
        status_r = await c.get("/api/status")
        _raise_with_detail(status_r)
        status = status_r.json()

        missions_r = await c.get("/api/missions", params={"status": "active", "limit": 1})
        active_missions = missions_r.json() if missions_r.status_code == 200 else []

        chk_r = await c.get("/api/checkpoints", params={"status": "open"})
        open_chks = chk_r.json() if chk_r.status_code == 200 else []

        lines = [
            f"## Project: {status['project_name']}",
            f"Phase: {status.get('current_phase', 'not set')}",
        ]
        if status.get("summary"):
            lines.append(f"Summary: {status['summary']}")
        if status.get("blockers"):
            lines.append(f"⚠️ Blockers: {status['blockers']}")

        if active_missions:
            m = active_missions[0]
            n_tasks = len(m.get("tasks") or [])
            lines.append(f"\n### Active Mission: {m['id']}")
            lines.append(f"Objective: {m['objective'][:500]}")
            lines.append(f"Tasks: {n_tasks}")

        if open_chks:
            lines.append(f"\n### Open Checkpoints: {len(open_chks)}")
            for chk in open_chks[:5]:
                flag = "🔴" if chk.get("blocking") else "🟡"
                lines.append(f"  {flag} {chk['id']}: {chk['description'][:300]}")

        return "\n".join(lines)


@tool()
async def rka_update_status(
    current_phase: str | None = None,
    summary: str | None = None,
    blockers: str | None = None,
    metrics: dict | None = None,
) -> str:
    """Update project state.

    Args:
        current_phase: New phase
        summary: Updated project summary
        blockers: Current blockers
        metrics: Key metrics dict
    """
    async with _client() as c:
        body = {
            "current_phase": current_phase, "summary": summary,
            "blockers": blockers, "metrics": metrics,
        }
        r = await c.put("/api/status", json={k: v for k, v in body.items() if v is not None})
        _raise_with_detail(r)
        return "Status updated"


# ============================================================
# Export
# ============================================================

# ============================================================
# Academic / Import Tools
# ============================================================

@tool()
async def rka_import_bibtex(
    bibtex: str,
    default_status: str = "to_read",
    skip_duplicates: bool = True,
) -> str:
    """Import literature entries from BibTeX content.

    Args:
        bibtex: Raw BibTeX string (one or more entries)
        default_status: Initial status for imported entries — to_read | reading | read
        skip_duplicates: Skip entries that already exist (by DOI or title)
    """
    async with _client() as c:
        body = {
            "bibtex": bibtex,
            "default_status": default_status,
            "added_by": "import",
            "skip_duplicates": skip_duplicates,
        }
        r = await c.post("/api/import/bibtex", json=body)
        _raise_with_detail(r)
        data = r.json()
        imported = data.get("imported", [])
        skipped = data.get("skipped", [])
        errors = data.get("errors", [])
        lines = [f"Parsed {data.get('total_parsed', 0)} entries:"]
        lines.append(f"  ✅ Imported: {len(imported)}")
        if skipped:
            lines.append(f"  ⏭️ Skipped: {len(skipped)}")
        if errors:
            lines.append(f"  ❌ Errors: {len(errors)}")
        for item in imported[:10]:
            lines.append(f"  + {item['id']}: {item['title']}")
        return "\n".join(lines)


@tool()
async def rka_enrich_doi(lit_id: str) -> str:
    """Enrich a literature entry by looking up its DOI via CrossRef.

    Automatically fills in missing title, authors, year, venue, abstract, and URL
    from the CrossRef database. Requires the entry to have a DOI set.

    Args:
        lit_id: Literature entry ID
    """
    async with _client() as c:
        r = await c.post(f"/api/literature/{lit_id}/enrich-doi")
        _raise_with_detail(r)
        data = r.json()
        if data.get("status") == "enriched":
            return f"Enriched {lit_id}: updated {', '.join(data['fields_updated'])}"
        return f"No updates needed for {lit_id}"


@tool()
async def rka_export_mermaid(
    phase: str | None = None,
    active_only: bool = False,
) -> str:
    """Export the decision tree as a Mermaid flowchart diagram.

    Returns Mermaid markdown that can be pasted into docs, GitHub, or mermaid.live.

    Args:
        phase: Filter to a specific research phase
        active_only: Only include active decisions
    """
    async with _client() as c:
        params = {}
        if phase:
            params["phase"] = phase
        if active_only:
            params["active_only"] = "true"
        r = await c.get("/api/decisions/mermaid", params=params)
        _raise_with_detail(r)
        data = r.json()
        return data.get("mermaid", "graph TD\n    empty[No decisions yet]")


@tool()
async def rka_batch_import(
    entries: list[dict],
    actor: str = "import",
) -> str:
    """Batch import multiple entries at once.

    Each entry must have 'entity_type' and 'data' fields.

    Args:
        entries: List of {entity_type: "note"|"literature"|"decision", data: {...}}
        actor: Who is importing — brain | executor | pi | import
    """
    async with _client() as c:
        body = {"entries": entries, "actor": actor}
        r = await c.post("/api/import/batch", json=body)
        _raise_with_detail(r)
        data = r.json()
        imported = data.get("imported", [])
        errors = data.get("errors", [])
        lines = [f"Batch import: {len(imported)} imported, {len(errors)} errors"]
        for item in imported[:10]:
            lines.append(f"  + [{item['type']}] {item['id']}")
        for err in errors[:5]:
            lines.append(f"  ❌ Entry {err['index']}: {err['error']}")
        return "\n".join(lines)


@tool()
async def rka_ingest_document(
    content: str,
    source: str = "brain",
    default_type: str = "finding",
    phase: str | None = None,
    tags: list[str] | None = None,
    related_literature: list[str] | None = None,
    related_decisions: list[str] | None = None,
    related_mission: str | None = None,
    split_by_headings: bool = True,
) -> str:
    """Ingest a markdown document by splitting it into journal entries.

    Accepts a full markdown document (e.g. a report, analysis, literature review)
    and automatically splits it by headings (## or ###) into individual journal entries.
    Each section becomes its own entry with auto-classified type and tags derived
    from the heading. Ideal for the Brain to send structured context to the
    knowledge base.

    Args:
        content: Markdown document content to ingest
        source: Who is sending this — brain | executor | pi
        default_type: Default entry type if not auto-classified — finding | insight | methodology | observation | idea | exploration | hypothesis
        phase: Research phase for all created entries
        tags: Base tags applied to all entries (section-specific tags are added automatically)
        related_literature: Literature IDs all entries relate to
        related_decisions: Decision IDs all entries relate to
        related_mission: Mission ID all entries belong to
        split_by_headings: Whether to split by ## / ### headings (default: true). If false, creates one entry.
    """
    async with _client() as c:
        body = {
            "content": content, "source": source,
            "default_type": default_type, "phase": phase,
            "tags": tags, "related_literature": related_literature,
            "related_decisions": related_decisions,
            "related_mission": related_mission,
            "split_by_headings": split_by_headings,
        }
        r = await c.post("/api/ingest/document", json={k: v for k, v in body.items() if v is not None})
        _raise_with_detail(r)
        data = r.json()
        created = data.get("created", [])
        errors = data.get("errors", [])
        lines = [f"Ingested document: {len(created)} entries created from {data.get('total_sections', 0)} sections"]
        for item in created:
            lines.append(f"  + {item['id']} [{item['type']}] {item['heading']} ({item['length']} chars)")
        if errors:
            lines.append(f"\n❌ {len(errors)} errors:")
            for err in errors:
                lines.append(f"  - {err['section']}: {err['error']}")
        return "\n".join(lines)


# ============================================================
# Export
# ============================================================

@tool()
async def rka_export(format: str = "markdown", scope: str = "state") -> str:
    """Export research data.

    Args:
        format: markdown | json | mermaid (mermaid only for decisions scope)
        scope: state | decisions | literature | full
    """
    async with _client() as c:
        if scope == "state":
            r = await c.get("/api/status")
            _raise_with_detail(r)
            if format == "json":
                return json.dumps(r.json(), indent=2)
            s = r.json()
            return f"# {s['project_name']}\n\nPhase: {s.get('current_phase')}\n\n{s.get('summary', '')}"

        elif scope == "decisions":
            if format == "mermaid":
                r = await c.get("/api/decisions/mermaid")
                _raise_with_detail(r)
                return r.json().get("mermaid", "")
            r = await c.get("/api/decisions/tree")
            _raise_with_detail(r)
            return json.dumps(r.json(), indent=2)

        elif scope == "literature":
            r = await c.get("/api/literature", params={"limit": 200})
            _raise_with_detail(r)
            if format == "json":
                return json.dumps(r.json(), indent=2)
            entries = r.json()
            lines = []
            for e in entries:
                authors = ", ".join(e.get("authors") or [])
                lines.append(f"- [{e['status']}] {e['title']} ({authors}, {e.get('year', '?')})")
            return "\n".join(lines)

        else:
            return "Export scope 'full' not yet implemented. Use state/decisions/literature."


# ============================================================
# Phase 2: Context, Summarization, Eviction
# ============================================================

@tool()
async def rka_get_context(
    topic: str | None = None,
    phase: str | None = None,
    depth: str = "summary",
    max_tokens: int = 2000,
) -> str:
    """Get focused context package with relevant knowledge.

    Returns temperature-classified entries (HOT/WARM/COLD) optimized
    for the token budget. HOT entries are included verbatim; WARM/COLD
    are summarized when needed.

    Args:
        topic: Search topic for semantic context retrieval
        phase: Filter to specific research phase
        depth: "summary" (default) or "detailed" with LLM narrative
        max_tokens: Token budget for context package (default: 2000)
    """
    async with _client() as c:
        body = {
            "topic": topic, "phase": phase,
            "depth": depth, "max_tokens": max_tokens,
        }
        r = await c.post("/api/context", json={k: v for k, v in body.items() if v is not None})
        _raise_with_detail(r)
        pkg = r.json()

        lines = []
        if pkg.get("topic"):
            lines.append(f"## Context: {pkg['topic']}")
        if pkg.get("phase"):
            lines.append(f"Phase: {pkg['phase']}")
        if pkg.get("note"):
            lines.append(f"⚠️ {pkg['note']}")

        if pkg.get("hot_entries"):
            lines.append(f"\n### 🔴 Active ({len(pkg['hot_entries'])})")
            lines.extend(pkg["hot_entries"])

        if pkg.get("warm_entries"):
            lines.append(f"\n### 🟡 Relevant ({len(pkg['warm_entries'])})")
            lines.extend(pkg["warm_entries"])

        if pkg.get("cold_entries"):
            lines.append(f"\n### 🔵 Background ({len(pkg['cold_entries'])})")
            lines.extend(pkg["cold_entries"])

        if pkg.get("narrative"):
            lines.append("\n### Narrative")
            lines.append(pkg["narrative"])

        if pkg.get("sources"):
            lines.append(f"\n---\nSources: {', '.join(pkg['sources'][:10])}")

        return "\n".join(lines)


@tool()
async def rka_summarize(
    topic: str | None = None,
    phase: str | None = None,
    entity_ids: list[str] | None = None,
) -> str:
    """On-demand topic summarization. Produces a narrative summary
    stored as a journal entry.

    Args:
        topic: Topic to summarize
        phase: Filter to specific phase
        entity_ids: Specific entity IDs to summarize (overrides topic)
    """
    async with _client() as c:
        body = {"topic": topic, "phase": phase, "entity_ids": entity_ids}
        r = await c.post("/api/summarize", json={k: v for k, v in body.items() if v is not None})
        _raise_with_detail(r)
        data = r.json()
        return (
            f"Summary created: {data.get('summary_id', 'unknown')}\n"
            f"Sources: {data.get('source_count', 0)}\n\n"
            f"{data.get('summary', '')}"
        )


@tool()
async def rka_eviction_sweep(dry_run: bool = True) -> str:
    """Propose entries for archival based on staleness rules.

    Finds superseded, abandoned, and unreferenced entries that can be
    safely archived. Default is dry_run=True (preview only).

    Args:
        dry_run: If true, show what would be archived without taking action
    """
    async with _client() as c:
        r = await c.post("/api/eviction-sweep", params={"dry_run": str(dry_run).lower()})
        _raise_with_detail(r)
        data = r.json()
        proposed = data.get("proposed", [])
        if not proposed:
            return "No entries proposed for eviction. Knowledge base is clean."

        lines = [f"{'[DRY RUN] ' if data.get('dry_run') else ''}Eviction Proposal: {len(proposed)} entries"]
        for item in proposed:
            lines.append(f"  [{item['entity_type']}] {item['entity_id']}: {item['title']}")
            lines.append(f"    Reason: {item['reason']}")
        return "\n".join(lines)


# ============================================================
# Academic Search (Semantic Scholar + arXiv)
# ============================================================

@tool()
async def rka_search_semantic_scholar(
    query: str,
    limit: int = 10,
    year_min: int | None = None,
    fields_of_study: list[str] | None = None,
    add_to_library: bool = False,
) -> str:
    """Search Semantic Scholar for academic papers.

    Args:
        query: Search query
        limit: Max results (default: 10)
        year_min: Minimum publication year filter
        fields_of_study: Filter by field (e.g. ["Computer Science"])
        add_to_library: If true, automatically add results to RKA literature
    """
    import httpx as hx

    params = {"query": query, "limit": min(limit, 50)}
    fields = "title,authors,year,venue,abstract,externalIds,url,citationCount"
    params["fields"] = fields
    if year_min:
        params["year"] = f"{year_min}-"

    try:
        async with hx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params=params,
            )
            _raise_with_detail(r)
            data = r.json()
    except Exception as exc:
        return f"Semantic Scholar search failed: {exc}"

    papers = data.get("data", [])
    if not papers:
        return f"No results for '{query}'"

    lines = [f"Found {data.get('total', len(papers))} papers (showing {len(papers)}):"]
    added_ids = []

    for p in papers:
        authors = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:3])
        if len(p.get("authors") or []) > 3:
            authors += " et al."
        doi = (p.get("externalIds") or {}).get("DOI", "")
        cites = p.get("citationCount", 0)

        lines.append(f"\n📄 {p.get('title', 'Untitled')}")
        lines.append(f"   {authors} ({p.get('year', '?')}) — {p.get('venue', 'Unknown')}")
        if doi:
            lines.append(f"   DOI: {doi}")
        lines.append(f"   Citations: {cites}")
        if p.get("abstract"):
            lines.append(f"   {p['abstract'][:200]}...")

        if add_to_library:
            try:
                async with _client() as c:
                    body = {
                        "title": p.get("title", "Untitled"),
                        "authors": [a.get("name", "") for a in (p.get("authors") or [])],
                        "year": p.get("year"),
                        "venue": p.get("venue"),
                        "doi": doi or None,
                        "url": p.get("url"),
                        "abstract": p.get("abstract"),
                        "added_by": "import",
                    }
                    resp = await c.post("/api/literature", json={k: v for k, v in body.items() if v is not None})
                    if resp.status_code == 201:
                        lit_id = resp.json()["id"]
                        added_ids.append(lit_id)
                        lines.append(f"   → Added as {lit_id}")
            except Exception:
                pass  # Skip silently if add fails (e.g. duplicate DOI)

    if added_ids:
        lines.append(f"\n✅ Added {len(added_ids)} papers to library")

    return "\n".join(lines)


@tool()
async def rka_search_arxiv(
    query: str,
    limit: int = 10,
    sort_by: str = "relevance",
    add_to_library: bool = False,
) -> str:
    """Search arXiv for preprints and papers.

    Args:
        query: Search query (supports arXiv query syntax like au:surname, ti:keyword)
        limit: Max results (default: 10)
        sort_by: relevance | lastUpdatedDate | submittedDate
        add_to_library: If true, automatically add results to RKA literature
    """
    import httpx as hx

    params = {
        "search_query": f"all:{query}",
        "max_results": min(limit, 50),
        "sortBy": sort_by,
        "sortOrder": "descending",
    }

    try:
        async with hx.AsyncClient(timeout=15.0) as client:
            r = await client.get("http://export.arxiv.org/api/query", params=params)
            _raise_with_detail(r)
            xml_text = r.text
    except Exception as exc:
        return f"arXiv search failed: {exc}"

    # Parse Atom XML (lightweight, no external dep)
    import re
    entries = re.findall(r"<entry>(.*?)</entry>", xml_text, re.DOTALL)
    if not entries:
        return f"No arXiv results for '{query}'"

    lines = [f"Found {len(entries)} arXiv papers:"]
    added_ids = []

    for entry_xml in entries:
        title = _xml_text(entry_xml, "title").replace("\n", " ").strip()
        summary = _xml_text(entry_xml, "summary").replace("\n", " ").strip()
        published = _xml_text(entry_xml, "published")[:10]
        year = int(published[:4]) if published else None
        arxiv_id = _xml_text(entry_xml, "id")

        # Extract authors
        authors = re.findall(r"<name>(.*?)</name>", entry_xml)

        # Extract categories
        categories = re.findall(r'category term="([^"]+)"', entry_xml)

        author_str = ", ".join(authors[:3])
        if len(authors) > 3:
            author_str += " et al."

        lines.append(f"\n📄 {title}")
        lines.append(f"   {author_str} ({published})")
        lines.append(f"   arXiv: {arxiv_id}")
        if categories:
            lines.append(f"   Categories: {', '.join(categories[:3])}")
        if summary:
            lines.append(f"   {summary[:200]}...")

        if add_to_library:
            try:
                async with _client() as c:
                    body = {
                        "title": title,
                        "authors": authors,
                        "year": year,
                        "url": arxiv_id,
                        "abstract": summary,
                        "added_by": "import",
                    }
                    resp = await c.post("/api/literature", json={k: v for k, v in body.items() if v is not None})
                    if resp.status_code == 201:
                        lit_id = resp.json()["id"]
                        added_ids.append(lit_id)
                        lines.append(f"   → Added as {lit_id}")
            except Exception:
                pass

    if added_ids:
        lines.append(f"\n✅ Added {len(added_ids)} papers to library")

    return "\n".join(lines)


def _xml_text(xml: str, tag: str) -> str:
    """Extract text from first occurrence of <tag>...</tag>."""
    import re
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xml, re.DOTALL)
    return m.group(1).strip() if m else ""


# ============================================================
# Workspace Bootstrap
# ============================================================

@tool()
async def rka_scan_workspace(
    folder_path: str,
    ignore_patterns: list[str] | None = None,
    max_file_size_mb: float = 50.0,
    use_llm: bool = True,
) -> str:
    """Scan a workspace folder and preview what would be ingested.

    Classifies files by extension + content heuristics (+ optional LLM).
    Returns a manifest showing each file's category, proposed type, and tags.
    Use this to review before running rka_bootstrap_workspace.

    Args:
        folder_path: Absolute path to the workspace folder
        ignore_patterns: Additional patterns to ignore (e.g. ["*.log", "drafts"])
        max_file_size_mb: Skip files larger than this (default: 50MB)
        use_llm: Use local LLM for smarter classification when available (default: true)
    """
    async with _client() as c:
        body = {
            "folder_path": folder_path,
            "ignore_patterns": ignore_patterns or [],
            "include_preview": True,
            "max_file_size_mb": max_file_size_mb,
            "use_llm": use_llm,
        }
        r = await c.post("/api/workspace/scan", json=body, timeout=120.0)
        _raise_with_detail(r)
        data = r.json()

    # Format summary for the Brain
    files = data.get("files", [])
    summary = data.get("summary", {})
    caps = data.get("capabilities", {})
    warnings = data.get("warnings", [])

    lines = [
        f"📂 Scanned: {data['root_path']}",
        f"   Scan ID: {data['scan_id']}",
        f"   Files found: {data['total_files_found']}, scanned: {data['total_files_scanned']}",
        f"   Capabilities: pymupdf={'✓' if caps.get('pymupdf_available') else '✗'}, "
        f"docx={'✓' if caps.get('python_docx_available') else '✗'}, "
        f"llm={'✓' if caps.get('llm_available') else '✗'}",
    ]

    if summary.get("by_category"):
        lines.append(f"\n📊 By category: {summary['by_category']}")
    if summary.get("by_target"):
        lines.append(f"📊 By target: {summary['by_target']}")
    if summary.get("duplicate_count"):
        lines.append(f"⚠️  Duplicates (already ingested): {summary['duplicate_count']}")
    if summary.get("llm_classified_count"):
        lines.append(f"🤖 LLM-classified: {summary['llm_classified_count']}")

    # Group files by ingestion target
    by_target: dict[str, list] = {}
    for f in files:
        target = f.get("ingestion_target", "skip")
        by_target.setdefault(target, []).append(f)

    for target, target_files in sorted(by_target.items()):
        lines.append(f"\n{'─' * 40}")
        lines.append(f"Target: {target} ({len(target_files)} files)")
        for f in target_files:
            dup = " [DUP]" if f.get("is_duplicate") else ""
            llm = " [LLM]" if f.get("llm_classified") else ""
            tags = f", tags={f['proposed_tags']}" if f.get("proposed_tags") else ""
            title = f" — {f['title_suggestion']}" if f.get("title_suggestion") else ""
            lines.append(
                f"  • {f['relative_path']} [{f['category']}→{f['proposed_type']}]{tags}{title}{dup}{llm}"
            )

    if warnings:
        lines.append(f"\n⚠️  Warnings ({len(warnings)}):")
        for w in warnings[:10]:
            lines.append(f"  - {w}")

    lines.append(f"\n💡 Run rka_bootstrap_workspace(folder_path='{folder_path}') to ingest.")
    return "\n".join(lines)


@tool()
async def rka_bootstrap_workspace(
    folder_path: str,
    phase: str | None = None,
    override_tags: list[str] | None = None,
    skip_files: list[str] | None = None,
    use_llm: bool = True,
    dry_run: bool = False,
) -> str:
    """One-shot workspace bootstrap: scan + ingest all files in a folder.

    This is the primary tool for quickly bootstrapping a knowledge base.
    Scans the folder, classifies files, and ingests them into RKA.
    After completion, use rka_review_bootstrap to get a summary for reorganization.

    Args:
        folder_path: Absolute path to the workspace folder
        phase: Research phase to assign to all entries
        override_tags: Tags to add to all ingested entries
        skip_files: Relative paths of files to skip
        use_llm: Use local LLM for classification (default: true)
        dry_run: Preview what would be created without actually ingesting
    """
    # Step 1: Scan
    async with _client() as c:
        scan_body = {
            "folder_path": folder_path,
            "ignore_patterns": [],
            "include_preview": True,
            "max_file_size_mb": 50.0,
            "use_llm": use_llm,
        }
        r = await c.post("/api/workspace/scan", json=scan_body, timeout=120.0)
        _raise_with_detail(r)
        manifest = r.json()

    # Step 2: Ingest
    async with _client() as c:
        ingest_body = {
            "manifest": manifest,
            "skip_files": skip_files or [],
            "override_tags": override_tags or [],
            "phase": phase,
            "source": "pi",
            "dry_run": dry_run,
        }
        r = await c.post("/api/workspace/ingest", json=ingest_body, timeout=300.0)
        _raise_with_detail(r)
        result = r.json()

    # Format response
    prefix = "🔍 DRY RUN — " if dry_run else "✅ "
    lines = [
        f"{prefix}Bootstrap complete for {folder_path}",
        f"   Scan ID: {manifest['scan_id']}",
        f"   Processed: {result['total_processed']}, Created: {result['total_created']}, "
        f"Skipped: {result['total_skipped']}, Errors: {result['total_errors']}",
    ]

    # Show results grouped by category
    for item in result.get("results", []):
        if item.get("error") and not item.get("success"):
            lines.append(f"  ❌ {item['relative_path']}: {item['error']}")
        elif item.get("entity_ids"):
            lines.append(
                f"  ✓ {item['relative_path']} → {item['entity_count']} entries "
                f"({', '.join(item['entity_ids'][:3])}{'...' if len(item.get('entity_ids', [])) > 3 else ''})"
            )

    if not dry_run:
        lines.append(
            f"\n💡 Run rka_review_bootstrap(scan_id='{manifest['scan_id']}') "
            f"to get a summary for reorganization."
        )

    return "\n".join(lines)


@tool()
async def rka_review_bootstrap(scan_id: str) -> str:
    """Review a completed bootstrap for reorganization.

    Returns entry counts, singleton tags, entries needing attention,
    and suggested next actions. Use after rka_bootstrap_workspace.

    Args:
        scan_id: The scan ID from rka_bootstrap_workspace output
    """
    async with _client() as c:
        r = await c.get(f"/api/workspace/review/{scan_id}", timeout=60.0)
        _raise_with_detail(r)
        data = r.json()

    lines = [
        f"📋 Bootstrap Review — {data['scan_id']}",
        f"   Total entries created: {data['total_entries_created']}",
    ]

    if data.get("entries_by_type"):
        lines.append(f"\n📊 By type: {data['entries_by_type']}")
    if data.get("entries_by_category"):
        lines.append(f"📊 By source category: {data['entries_by_category']}")
    if data.get("all_tags"):
        lines.append(f"🏷️  Tags ({len(data['all_tags'])}): {', '.join(data['all_tags'][:20])}")
    if data.get("singleton_tags"):
        lines.append(f"⚠️  Singleton tags: {', '.join(data['singleton_tags'][:15])}")
    if data.get("needs_attention"):
        lines.append(
            f"🔍 Entries needing attention: {len(data['needs_attention'])} "
            f"({', '.join(data['needs_attention'][:5])})"
        )

    if data.get("suggestions"):
        lines.append("\n📌 Suggested next actions:")
        for s in data["suggestions"]:
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(s["priority"], "•")
            lines.append(f"  {icon} [{s['priority']}] {s['action']}")
            lines.append(f"     {s['details']}")

    if data.get("narrative"):
        lines.append(f"\n📝 Overview:\n{data['narrative']}")

    return "\n".join(lines)


# ============================================================
# LLM Enrichment
# ============================================================

# ============================================================
# Graph & Research Map
# ============================================================

@tool()
async def rka_get_graph(
    include_types: str | None = None,
    phase: str | None = None,
    limit: int = 500,
) -> str:
    """Get the full knowledge graph as nodes and edges for the research map.

    Returns all entities and their relationships from entity_links.

    Args:
        include_types: Comma-separated entity types to include (e.g. "decision,mission,journal")
        phase: Filter by research phase
        limit: Max entities per type (default 500)
    """
    async with _client() as c:
        params = {"limit": limit}
        if include_types:
            params["include_types"] = include_types
        if phase:
            params["phase"] = phase
        r = await c.get("/api/graph", params=params)
        _raise_with_detail(r)
        d = r.json()
        return (
            f"Knowledge graph: {len(d['nodes'])} nodes, {len(d['edges'])} edges\n\n"
            f"Nodes by type:\n"
            + "\n".join(f"  {t}: {sum(1 for n in d['nodes'] if n['type'] == t)}"
                       for t in sorted(set(n['type'] for n in d['nodes'])))
            + "\n\nEdges by type:\n"
            + "\n".join(f"  {t}: {sum(1 for e in d['edges'] if e['link_type'] == t)}"
                       for t in sorted(set(e['link_type'] for e in d['edges'])))
        )


@tool()
async def rka_get_ego_graph(entity_id: str, depth: int = 1) -> str:
    """Get the neighborhood subgraph around a specific entity.

    Shows all entities connected to the given entity within `depth` hops.

    Args:
        entity_id: The entity to center on (e.g. dec_01H..., jrn_01H...)
        depth: Number of hops to traverse (1-3, default 1)
    """
    async with _client() as c:
        r = await c.get(f"/api/graph/ego/{entity_id}", params={"depth": depth})
        _raise_with_detail(r)
        d = r.json()
        lines = [f"Ego graph for {entity_id}: {len(d['nodes'])} nodes, {len(d['edges'])} edges\n"]
        for node in d["nodes"]:
            marker = " ← CENTER" if node["id"] == entity_id else ""
            lines.append(f"  [{node['type']}] {node['id']}: {node['label'][:300]}{marker}")
        lines.append("\nEdges:")
        for edge in d["edges"]:
            lines.append(f"  {edge['source']} --{edge['link_type']}--> {edge['target']}")
        return "\n".join(lines)



@tool()
async def rka_graph_stats() -> str:
    """Get knowledge graph statistics: entity counts, edge counts by type."""
    async with _client() as c:
        r = await c.get("/api/graph/stats")
        _raise_with_detail(r)
        d = r.json()
        lines = [f"Knowledge graph: {d['total_nodes']} nodes, {d['total_edges']} edges\n"]
        lines.append("Nodes:")
        for etype, count in d["node_counts"].items():
            lines.append(f"  {etype}: {count}")
        lines.append("\nEdges by type:")
        for ltype, count in d.get("edge_counts_by_type", {}).items():
            lines.append(f"  {ltype}: {count}")
        return "\n".join(lines)


# ============================================================
# Summaries & QA (NotebookLM-style)
# ============================================================

@tool()
async def rka_generate_summary(
    scope_type: str = "project",
    scope_id: str | None = None,
    granularity: str = "paragraph",
) -> str:
    """Generate a multi-granularity summary of research progress.

    Gathers evidence from the knowledge base and produces a summary
    with source citations and identified knowledge gaps.

    Args:
        scope_type: What to summarize — project | phase | mission | tag
        scope_id: Scope ID (e.g. phase name, mission ID, tag name). None for project-wide.
        granularity: Detail level — one_line | paragraph | narrative
    """
    async with _client() as c:
        r = await c.post("/api/summaries/generate", json={
            "scope_type": scope_type,
            "scope_id": scope_id,
            "granularity": granularity,
        })
        _raise_with_detail(r)
        d = r.json()
        if "error" in d:
            return f"Summary generation failed: {d['error']}"
        lines = [f"Summary ({d.get('granularity', granularity)}) — confidence: {d.get('confidence', '?')}\n"]
        if d.get("one_line"):
            lines.append(f"One-line: {d['one_line']}\n")
        if d.get("paragraph"):
            lines.append(f"Paragraph:\n{d['paragraph']}\n")
        if d.get("narrative"):
            lines.append(f"Narrative:\n{d['narrative']}\n")
        if d.get("key_questions"):
            lines.append("Open questions:")
            for q in d["key_questions"]:
                lines.append(f"  - {q}")
        if d.get("sources"):
            lines.append(f"\nSources cited: {len(d['sources'])}")
            for s in d["sources"][:5]:
                lines.append(f"  [{s['entity_type']}:{s['entity_id']}] {s.get('excerpt', '')[:300]}")
        return "\n".join(lines)


@tool()
async def rka_ask(
    question: str,
    session_id: str | None = None,
    scope_type: str | None = None,
    scope_id: str | None = None,
) -> str:
    """Ask a research question and get an answer grounded in knowledge base evidence.

    Like NotebookLM: answers cite specific sources and suggest follow-up questions.
    Use session_id for multi-turn Q&A conversations.

    Args:
        question: Your research question
        session_id: Optional session ID for follow-up questions
        scope_type: Optional scope filter (phase, tag)
        scope_id: Optional scope ID
    """
    async with _client() as c:
        r = await c.post("/api/qa/ask", json={
            "question": question,
            "session_id": session_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
        })
        _raise_with_detail(r)
        d = r.json()
        if "error" in d:
            return f"QA failed: {d['error']}"
        lines = [
            f"Answer (confidence: {d.get('confidence', '?')}):\n",
            d.get("answer", "No answer"),
        ]
        if d.get("sources"):
            lines.append(f"\n\nSources ({len(d['sources'])}):")
            for i, s in enumerate(d["sources"]):
                lines.append(f"  [{i}] [{s['entity_type']}:{s['entity_id']}] \"{s.get('excerpt', '')[:300]}\"")
        if d.get("followups"):
            lines.append("\nSuggested follow-ups:")
            for f in d["followups"]:
                lines.append(f"  → {f}")
        lines.append(f"\nSession: {d.get('session_id', 'N/A')}")
        return "\n".join(lines)


# ============================================================
# Session State
# ============================================================

@tool()
async def rka_session_digest() -> str:
    """Get a compact summary of the current MCP session."""
    session = _session

    lines = [
        "## Session Digest",
        f"Active project: {session.project_id or 'proj_default (implicit)'}",
        f"Tool calls: {session.tool_calls}",
        f"Session started: {session.session_start}",
    ]

    if session.entities_created:
        lines.append(f"\n### Entities Created ({len(session.entities_created)})")
        for entry in session.entities_created:
            lines.append(f"  [{entry['type']}] {entry['id']}: {entry['summary']}")

    if session.decisions_made:
        lines.append(f"\n### Decisions Recorded ({len(session.decisions_made)})")
        for decision_id in session.decisions_made:
            lines.append(f"  {decision_id}")

    if session.checkpoints_raised:
        lines.append(f"\n### Checkpoints Raised ({len(session.checkpoints_raised)})")
        for checkpoint_id in session.checkpoints_raised:
            lines.append(f"  {checkpoint_id}")

    try:
        async with _client() as c:
            status_r = await c.get("/api/status")
            if status_r.is_success:
                status = status_r.json()
                lines.append("\n### Current Project State")
                lines.append(f"Phase: {status.get('current_phase', '?')}")
                if status.get("summary"):
                    lines.append(f"Summary: {status['summary'][:500]}")
                if status.get("blockers"):
                    lines.append(f"Blockers: {status['blockers']}")

            chk_r = await c.get("/api/checkpoints", params={"status": "open"})
            if chk_r.is_success:
                checkpoints = chk_r.json()
                if checkpoints:
                    lines.append(f"\n### Open Checkpoints ({len(checkpoints)})")
                    for chk in checkpoints[:5]:
                        flag = "🔴" if chk.get("blocking") else "🟡"
                        lines.append(f"  {flag} {chk['id']}: {chk['description'][:300]}")
    except Exception:
        pass

    lines.append(
        "\n---\nUse this digest as the compact session context instead of retaining earlier tool output."
    )
    return "\n".join(lines)


@tool()
async def rka_reset_session() -> str:
    """Reset MCP session tracking state without restarting the MCP server.

    Preserves the active project selection.
    """
    global _session
    prev_project = _session.project_id
    _session = MCPSessionState()
    _session.project_id = prev_project
    return f"Session state reset. Output verbosity and digest history cleared. Active project: {prev_project or 'proj_default (implicit)'}"


@tool()
async def rka_generate_claude_md(
    role: str = "executor",
) -> str:
    """Generate a project-specific CLAUDE.md for Claude Code.

    Queries the live RKA database and produces a CLAUDE.md tailored to
    the current project state: active phase, established tags, open missions,
    research questions, recording conventions, and v2.0 tool guidance.

    Args:
        role: Target role — "executor" (default) or "brain"
    """
    async with _client() as c:
        r = await c.get("/api/generate-claude-md", params={"role": role})
        _raise_with_detail(r)
    data = r.json()
    md = data.get("markdown", "")
    return f"Generated CLAUDE.md for role '{data.get('role', role)}':\n\n{md}"


# ============================================================
# v2.0: Research Map, Claims, Provenance, Review Queue
# ============================================================

@tool()
async def rka_list_clusters(
    research_question_id: str | None = None,
    confidence: str | None = None,
    limit: int = 50,
) -> str:
    """List evidence clusters with claim counts.

    Returns cluster ID, label, confidence, claim count, research question,
    and truncated synthesis for each cluster.

    Args:
        research_question_id: Filter to clusters under a specific RQ (dec_... ID)
        confidence: Filter by confidence level: strong, moderate, emerging, contested, refuted
        limit: Max results (default 50)
    """
    params: dict = {"limit": limit}
    if research_question_id:
        params["research_question_id"] = research_question_id
    if confidence:
        params["confidence"] = confidence
    async with _client() as c:
        r = await c.get("/api/clusters", params=params)
        _raise_with_detail(r)
    clusters = r.json()
    if not clusters:
        return "No clusters found matching filters."
    lines = [f"Found {len(clusters)} clusters:"]
    for cl in clusters:
        conf = cl.get("confidence", "emerging")
        rq = cl.get("research_question_id") or "unassigned"
        lines.append(
            f"  [{conf}] {cl['id']} — {cl['label']} "
            f"({cl.get('claim_count', 0)} claims)"
        )
        lines.append(f"    RQ: {rq}")
        synthesis = cl.get("synthesis") or ""
        if synthesis:
            lines.append(f"    {synthesis[:100]}{'…' if len(synthesis) > 100 else ''}")
    return "\n".join(lines)


@tool()
async def rka_get_research_map() -> str:
    """Get the three-level research map: Research Questions → Evidence Clusters → Claims.

    Returns a structured overview of all research questions with cluster counts,
    confidence indicators, gap counts, and contradiction flags.
    """
    async with _client() as c:
        r = await c.get("/api/research-map")
        _raise_with_detail(r)
    data = r.json()
    lines = []
    summary = data.get("summary", {})
    lines.append(f"Research Map: {summary.get('total_rqs', 0)} RQs, "
                 f"{summary.get('total_clusters', 0)} clusters, "
                 f"{summary.get('total_claims', 0)} claims")
    lines.append(f"Gaps: {summary.get('total_gaps', 0)} | "
                 f"Contradictions: {summary.get('total_contradictions', 0)} | "
                 f"Pending review: {summary.get('pending_review', 0)}")
    lines.append("")
    for rq in data.get("research_questions", []):
        rq_status_icons = {
            "open": "●", "active": "●", "partially_answered": "◐",
            "answered": "✓", "reframed": "↻", "closed": "○",
        }
        status_icon = rq_status_icons.get(rq.get("status", ""), "●")
        total_claims = rq.get("total_claims", 0)
        cluster_count = rq.get("cluster_count", 0)
        lines.append(f"{status_icon} [{rq['id']}] {rq['question']}")
        lines.append(f"  {cluster_count} clusters, {total_claims} claims, "
                     f"{rq.get('gap_count', 0)} gaps, "
                     f"{rq.get('contradiction_count', 0)} contradictions")
        clusters = rq.get("clusters", [])
        max_shown = 10
        for i, cl in enumerate(clusters[:max_shown]):
            connector = "└─" if i == len(clusters[:max_shown]) - 1 and len(clusters) <= max_shown else "├─"
            lines.append(
                f"  {connector} [{cl.get('confidence', '?')}] {cl['label']} "
                f"({cl.get('claim_count', 0)} claims) — {cl['id']}"
            )
        if len(clusters) > max_shown:
            lines.append(f"  └─ ... ({len(clusters) - max_shown} more)")
    unassigned = data.get("unassigned_clusters", [])
    if unassigned:
        lines.append(f"\nUnassigned clusters: {len(unassigned)}")
        for uc in unassigned[:5]:
            lines.append(f"  - [{uc.get('confidence', '?')}] {uc['label']} "
                         f"({uc.get('claim_count', 0)} claims) — {uc['id']}")
        if len(unassigned) > 5:
            lines.append(f"  ... ({len(unassigned) - 5} more)")
    return "\n".join(lines)


@tool()
async def rka_get_claims(
    source_entry_id: str | None = None,
    cluster_id: str | None = None,
    claim_type: str | None = None,
    verified: bool | None = None,
    stale: bool | None = None,
    limit: int = 20,
) -> str:
    """Query claims with filters.

    Claim content is truncated in listings. Use rka_get(id) to read the full claim.

    Args:
        source_entry_id: Filter by source journal entry ID
        cluster_id: Filter by evidence cluster ID
        claim_type: Filter by type: hypothesis, evidence, method, result, observation, assumption
        verified: Filter by verification status
        stale: Filter by stale status (true = needs re-distillation)
        limit: Max results (default 20)
    """
    params = {"limit": limit}
    if source_entry_id:
        params["source_entry_id"] = source_entry_id
    if cluster_id:
        params["cluster_id"] = cluster_id
    if claim_type:
        params["claim_type"] = claim_type
    if verified is not None:
        params["verified"] = verified
    if stale is not None:
        params["stale"] = stale
    async with _client() as c:
        r = await c.get("/api/claims", params=params)
        _raise_with_detail(r)
    claims = r.json()
    if not claims:
        return "No claims found matching filters."
    lines = [f"Found {len(claims)} claims:"]
    for cl in claims:
        v = "✓" if cl.get("verified") else "○"
        s = " [STALE]" if cl.get("stale") else ""
        lines.append(
            f"  {v} [{cl['id']}] ({cl['claim_type']}) "
            f"conf={cl.get('confidence', '?'):.2f}{s}"
        )
        lines.append(f"    {cl['content'][:500]}")
        lines.append(f"    source: {cl['source_entry_id']}")
    return "\n".join(lines)


@tool()
async def rka_extract_claims(
    entry_id: str,
    claims: list[dict],
) -> str:
    """Brain creates claims extracted from a journal entry.

    The Brain reads an entry, identifies atomic claims, and writes them back.
    Each claim gets a derived_from link to the source entry.

    Args:
        entry_id: Source journal entry ID (e.g. jnl_...)
        claims: List of claim objects, each with:
            - claim_type: hypothesis, evidence, method, result, observation, assumption
            - content: The atomic claim text
            - confidence: 0.0-1.0 (default 0.5)
            - cluster_id: Optional cluster ID to assign this claim to (e.g. ecl_...)
    """
    created = []
    assigned = 0
    async with _client() as c:
        for cl in claims:
            payload = {
                "source_entry_id": entry_id,
                "claim_type": cl["claim_type"],
                "content": cl["content"],
                "confidence": cl.get("confidence", 0.5),
            }
            r = await c.post("/api/claims", json=payload)
            _raise_with_detail(r)
            result = r.json()
            created.append(result)
            _record_entity("claim", result["id"], f"{cl['claim_type']}: {cl['content'][:60]}")

            # Inline cluster assignment if cluster_id provided
            cluster_id = cl.get("cluster_id")
            if cluster_id:
                edge_payload = {
                    "source_claim_id": result["id"],
                    "cluster_id": cluster_id,
                    "relation": "member_of",
                }
                r2 = await c.post("/api/claims/edges", json=edge_payload)
                _raise_with_detail(r2)
                assigned += 1

    lines = [f"Created {len(created)} claims from {entry_id}:"]
    if assigned:
        lines[0] += f" ({assigned} assigned to clusters)"
    for cl in created:
        lines.append(f"  [{cl['id']}] ({cl['claim_type']}) conf={cl.get('confidence', 0.5):.2f}")
        lines.append(f"    {cl['content'][:200]}")
    return "\n".join(lines)


@tool()
async def rka_create_cluster(
    label: str,
    research_question_id: str | None = None,
    synthesis: str | None = None,
    confidence: str = "emerging",
    claim_ids: list[str] | None = None,
) -> str:
    """Brain creates an evidence cluster and optionally assigns claims to it.

    Args:
        label: Short label for the cluster theme
        research_question_id: Decision ID (kind=research_question) this cluster addresses
        synthesis: Brain's synthesis paragraph (can be added later via rka_review_cluster)
        confidence: strong, moderate, emerging, contested, refuted
        claim_ids: Optional list of claim IDs to assign as members
    """
    payload = {
        "label": label,
        "confidence": confidence,
    }
    if research_question_id:
        payload["research_question_id"] = research_question_id
    if synthesis:
        payload["synthesis"] = synthesis

    async with _client() as c:
        r = await c.post("/api/clusters", json=payload)
        _raise_with_detail(r)
        cluster = r.json()
        cluster_id = cluster["id"]
        _record_entity("cluster", cluster_id, f"Cluster: {label[:60]}")

        assigned = 0
        if claim_ids:
            for cid in claim_ids:
                edge_payload = {
                    "source_claim_id": cid,
                    "cluster_id": cluster_id,
                    "relation": "member_of",
                    "confidence": 0.5,
                }
                er = await c.post("/api/claims/edges", json=edge_payload)
                if er.is_success:
                    assigned += 1

            # Update cluster claim count
            r2 = await c.put(f"/api/clusters/{cluster_id}", json={
                "needs_reprocessing": False,
                "synthesized_by": "brain",
            })

    parts = [f"Created cluster {cluster_id} ({label}), confidence={confidence}"]
    if assigned:
        parts.append(f"{assigned} claims assigned")
    if research_question_id:
        parts.append(f"linked to RQ {research_question_id}")
    return ", ".join(parts)


@tool()
async def rka_assign_claims_to_cluster(
    cluster_id: str,
    claim_ids: list[str],
) -> str:
    """Brain assigns existing claims to an existing evidence cluster.

    Creates member_of edges between claims and the cluster.

    Args:
        cluster_id: Target evidence cluster ID
        claim_ids: List of claim IDs to assign
    """
    results = []
    async with _client() as c:
        for cid in claim_ids:
            edge_payload = {
                "source_claim_id": cid,
                "cluster_id": cluster_id,
                "relation": "member_of",
                "confidence": 0.5,
            }
            r = await c.post("/api/claims/edges", json=edge_payload)
            if r.is_success:
                results.append(f"  {cid}: assigned")
            else:
                results.append(f"  {cid}: failed ({r.status_code})")

    return f"Assigned {len([r for r in results if 'assigned' in r])}/{len(claim_ids)} claims to cluster {cluster_id}:\n" + "\n".join(results)


@tool()
async def rka_supersede_decision(
    old_decision_id: str,
    question: str,
    chosen: str,
    rationale: str,
    decided_by: str = "brain",
    phase: str = "",
    kind: str = "decision",
) -> str:
    """Atomically supersede a decision and trigger re-distillation of affected knowledge.

    Marks the old decision as superseded, creates a new replacement decision,
    finds all journal entries linked to the old decision, marks their claims as stale,
    and enqueues re-distillation jobs.

    Args:
        old_decision_id: ID of the decision to supersede
        question: New decision question
        chosen: New chosen option
        rationale: Why the old decision is being overturned
        decided_by: Actor making the decision (brain, executor, pi)
        phase: Research phase
        kind: Decision kind (decision, research_question, design_choice, operational)
    """
    payload = {
        "old_decision_id": old_decision_id,
        "new_decision": {
            "question": question,
            "chosen": chosen,
            "rationale": rationale,
            "decided_by": decided_by,
            "phase": phase,
            "kind": kind,
        },
    }
    # Call the supersede endpoint via the decisions API
    async with _client() as c:
        r = await c.post(f"/api/decisions/{old_decision_id}/supersede", json=payload)
        _raise_with_detail(r)
    result = r.json()
    _record_entity("decision", result.get("id", "?"), f"Supersedes {old_decision_id}: {question[:60]}")
    return json.dumps(result, indent=2, default=str)


@tool()
async def rka_trace_provenance(
    entity_id: str,
    direction: str = "both",
    max_depth: int = 4,
) -> str:
    """Trace the full reasoning chain behind any entity.

    Follows typed entity links (informed_by, justified_by, motivated, produced,
    derived_from, cites, references, supersedes) to show why something exists.

    Args:
        entity_id: The entity ID to trace from (any type: jrn_, dec_, clm_, etc.)
        direction: upstream (what led to this), downstream (what this led to), or both
        max_depth: Maximum hops to traverse (default 4)
    """
    async with _client() as c:
        r = await c.get("/api/graph/ego", params={
            "entity_id": entity_id, "depth": max_depth,
        })
        _raise_with_detail(r)
    data = r.json()
    nodes = {n["id"]: n for n in data.get("nodes", [])}
    edges = data.get("edges", [])

    lines = [f"Provenance for {entity_id}:"]

    if direction in ("upstream", "both"):
        lines.append("\n  Upstream (what led to this):")
        for e in edges:
            if e.get("target") == entity_id or (direction == "both" and entity_id in (e.get("source", ""), e.get("target", ""))):
                src = nodes.get(e.get("source", ""), {})
                lines.append(f"    ← {e.get('link_type', '?')} {e.get('source', '?')} [{src.get('type', '?')}] {src.get('label', '')[:80]}")

    if direction in ("downstream", "both"):
        lines.append("\n  Downstream (what this led to):")
        for e in edges:
            if e.get("source") == entity_id:
                tgt = nodes.get(e.get("target", ""), {})
                lines.append(f"    → {e.get('link_type', '?')} {e.get('target', '?')} [{tgt.get('type', '?')}] {tgt.get('label', '')[:80]}")

    if len(lines) <= 3:
        lines.append("  (no links found)")
    return "\n".join(lines)


@tool()
async def rka_get_review_queue(
    status: str = "pending",
    limit: int = 20,
) -> str:
    """Get items in the Brain review queue.

    The review queue contains items that need Brain-level attention:
    low-confidence clusters, potential contradictions, complex syntheses,
    re-distillation reviews, cross-topic links, and stale themes.

    Args:
        status: Filter by status (pending, acknowledged, resolved, dismissed)
        limit: Max results
    """
    async with _client() as c:
        r = await c.get("/api/review-queue", params={"status": status, "limit": limit})
        _raise_with_detail(r)
    items = r.json()
    if not items:
        return f"No {status} review items."
    lines = [f"Review queue ({len(items)} {status} items):"]
    for item in items:
        lines.append(f"  [{item['id']}] {item['flag']} — {item['item_type']}:{item['item_id']}")
        if item.get("context"):
            ctx = item["context"] if isinstance(item["context"], str) else json.dumps(item["context"])
            lines.append(f"    Context: {ctx[:500]}")
        lines.append(f"    Priority: {item.get('priority', '?')} | Raised by: {item.get('raised_by', '?')}")
    return "\n".join(lines)


@tool()
async def rka_review_cluster(
    cluster_id: str,
    confidence: str,
    synthesis: str,
    gaps: list[str] | None = None,
    contradictions: list[str] | None = None,
    resolve_queue_items: list[str] | None = None,
    research_question_id: str | None = None,
) -> str:
    """Brain reviews and enriches an evidence cluster.

    The Brain evaluates a cluster's evidence and writes back a definitive
    synthesis with proper confidence assessment. This replaces the local LLM's synthesis.

    Args:
        cluster_id: Evidence cluster to review
        confidence: Brain's assessed confidence (strong, moderate, emerging, contested, refuted)
        synthesis: Brain's written synthesis paragraph
        gaps: Brain-identified evidence gaps
        contradictions: Brain-confirmed contradictions
        resolve_queue_items: Review queue item IDs to mark as resolved
        research_question_id: Decision ID (kind=research_question) to assign this cluster to
    """
    # Update cluster
    payload = {
        "synthesis": synthesis,
        "confidence": confidence,
        "synthesized_by": "brain",
        "needs_reprocessing": False,
        "research_question_id": research_question_id,
    }
    body = {k: v for k, v in payload.items() if v is not None}
    async with _client() as c:
        r = await c.put(f"/api/clusters/{cluster_id}", json=body)
        _raise_with_detail(r)

        # Resolve review queue items
        if resolve_queue_items:
            for item_id in resolve_queue_items:
                await c.put(f"/api/review-queue/{item_id}", json={
                    "status": "resolved",
                    "resolved_by": "brain",
                    "resolution": f"Cluster {cluster_id} reviewed: {confidence}",
                })

    parts = [f"Cluster {cluster_id} updated: confidence={confidence}, synthesized_by=brain"]
    if research_question_id:
        parts.append(f"assigned to RQ {research_question_id}")
    return ", ".join(parts)


@tool()
async def rka_review_claims(
    claim_ids: list[str],
    action: str = "approve",
    confidence_override: float | None = None,
) -> str:
    """Brain reviews extracted claims — approve, adjust confidence, or reject.

    Args:
        claim_ids: List of claim IDs to review
        action: approve (mark verified), reject (mark stale), adjust (set confidence)
        confidence_override: New confidence value (0.0-1.0), used with action=adjust
    """
    results = []
    async with _client() as c:
        for cid in claim_ids:
            if action == "approve":
                payload = {"verified": True}
            elif action == "reject":
                payload = {"stale": True, "verified": False}
            elif action == "adjust" and confidence_override is not None:
                payload = {"confidence": confidence_override}
            else:
                results.append(f"{cid}: invalid action")
                continue
            r = await c.put(f"/api/claims/{cid}", json=payload)
            if r.is_success:
                results.append(f"{cid}: {action}d")
            else:
                results.append(f"{cid}: failed ({r.status_code})")
    return "\n".join(results)


@tool()
async def rka_resolve_contradiction(
    cluster_id: str,
    resolution: str,
    claim_actions: dict[str, str] | None = None,
) -> str:
    """Brain resolves a flagged contradiction within an evidence cluster.

    Args:
        cluster_id: The cluster containing the contradiction
        resolution: Brain's explanation of how the contradiction is resolved
        claim_actions: Dict of claim_id → action (keep, reject, reframe). Optional.
    """
    lines = [f"Resolving contradiction in cluster {cluster_id}"]
    async with _client() as c:
        if claim_actions:
            for cid, action in claim_actions.items():
                if action == "reject":
                    await c.put(f"/api/claims/{cid}", json={"stale": True})
                    lines.append(f"  {cid}: marked stale")
                elif action == "keep":
                    lines.append(f"  {cid}: kept")
                elif action == "reframe":
                    lines.append(f"  {cid}: flagged for re-extraction")

        # Resolve matching review queue items
        r = await c.get("/api/review-queue", params={"status": "pending"})
        if r.is_success:
            for item in r.json():
                if item.get("item_id") == cluster_id and item.get("flag") == "potential_contradiction":
                    await c.put(f"/api/review-queue/{item['id']}", json={
                        "status": "resolved",
                        "resolved_by": "brain",
                        "resolution": resolution,
                    })
                    lines.append(f"  Resolved review item {item['id']}")

    lines.append(f"  Resolution: {resolution}")
    return "\n".join(lines)


# ============================================================
# Researcher experience tools
# ============================================================


@tool()
async def rka_get_changelog(
    since: str,
    limit: int = 50,
) -> str:
    """Show what changed since a given date across all entity types.

    Returns created and modified entities (journal, decisions, literature,
    claims, clusters, missions) grouped by action, with a statistics block.

    Args:
        since: ISO date/datetime (e.g. "2026-04-10" or "2026-04-10T14:00:00Z")
        limit: Max results per category (default 50)
    """
    async with _client() as c:
        r = await c.get("/api/changelog", params={"since": since, "limit": limit})
        _raise_with_detail(r)
        data = r.json()

    stats = data.get("statistics", {})
    created = data.get("created", [])
    modified = data.get("modified", [])

    lines = [f"## Changelog since {since}"]
    lines.append(f"Created: {stats.get('total_created', 0)} | Modified: {stats.get('total_modified', 0)}")
    by_type = stats.get("by_type", {})
    if by_type:
        lines.append("By type: " + ", ".join(f"{k}: {v}" for k, v in by_type.items()))
    lines.append("")

    if created:
        lines.append("### Created")
        for e in created:
            lines.append(f"  [{e['entity_type']}] {e['id']}: {e.get('label', '')}")
        lines.append("")

    if modified:
        lines.append("### Modified")
        for e in modified:
            lines.append(f"  [{e['entity_type']}] {e['id']}: {e.get('label', '')}")

    if not created and not modified:
        lines.append("No changes since " + since)

    return "\n".join(lines)


@tool()
async def rka_assemble_evidence(
    research_question_id: str,
    format: str = "progress_report",
) -> str:
    """Assemble evidence under a research question into a structured markdown draft.

    Pulls cluster syntheses, key claims, decision rationale, and cited literature
    into a document the Brain can edit and refine. No LLM needed — structured
    concatenation of existing data.

    Args:
        research_question_id: The RQ decision ID (dec_...)
        format: lit_review | progress_report | proposal_section
    """
    async with _client() as c:
        r = await c.get("/api/assemble-evidence", params={
            "research_question_id": research_question_id,
            "format": format,
        })
        _raise_with_detail(r)
        data = r.json()

    return data["content"]


@tool()
async def rka_split_cluster(
    source_id: str,
    new_clusters: list[dict],
) -> str:
    """Split a cluster into multiple new clusters by reassigning its claims.

    Claims not mentioned in any new_cluster stay in the source.
    Claim-to-entry provenance links are preserved — only cluster membership changes.

    Args:
        source_id: Cluster to split (ecl_...)
        new_clusters: List of {label: str, claim_ids: [str], research_question_id?: str}
    """
    async with _client() as c:
        r = await c.post("/api/clusters/split", json={
            "source_id": source_id,
            "new_clusters": new_clusters,
        })
        _raise_with_detail(r)
        data = r.json()

    lines = [f"Split {source_id} → {len(data['new_clusters'])} new clusters:"]
    for nc in data["new_clusters"]:
        lines.append(f"  {nc['id']}: {nc['label']} ({nc['claim_count']} claims)")
        _record_entity("cluster", nc["id"], nc["label"])
    lines.append(f"Source retains {data['source_remaining_claims']} claims")
    return "\n".join(lines)


@tool()
async def rka_merge_clusters(
    source_ids: list[str],
    target_label: str,
    target_synthesis: str | None = None,
    research_question_id: str | None = None,
) -> str:
    """Merge multiple clusters into one new cluster.

    All claims from source clusters are reassigned to the new cluster.
    Source clusters are left empty. Claim-to-entry provenance links are preserved.

    Args:
        source_ids: Clusters to merge (list of ecl_...)
        target_label: Label for the new combined cluster
        target_synthesis: Brain's synthesis for the merged cluster
        research_question_id: RQ to assign the new cluster to
    """
    async with _client() as c:
        r = await c.post("/api/clusters/merge", json={
            "source_ids": source_ids,
            "target_label": target_label,
            "target_synthesis": target_synthesis,
            "research_question_id": research_question_id,
        })
        _raise_with_detail(r)
        data = r.json()

    _record_entity("cluster", data["target_id"], target_label)
    lines = [
        f"Merged {len(source_ids)} clusters into {data['target_id']}: {target_label}",
        f"  {data['total_claims_moved']} claims moved",
        f"  Sources left empty: {', '.join(source_ids)}",
    ]
    return "\n".join(lines)


@tool()
async def rka_process_paper(
    lit_id: str,
    annotations: list[dict],
    summary: str | None = None,
) -> str:
    """Process reading annotations from a paper into structured claims.

    Creates a journal entry with reading notes, then extracts claims from
    each annotation. Optionally assigns claims to clusters inline.
    Auto-advances literature status from to_read to reading.

    Args:
        lit_id: Literature entry ID (lit_...)
        annotations: List of reading annotations:
            - passage: Key text/finding from the paper
            - note: Your interpretation or commentary (optional)
            - claim_type: hypothesis | evidence | method | result | observation | assumption
            - confidence: 0.0-1.0 (default 0.5)
            - cluster_id: Optional cluster to assign to (ecl_...)
        summary: Overall paper summary (becomes the journal entry content)
    """
    async with _client() as c:
        r = await c.post("/api/literature/process-paper", json={
            "lit_id": lit_id,
            "annotations": annotations,
            "summary": summary,
        })
        _raise_with_detail(r)
        data = r.json()

    _record_entity("journal", data["journal_entry_id"], f"Reading notes for {lit_id}")
    for cl in data.get("claims", []):
        _record_entity("claim", cl["id"], f"{cl['claim_type']}: {cl['content']}")

    lines = [
        f"Processed {len(data['claims'])} annotations from {lit_id}:",
        f"  Journal entry: {data['journal_entry_id']}",
        f"  Claims created: {data['claims_created']}",
    ]
    if data["claims_assigned"] > 0:
        lines.append(f"  Claims assigned to clusters: {data['claims_assigned']}")
    lines.append(f"  Literature status: {data['literature_status']}")
    for cl in data.get("claims", []):
        cluster_str = f" → {cl['cluster_id']}" if cl.get("cluster_id") else ""
        lines.append(f"    [{cl['id']}] ({cl['claim_type']}) {cl['content']}{cluster_str}")
    return "\n".join(lines)


@tool()
async def rka_advance_rq(
    rq_id: str,
    status: str,
    conclusion: str | None = None,
    evidence_cluster_ids: list[str] | None = None,
) -> str:
    """Advance a research question's lifecycle status.

    Tracks RQ progress from open through answered/closed. Optionally stores
    a conclusion and links supporting evidence clusters.

    Args:
        rq_id: Research question decision ID (dec_... with kind=research_question)
        status: open | partially_answered | answered | reframed | closed
        conclusion: Brain's conclusion text (recommended when status=answered)
        evidence_cluster_ids: Clusters that provide the answer (creates justified_by links)
    """
    async with _client() as c:
        r = await c.post("/api/research-questions/advance", json={
            "rq_id": rq_id,
            "status": status,
            "conclusion": conclusion,
            "evidence_cluster_ids": evidence_cluster_ids,
        })
        _raise_with_detail(r)
        data = r.json()

    status_icons = {
        "open": "●", "partially_answered": "◐",
        "answered": "✓", "reframed": "↻", "closed": "○",
    }
    icon = status_icons.get(status, "?")
    lines = [
        f"{icon} RQ {rq_id}: {data.get('previous_status', '?')} → {status}",
        f"  Question: {data.get('question', '')}",
    ]
    if data.get("conclusion_entry_id"):
        lines.append(f"  Conclusion recorded: {data['conclusion_entry_id']}")
    if data.get("evidence_clusters_linked", 0) > 0:
        lines.append(f"  Evidence clusters linked: {data['evidence_clusters_linked']}")
    return "\n".join(lines)


# ============================================================
# Maintenance manifest
# ============================================================


@tool()
async def rka_get_pending_maintenance() -> str:
    """Detect knowledge base gaps that need attention. Pure SQL — no LLM needed.

    Returns a compact manifest of:
    (a) entries without tags
    (b) entries without claims extracted
    (c) clusters needing synthesis
    (d) flagged contradictions
    (e) entries missing cross-references (no related_decisions)
    (f) decisions without justified_by links
    (g) missions without motivated_by_decision
    (h) unassigned evidence clusters

    Each category includes entity IDs, counts, and suggested fix actions.
    Use at session start to identify maintenance work before proceeding.
    """
    async with _client() as c:
        r = await c.get("/api/maintenance")
        _raise_with_detail(r)
        data = r.json()

    total = data["total_items"]
    est = data["estimated_tool_calls"]

    if total == 0:
        return "Knowledge base is clean — no pending maintenance items."

    lines = [f"## Pending Maintenance: {total} items (~{est} tool calls to fix)\n"]
    for key, cat in data["categories"].items():
        count = cat["count"]
        if count == 0:
            continue
        lines.append(f"### {cat['description']} ({count})")
        ids = cat["ids"]
        # Show up to 10 IDs inline, rest as count
        shown = ids[:10]
        lines.append(f"  IDs: {', '.join(shown)}")
        if len(ids) > 10:
            lines.append(f"  ... and {len(ids) - 10} more")
        lines.append(f"  Fix: {cat['fix_action']}")
        lines.append("")

    return "\n".join(lines)


# ============================================================
# MCP Prompts — orientation guides for Brain and Executor
# ============================================================

@mcp.prompt()
def brain_orientation() -> str:
    """Orientation guide for the Brain (Claude Desktop) — strategic AI role in RKA workflow."""
    return """\
# Brain Orientation — Research Knowledge Agent (RKA)

You are the **Brain**: the strategic AI layer in an RKA-powered research project.
Your counterpart is the **Executor** (Claude Code), which handles implementation.
The **PI** (human researcher) supervises both of you.

---

## Your Role

- Think strategically: interpret findings, decide research direction, manage literature
- Do NOT implement code, run experiments, or edit files directly — delegate to Executor
- Record all significant decisions in RKA so the knowledge base is always current
- Keep the PI informed; escalate blockers as checkpoints

---

## Session Start Protocol

Always begin a session by loading context:

1. If working with multiple projects, use `rka_list_projects()` to see available projects and `rka_set_project(id)` to select the right one. Skip if only one project exists or if the correct project is already active.
2. `rka_get_context()` — full project state (phase, open missions, recent notes, decisions)
3. `rka_get_status()` — current phase, focus, next steps
4. `rka_get_pending_maintenance()` — check for provenance gaps
5. `rka_get_checkpoints(status="open")` — check for unresolved Executor blockers

**Maintenance Protocol**: If maintenance items exist, silently process up to 10
before greeting the user. Priority: decisions_without_justified_by > missions_without_motivated_by
> unassigned_clusters > entries_missing_cross_refs. Do not mention maintenance work
to the user unless they ask.

If there are open checkpoints, resolve them before continuing new work.

---

## Core Workflow

### Directing the Executor
- `rka_create_mission(phase, objective, tasks, context, acceptance_criteria)` — assign work; returns the full mission ID to pass to the Executor
- `rka_get_mission(id)` — check progress
- `rka_resolve_checkpoint(id, resolution)` — unblock the Executor

### Recording Knowledge
- `rka_add_note(content, type="note", source="brain")` — observations, analyses, insights
- `rka_add_note(content, type="directive")` — instructions to the Executor
- `rka_add_decision(title, rationale, chosen_option, alternatives)` — record all non-trivial choices
- `rka_add_literature(...)` or `rka_enrich_doi(doi)` — add papers; use `rka_search_semantic_scholar` / `rka_search_arxiv` to find related work

### PI Input Attribution (Critical)
When recording PI input, ALWAYS set `source="pi"` and `verbatim_input` to the PI's exact words.
Your analysis goes in `content`. This preserves intellectual attribution.
Example: `rka_add_note(content="PI suggests focusing on...", source="pi", verbatim_input="Let's try the transformer approach instead")`

### Reviewing Progress
- `rka_get_journal(limit=20)` — recent notes from all actors
- `rka_get_decision_tree()` — all decisions and their rationale
- `rka_get_literature(status="to_read")` — papers waiting for review
- `rka_get_report(mission_id)` — read Executor's completion report

### Updating Status
- `rka_update_status(phase, current_focus, next_steps, blockers)` — keep the dashboard current
- `rka_summarize(scope="project")` — generate a full project summary

### Session Management
- Use `limit` parameters to control output size when needed
- `rka_session_digest()` gives you a compressed summary of the session so far
- `rka_reset_session()` clears the session tracker when you want to start fresh

---

## Provenance Enforcement (Critical)

You are responsible for maintaining provenance discipline. ALWAYS:
- `rka_add_decision(..., related_journal=["jrn_01...", "jrn_02..."])` — what findings justify this
- `rka_create_mission(..., motivated_by_decision="dec_01...")` — what decision triggers this work
- `rka_add_note(..., related_decisions=["dec_01..."], related_mission="msn_01...")` — link context
- `rka_trace_provenance(entity_id, direction="upstream")` — understand why something exists

Orphaned entities (no links) degrade the knowledge graph. Fix them during maintenance.

## v2.0 Research Map Workflow

- `rka_get_research_map()` — see the three-level view (RQs → clusters → claims)
- When creating decisions, set `kind="research_question"` for questions that organize research
- Assign orphaned evidence clusters to research questions via `rka_review_cluster(..., research_question_id=dec_id)`

## Review Queue (Brain-Only)

At session start, after loading context:
5. `rka_get_review_queue()` — items flagged for your attention

Process high-priority items before starting new work:
- `rka_review_cluster(cluster_id, confidence, synthesis)` — write definitive synthesis
- `rka_review_claims(claim_ids, action)` — approve, reject, or adjust claims
- `rka_resolve_contradiction(cluster_id, resolution)` — resolve flagged conflicts

Your syntheses are marked `synthesized_by: brain` — they are the authoritative interpretation.

## Decision Lifecycle

- To overturn a past decision: `rka_supersede_decision(old_id, question, chosen, rationale)`
- This automatically triggers re-distillation of affected knowledge
- Raw journal entries are never changed — only the interpretive layer rebuilds

---

## Session End Protocol

Before closing a conversation:
1. Add any insights or decisions from this session
2. `rka_submit_checkpoint(title, description, context)` if you need PI input before next session
3. `rka_update_status(...)` with updated next_steps

---

## Key Principles

- **One decision at a time**: record decisions as you make them, not in bulk at the end
- **Tag consistently**: use the project's established tags (check `rka_get_context` for existing tags)
- **Confidence levels**: use `hypothesis` → `tested` → `verified` as evidence accumulates
- **Importance**: mark only genuinely critical items as `critical`; keep `high` for important-but-not-urgent
"""


@mcp.prompt()
def executor_orientation() -> str:
    """Orientation guide for the Executor (Claude Code) — implementation AI role in RKA workflow."""
    return """\
# Executor Orientation — Research Knowledge Agent (RKA)

You are the **Executor**: the implementation AI in an RKA-powered research project.
Your counterpart is the **Brain** (Claude Desktop), which sets strategy.
The **PI** (human researcher) supervises both.

---

## Your Role

- Implement what the Brain assigns: write code, run experiments, process data, collect results
- Record methodology and findings in RKA as you work — don't batch up at the end
- Raise checkpoints immediately when you hit a decision that requires Brain/PI input
- Do NOT make strategic research decisions unilaterally

---

## Session Start Protocol

1. If working with multiple projects, use `rka_list_projects()` to see available projects and `rka_set_project(id)` to select the right one. Skip if only one project exists or if the correct project is already active.
2. `rka_get_context()` — load current project state
3. `rka_get_mission()` — finds the active or most recent pending mission automatically
4. If a pending mission is found, call `rka_update_mission_status(id, "active")` to claim it
5. Read the mission's `objective`, `tasks`, and **context** carefully before starting
6. If the mission has `motivated_by_decision`, read that decision with `rka_get(dec_id)` for full context

If no mission exists, ask the Brain or PI for direction before starting.

**Mission status lifecycle**: `pending` (Brain created, not started) → `active` (you are working on it) → `complete` (done via `rka_submit_report`). Always activate a pending mission before starting work.

### Session Management
- Use `limit` parameters to control output size when needed
- `rka_session_digest()` gives you a compressed summary of the session so far
- `rka_reset_session()` clears the session tracker when you want to start fresh

---

## Core Workflow

### During Implementation
- `rka_add_note(content, type="note", source="executor", related_mission=id)` — record results, observations, analyses
- `rka_add_note(content, type="log", source="executor", related_mission=id)` — document procedure steps
- `rka_ingest_document(path)` — import new files (PDFs, scripts, data files) into the knowledge base

### When Blocked
- `rka_submit_checkpoint(title, description, context, blocking=True)` — IMMEDIATELY when you need Brain/PI input
- Do not continue past a blocking decision; wait for `rka_resolve_checkpoint`

### On Completion
- `rka_submit_report(mission_id, summary, findings, anomalies, questions, codebase_state, recommended_next)` — required at mission end
- `summary`: full narrative report. `findings`/`anomalies`/`questions`: one item per line. `codebase_state`/`recommended_next`: plain strings.
- Include concrete findings, not just "task completed"

### Literature (when relevant)
- `rka_add_literature(title, ...)` or `rka_enrich_doi(doi)` — if you encounter a paper worth tracking
- `rka_search_semantic_scholar(query)` / `rka_search_arxiv(query)` — background literature search

---

## v2.0 Recording Standards

### Entry Types (simplified)

| Type | Use when | Example |
|------|---------|---------|
| `note` | You observed, analyzed, or discovered something | Results, insights, observations |
| `log` | You did a procedure step | "Ran stress test", "Deployed config" |
| `directive` | You received or are recording instructions | PI instructions, Brain directions |

Old types (finding, insight, methodology, etc.) are accepted but mapped to these three.

### Cross-References — ALWAYS Link Your Work

Every note and report MUST be linked to its context:
- `rka_add_note(..., related_mission="msn_01...")` — link to active mission (MANDATORY)
- `rka_add_note(..., related_decisions=["dec_01..."])` — link to relevant decisions (MANDATORY when applicable)
- `rka_submit_report(..., related_decisions=["dec_01..."])` — link findings to decisions they bear on

Orphaned entries (no related_mission, no related_decisions, no entity_links) are flagged
by `rka_get_pending_maintenance()` and create work for the Brain. Prevent this by linking as you go.

### Research Map Awareness

- `rka_get_research_map()` — see where your work fits in the big picture
- After completing a mission, check if your findings affect any research questions
- If they do, note which decisions your results justify or contradict

### Provenance

- `rka_trace_provenance(entity_id)` — trace the reasoning chain behind any entity
- Use this when you need to understand why a decision was made before implementing

---

## Key Principles

- **Record as you go**: a finding not recorded is a finding lost
- **Confidence is honest**: use `hypothesis` until you've verified; don't overstate
- **Checkpoints are not failures**: raising a checkpoint when genuinely blocked is correct behavior
- **Stay in scope**: if you discover something that changes the research direction, record it and checkpoint — don't pivot unilaterally
"""
