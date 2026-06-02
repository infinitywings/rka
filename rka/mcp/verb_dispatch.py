"""v2.7.0 PR-1 verb dispatcher helpers.

Thin adapters that route the 8 always-on v2.7.0 verbs to existing legacy
@tool(...) functions defined in rka/mcp/server.py. By design we never
duplicate REST-call code here — we look up the legacy function in
``_TOOL_REGISTRY`` (the registry the @tool decorator populates) and
invoke it with normalized kwargs.

This module is consumed by the verb bodies in rka/mcp/server.py and is
not itself a FastMCP-tooled module. All public helpers are sync wrappers
that call into legacy async tools — they MUST be awaited by the verb
bodies.

Design constraint: the legacy 91 tools stay UNCHANGED in PR-1. PR-2
demotes their tier and (optionally) deprecates them; until then both
surfaces coexist.

Bookkeeper invariant: this module lives under rka/, so it goes to
``main`` like the rest of rka/. Orchestrator never imports from here.

---

THE 8 VERBS:
  1. rka_query(scope, *, project_id, id?, query?, limit?, filters?, options?)
     — 29 read scopes
  2. rka_record_note(content, *, project_id, source, type, ...)
  3. rka_record_decision(question, chosen, rationale, *, project_id, ...)
  4. rka_record_literature(*, project_id, title?|bibtex?|search_query?|doi?,
     action?, ...) — 8 modes
  5. rka_mission(action, *, project_id, ...) — 6 actions
  6. rka_checkpoint(action, *, project_id, ...) — 8 actions
  7. rka_review(target, *, project_id, payload) — ~24 targets
  8. rka_session(action, ...) — UNSCOPED, ~9 actions

HYBRID design (from workflow w2cnkgz0k synthesis):
  - Design B (7 mid-grain verbs + 1 unscoped) as spine.
  - Graft A: provenance is a first-class top-level kwarg (not nested
    inside a body dict). The dispatcher unpacks
    `provenance={related_decisions: [...], related_literature: [...],
    related_mission: ..., supersedes: ..., related_journal: [...],
    motivated_by_decision: ...}` into the REST endpoint's flat fields.
  - Graft C: every verb description leads with role tag
    [BRAIN]/[EXECUTOR]/[PI]/[ANY] (lives on the verb @tool decorator
    docstrings; this module's dispatchers are role-neutral).

PHASE-X²' provenance enforcement (carried over from the orchestrator):
  - rka_record_note(source='pi', ...) requires verbatim_input.
  - rka_record_decision(...) requires related_journal as non-empty list.
  - rka_mission(action='create', ...) requires
    provenance['motivated_by_decision'].
"""

from __future__ import annotations

import json
from typing import Any


def _registry() -> dict:
    """Late-import the registry to avoid circular import at module load.

    rka/mcp/server.py imports from this module; this module needs the
    registry that server.py populates. Late binding sidesteps the cycle.
    """
    from rka.mcp.server import _TOOL_REGISTRY

    return _TOOL_REGISTRY


def _legacy(name: str):
    """Look up a legacy tool's wrapped callable from the registry."""
    reg = _registry()
    rec = reg.get(name)
    if rec is None:
        raise ValueError(
            f"v2.7.0 verb dispatch: legacy tool {name!r} not in registry "
            f"(known: {sorted(reg)[:5]}... total={len(reg)})"
        )
    return rec["fn"]


def _err(error_code: str, message: str, **extra: Any) -> str:
    """Render a structured verb-level error as JSON for the LLM caller."""
    body: dict[str, Any] = {"error": error_code, "message": message}
    body.update(extra)
    return json.dumps(body, indent=2)


# ---------------------------------------------------------------------------
# rka_record_literature dispatch — 5 modes
# ---------------------------------------------------------------------------


async def dispatch_record_literature(
    *,
    project_id: str,
    title: str | None,
    bibtex: str | None,
    search_query: str | None,
    search_source: str | None,
    doi: str | None,
    authors: list[str] | None,
    year: int | None,
    venue: str | None,
    status: str,
    abstract: str | None,
    url: str | None,
    tags: list[str] | None,
    related_decisions: list[str] | None,
    action: str | None,
    lit_id: str | None,
    manuscript_id: str | None,
    zotero_key: str | None,
    pdf_path: str | None,
    annotations: list[dict] | None,
    summary: str | None,
    add_to_library: bool,
    limit: int,
) -> str:
    """Route to one of the literature sub-modes by kwarg presence + action.

    Modes (priority):
      1. action='link_zotero' (id required)
      2. action='import_bibtex' OR bibtex provided (no action)
      3. action='enrich_doi' OR (doi only, no title/authors)
      4. action='search_semantic_scholar' OR search_source='semantic_scholar'
      5. action='search_arxiv' OR search_source='arxiv'
      6. action='process_paper' (lit_id + annotations)
      7. action='validate_reference' (manuscript_id + doi or title)
      8. Default: explicit-create via title
    """
    # Explicit action wins
    if action == "link_zotero":
        if not lit_id:
            return _err(
                "missing_field",
                "action='link_zotero' requires lit_id",
            )
        return await _legacy("rka_link_literature_to_zotero")(
            id=lit_id, project_id=project_id
        )

    if action == "import_bibtex" or (action is None and bibtex):
        if not bibtex:
            return _err(
                "missing_field",
                "action='import_bibtex' requires bibtex",
            )
        return await _legacy("rka_import_bibtex")(
            bibtex=bibtex,
            default_status=status,
            project_id=project_id,
        )

    if action == "enrich_doi":
        if not lit_id:
            return _err(
                "missing_field",
                "action='enrich_doi' requires lit_id",
            )
        return await _legacy("rka_enrich_doi")(
            lit_id=lit_id, project_id=project_id
        )

    if action == "search_semantic_scholar" or search_source == "semantic_scholar":
        q = search_query
        if not q:
            return _err(
                "missing_field",
                "semantic_scholar search requires search_query",
            )
        return await _legacy("rka_search_semantic_scholar")(
            query=q,
            limit=limit or 10,
            add_to_library=add_to_library,
            project_id=project_id,
        )

    if action == "search_arxiv" or search_source == "arxiv":
        q = search_query
        if not q:
            return _err(
                "missing_field",
                "arxiv search requires search_query",
            )
        return await _legacy("rka_search_arxiv")(
            query=q,
            limit=limit or 10,
            add_to_library=add_to_library,
            project_id=project_id,
        )

    if action == "process_paper":
        if not lit_id or annotations is None:
            return _err(
                "missing_field",
                "action='process_paper' requires lit_id + annotations",
            )
        return await _legacy("rka_process_paper")(
            lit_id=lit_id,
            annotations=annotations,
            summary=summary,
            project_id=project_id,
        )

    if action == "validate_reference":
        if not manuscript_id or (not doi and not title):
            return _err(
                "missing_field",
                "action='validate_reference' requires manuscript_id + (doi or title)",
            )
        return await _legacy("rka_validate_reference")(
            manuscript_id=manuscript_id,
            doi=doi,
            title=title,
            project_id=project_id,
        )

    # Default: title-based add. DOI-only (no title/authors) is also OK if
    # the user is bootstrapping a row to enrich later.
    if not title and not doi:
        return _err(
            "missing_field",
            "rka_record_literature: provide one of title, bibtex, doi, or "
            "search_query+search_source (or set action=...)",
        )

    return await _legacy("rka_add_literature")(
        title=title or f"(DOI: {doi})",
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        url=url,
        abstract=abstract,
        added_by="brain",
        project_id=project_id,
    )


# ---------------------------------------------------------------------------
# rka_mission dispatch — 6 actions
# ---------------------------------------------------------------------------


async def dispatch_mission(action: str, *, project_id: str, **kw: Any) -> str:
    """Discriminated dispatcher: action ∈ {create | update | update_status |
    submit_report | get_report | advance_rq}.

    Provenance: action='create' requires
    ``provenance.motivated_by_decision`` (Graft A surfaces it via a
    top-level provenance kwarg).
    """
    if action == "create":
        provenance = kw.get("provenance") or {}
        motivated_by = (
            kw.get("motivated_by_decision")
            or provenance.get("motivated_by_decision")
        )
        if not motivated_by:
            return _err(
                "missing_provenance",
                "rka_mission(action='create') requires "
                "provenance.motivated_by_decision (or top-level "
                "motivated_by_decision kwarg) — preserves the decision -> "
                "mission causality chain",
            )
        return await _legacy("rka_create_mission")(
            phase=kw.get("phase", "execution"),
            objective=kw["objective"],
            tasks=kw.get("tasks"),
            context=kw.get("context"),
            acceptance_criteria=kw.get("acceptance_criteria"),
            scope_boundaries=kw.get("scope_boundaries"),
            checkpoint_triggers=kw.get("checkpoint_triggers"),
            depends_on=kw.get("depends_on"),
            motivated_by_decision=motivated_by,
            tags=kw.get("tags"),
            project_id=project_id,
        )

    if action == "update":
        if not kw.get("mission_id"):
            return _err("missing_field", "action='update' requires mission_id")
        return await _legacy("rka_update_mission")(
            id=kw["mission_id"],
            phase=kw.get("phase"),
            objective=kw.get("objective"),
            context=kw.get("context"),
            acceptance_criteria=kw.get("acceptance_criteria"),
            scope_boundaries=kw.get("scope_boundaries"),
            checkpoint_triggers=kw.get("checkpoint_triggers"),
            depends_on=kw.get("depends_on"),
            parent_mission_id=kw.get("parent_mission_id"),
            motivated_by_decision=kw.get("motivated_by_decision"),
            tags=kw.get("tags"),
            project_id=project_id,
        )

    if action == "update_status":
        if not kw.get("mission_id") or not kw.get("status"):
            return _err(
                "missing_field",
                "action='update_status' requires mission_id + status",
            )
        return await _legacy("rka_update_mission_status")(
            id=kw["mission_id"],
            status=kw["status"],
            tasks=kw.get("tasks"),
            project_id=project_id,
        )

    if action == "submit_report":
        if not kw.get("mission_id"):
            return _err(
                "missing_field",
                "action='submit_report' requires mission_id",
            )
        return await _legacy("rka_submit_report")(
            mission_id=kw["mission_id"],
            summary=kw.get("summary"),
            findings=kw.get("findings", ""),
            anomalies=kw.get("anomalies", ""),
            questions=kw.get("questions", ""),
            codebase_state=kw.get("codebase_state", ""),
            recommended_next=kw.get("recommended_next", ""),
            content=kw.get("content"),
            project_id=project_id,
        )

    if action == "get_report":
        return await _legacy("rka_get_report")(
            mission_id=kw.get("mission_id"),
            project_id=project_id,
        )

    if action == "advance_rq":
        if not kw.get("rq_id") or not kw.get("status"):
            return _err(
                "missing_field",
                "action='advance_rq' requires rq_id + status",
            )
        return await _legacy("rka_advance_rq")(
            rq_id=kw["rq_id"],
            status=kw["status"],
            conclusion=kw.get("conclusion"),
            evidence_cluster_ids=kw.get("evidence_cluster_ids"),
            project_id=project_id,
        )

    return _err(
        "invalid_action",
        f"rka_mission: unknown action {action!r}; expected "
        "create|update|update_status|submit_report|get_report|advance_rq",
    )


# ---------------------------------------------------------------------------
# rka_checkpoint dispatch — 8 actions
# ---------------------------------------------------------------------------


async def dispatch_checkpoint(action: str, *, project_id: str, **kw: Any) -> str:
    """Discriminated dispatcher: action ∈ {submit | resolve | create_gate |
    evaluate_gate | present_decision | pi_select | record_outcome}.
    """
    if action == "submit":
        if not kw.get("mission_id") or not kw.get("type"):
            return _err(
                "missing_field",
                "action='submit' requires mission_id + type",
            )
        return await _legacy("rka_submit_checkpoint")(
            mission_id=kw["mission_id"],
            type=kw["type"],
            description=kw.get("description"),
            task_reference=kw.get("task_reference"),
            context=kw.get("context"),
            options=kw.get("options"),
            recommendation=kw.get("recommendation"),
            blocking=kw.get("blocking", True),
            content=kw.get("content"),
            project_id=project_id,
        )

    if action == "resolve":
        cid = kw.get("id") or kw.get("checkpoint_id")
        if not cid or not kw.get("resolution") or not kw.get("resolved_by"):
            return _err(
                "missing_field",
                "action='resolve' requires id + resolution + resolved_by",
            )
        return await _legacy("rka_resolve_checkpoint")(
            id=cid,
            resolution=kw["resolution"],
            resolved_by=kw["resolved_by"],
            rationale=kw.get("rationale"),
            create_decision=kw.get("create_decision", False),
            project_id=project_id,
        )

    if action == "create_gate":
        for f in ("mission_id", "gate_type", "deliverables", "pass_criteria"):
            if kw.get(f) in (None, ""):
                return _err(
                    "missing_field",
                    f"action='create_gate' requires {f}",
                )
        return await _legacy("rka_create_gate")(
            mission_id=kw["mission_id"],
            gate_type=kw["gate_type"],
            deliverables=kw["deliverables"],
            pass_criteria=kw["pass_criteria"],
            assumptions_to_verify=kw.get("assumptions_to_verify"),
            project_id=project_id,
        )

    if action == "evaluate_gate":
        if not kw.get("gate_id") or not kw.get("verdict") or not kw.get("notes"):
            return _err(
                "missing_field",
                "action='evaluate_gate' requires gate_id + verdict + notes",
            )
        return await _legacy("rka_evaluate_gate")(
            gate_id=kw["gate_id"],
            verdict=kw["verdict"],
            notes=kw["notes"],
            assumption_status=kw.get("assumption_status"),
            project_id=project_id,
        )

    if action == "present_decision":
        dec_id = kw.get("decision_id") or kw.get("id")
        if not dec_id:
            return _err(
                "missing_field",
                "action='present_decision' requires decision_id",
            )
        if not kw.get("confirmation_brief") or kw.get("options") is None:
            return _err(
                "missing_field",
                "action='present_decision' requires confirmation_brief + options",
            )
        return await _legacy("rka_present_decision")(
            decision_id=dec_id,
            confirmation_brief=kw["confirmation_brief"],
            options=kw["options"],
            pi_preference=kw.get("pi_preference"),
            project_id=project_id,
        )

    if action == "pi_select":
        dec_id = kw.get("decision_id") or kw.get("id")
        if not dec_id:
            return _err(
                "missing_field",
                "action='pi_select' requires decision_id",
            )
        return await _legacy("rka_record_pi_selection")(
            decision_id=dec_id,
            selected_option_id=kw.get("selected_option_id"),
            override_rationale=kw.get("override_rationale"),
            project_id=project_id,
        )

    if action == "record_outcome":
        dec_id = kw.get("decision_id") or kw.get("id")
        if not dec_id or not kw.get("outcome"):
            return _err(
                "missing_field",
                "action='record_outcome' requires decision_id + outcome",
            )
        return await _legacy("rka_record_outcome")(
            decision_id=dec_id,
            outcome=kw["outcome"],
            outcome_details=kw.get("outcome_details") or kw.get("lessons"),
            recorded_by=kw.get("recorded_by", "pi"),
            project_id=project_id,
        )

    return _err(
        "invalid_action",
        f"rka_checkpoint: unknown action {action!r}; expected submit|resolve|"
        "create_gate|evaluate_gate|present_decision|pi_select|record_outcome",
    )


# ---------------------------------------------------------------------------
# rka_review dispatch — ~25 targets
# ---------------------------------------------------------------------------


# Map target names to legacy tool name + payload key transform.
# Each entry: (legacy_tool_name, payload_unpacker)
# The unpacker takes (project_id, payload) and returns kwargs for the legacy.


async def dispatch_review(target: str, *, project_id: str, payload: dict[str, Any] | None) -> str:
    """Dispatcher for the rka_review verb. Routes a target string to the
    correct legacy tool, unpacking `payload` into legacy kwargs.

    Targets supported (see SEMANTIC MAPPING TABLE in spec):
      Note / decision / literature updates:
        note_update, decision_update, literature_update
      Bulk:
        bulk_update, batch_import
      Hooks (config):
        hook_add, hook_enable, hook_disable, hook_delete
      Notifications:
        brain_notifications_clear
      Claims / clusters:
        extract_claims, cluster, claims, cluster_create, cluster_assign,
        cluster_split, cluster_merge
      Contradictions / freshness / maintenance:
        contradiction, flag_stale, eviction_sweep
      Workspace:
        bootstrap_workspace
      Status / manuscript:
        status_update, manuscript_register
    """
    p = payload or {}

    if target == "note_update":
        if not p.get("id"):
            return _err("missing_field", "review note_update requires payload.id")
        return await _legacy("rka_update_note")(
            id=p["id"],
            content=p.get("content"),
            type=p.get("type"),
            confidence=p.get("confidence"),
            importance=p.get("importance"),
            verbatim_input=p.get("verbatim_input"),
            related_decisions=p.get("related_decisions"),
            related_literature=p.get("related_literature"),
            related_mission=p.get("related_mission"),
            tags=p.get("tags"),
            phase=p.get("phase"),
            source=p.get("source"),
            project_id=project_id,
        )

    if target == "decision_update":
        if not p.get("id"):
            return _err("missing_field", "review decision_update requires payload.id")
        return await _legacy("rka_update_decision")(
            id=p["id"],
            status=p.get("status"),
            chosen=p.get("chosen"),
            rationale=p.get("rationale"),
            abandonment_reason=p.get("abandonment_reason"),
            kind=p.get("kind"),
            related_journal=p.get("related_journal"),
            parent_id=p.get("parent_id"),
            related_literature=p.get("related_literature"),
            related_missions=p.get("related_missions"),
            phase=p.get("phase"),
            tags=p.get("tags"),
            assumptions=p.get("assumptions"),
            project_id=project_id,
        )

    if target == "literature_update":
        if not p.get("id"):
            return _err("missing_field", "review literature_update requires payload.id")
        return await _legacy("rka_update_literature")(
            id=p["id"],
            title=p.get("title"),
            authors=p.get("authors"),
            year=p.get("year"),
            venue=p.get("venue"),
            doi=p.get("doi"),
            url=p.get("url"),
            bibtex=p.get("bibtex"),
            pdf_path=p.get("pdf_path"),
            abstract=p.get("abstract"),
            status=p.get("status"),
            key_findings=p.get("key_findings"),
            methodology_notes=p.get("methodology_notes"),
            relevance=p.get("relevance"),
            relevance_score=p.get("relevance_score"),
            related_decisions=p.get("related_decisions"),
            notes=p.get("notes"),
            tags=p.get("tags"),
            project_id=project_id,
        )

    if target == "bulk_update":
        if not p.get("updates"):
            return _err("missing_field", "review bulk_update requires payload.updates")
        return await _legacy("rka_bulk_update")(
            updates=p["updates"], project_id=project_id
        )

    if target == "batch_import":
        if not p.get("entries"):
            return _err("missing_field", "review batch_import requires payload.entries")
        actor = p.get("actor", "system")
        if actor == "import":
            actor = "system"
        return await _legacy("rka_batch_import")(
            entries=p["entries"], actor=actor, project_id=project_id
        )

    if target == "hook_add":
        for f in ("event", "handler_type", "handler_config", "name"):
            if p.get(f) is None:
                return _err("missing_field", f"hook_add payload requires {f}")
        return await _legacy("rka_add_hook")(
            event=p["event"],
            handler_type=p["handler_type"],
            handler_config=p["handler_config"],
            name=p["name"],
            enabled=p.get("enabled", True),
            created_by=p.get("created_by", "pi"),
            project_id=project_id,
        )

    if target == "hook_enable":
        hid = p.get("hook_id") or p.get("id")
        if not hid:
            return _err("missing_field", "hook_enable requires payload.hook_id")
        return await _legacy("rka_enable_hook")(hook_id=hid, project_id=project_id)

    if target == "hook_disable":
        hid = p.get("hook_id") or p.get("id")
        if not hid:
            return _err("missing_field", "hook_disable requires payload.hook_id")
        return await _legacy("rka_disable_hook")(hook_id=hid, project_id=project_id)

    if target == "hook_delete":
        hid = p.get("hook_id") or p.get("id")
        if not hid:
            return _err("missing_field", "hook_delete requires payload.hook_id")
        return await _legacy("rka_delete_hook")(hook_id=hid, project_id=project_id)

    if target == "brain_notifications_clear":
        if not p.get("ids"):
            return _err(
                "missing_field",
                "brain_notifications_clear requires payload.ids",
            )
        return await _legacy("rka_clear_brain_notifications")(
            ids=p["ids"], project_id=project_id
        )

    if target == "extract_claims":
        if not p.get("entry_id") or not p.get("claims"):
            return _err(
                "missing_field",
                "extract_claims requires payload.entry_id + payload.claims",
            )
        return await _legacy("rka_extract_claims")(
            entry_id=p["entry_id"],
            claims=p["claims"],
            project_id=project_id,
        )

    if target == "cluster":
        if not p.get("cluster_id") or not p.get("confidence") or not p.get("synthesis"):
            return _err(
                "missing_field",
                "review target='cluster' requires cluster_id + confidence + synthesis",
            )
        return await _legacy("rka_review_cluster")(
            cluster_id=p["cluster_id"],
            confidence=p["confidence"],
            synthesis=p["synthesis"],
            gaps=p.get("gaps"),
            contradictions=p.get("contradictions"),
            resolve_queue_items=p.get("resolve_queue_items"),
            research_question_id=p.get("research_question_id"),
            project_id=project_id,
        )

    if target == "claims":
        if not p.get("claim_ids"):
            return _err(
                "missing_field",
                "review target='claims' requires payload.claim_ids",
            )
        return await _legacy("rka_review_claims")(
            claim_ids=p["claim_ids"],
            action=p.get("action", "approve"),
            confidence_override=p.get("confidence_override"),
            project_id=project_id,
        )

    if target == "cluster_create":
        if not p.get("label"):
            return _err(
                "missing_field",
                "cluster_create requires payload.label",
            )
        return await _legacy("rka_create_cluster")(
            label=p["label"],
            research_question_id=p.get("research_question_id"),
            synthesis=p.get("synthesis"),
            confidence=p.get("confidence", "emerging"),
            claim_ids=p.get("claim_ids"),
            project_id=project_id,
        )

    if target == "cluster_assign":
        if not p.get("cluster_id") or not p.get("claim_ids"):
            return _err(
                "missing_field",
                "cluster_assign requires cluster_id + claim_ids",
            )
        return await _legacy("rka_assign_claims_to_cluster")(
            cluster_id=p["cluster_id"],
            claim_ids=p["claim_ids"],
            project_id=project_id,
        )

    if target == "cluster_split":
        if not p.get("source_id") or not p.get("new_clusters"):
            return _err(
                "missing_field",
                "cluster_split requires source_id + new_clusters",
            )
        return await _legacy("rka_split_cluster")(
            source_id=p["source_id"],
            new_clusters=p["new_clusters"],
            project_id=project_id,
        )

    if target == "cluster_merge":
        if not p.get("source_ids") or not p.get("target_label"):
            return _err(
                "missing_field",
                "cluster_merge requires source_ids + target_label",
            )
        return await _legacy("rka_merge_clusters")(
            source_ids=p["source_ids"],
            target_label=p["target_label"],
            target_synthesis=p.get("target_synthesis"),
            research_question_id=p.get("research_question_id"),
            project_id=project_id,
        )

    if target == "contradiction":
        if not p.get("cluster_id") or not p.get("resolution"):
            return _err(
                "missing_field",
                "review target='contradiction' requires cluster_id + resolution",
            )
        return await _legacy("rka_resolve_contradiction")(
            cluster_id=p["cluster_id"],
            resolution=p["resolution"],
            claim_actions=p.get("claim_actions"),
            project_id=project_id,
        )

    if target == "flag_stale":
        if not p.get("entity_id") or not p.get("reason"):
            return _err(
                "missing_field",
                "flag_stale requires payload.entity_id + payload.reason",
            )
        return await _legacy("rka_flag_stale")(
            entity_id=p["entity_id"],
            reason=p["reason"],
            staleness=p.get("staleness", "yellow"),
            propagate=p.get("propagate", True),
            project_id=project_id,
        )

    if target == "eviction_sweep":
        return await _legacy("rka_eviction_sweep")(
            dry_run=p.get("dry_run", True), project_id=project_id
        )

    if target == "bootstrap_workspace":
        if not p.get("folder_path"):
            return _err(
                "missing_field",
                "bootstrap_workspace requires payload.folder_path",
            )
        return await _legacy("rka_bootstrap_workspace")(
            folder_path=p["folder_path"],
            phase=p.get("phase"),
            override_tags=p.get("override_tags"),
            skip_files=p.get("skip_files"),
            use_llm=p.get("use_llm", True),
            dry_run=p.get("dry_run", False),
            project_id=project_id,
        )

    if target == "status_update":
        return await _legacy("rka_update_status")(
            current_phase=p.get("current_phase") or p.get("phase"),
            summary=p.get("summary") or p.get("focus"),
            blockers=p.get("blockers"),
            metrics=p.get("metrics"),
            content=p.get("content"),
            project_id=project_id,
        )

    if target == "manuscript_register":
        if not p.get("venue") or not p.get("title"):
            return _err(
                "missing_field",
                "manuscript_register requires payload.venue + payload.title",
            )
        return await _legacy("rka_register_manuscript")(
            venue=p["venue"],
            title=p["title"],
            abstract=p.get("abstract"),
            sections=p.get("sections"),
            project_id=project_id,
        )

    if target == "supersede_decision":
        for f in ("old_decision_id", "question", "chosen", "rationale"):
            if not p.get(f):
                return _err(
                    "missing_field",
                    f"supersede_decision payload requires {f}",
                )
        return await _legacy("rka_supersede_decision")(
            old_decision_id=p["old_decision_id"],
            question=p["question"],
            chosen=p["chosen"],
            rationale=p["rationale"],
            decided_by=p.get("decided_by", "brain"),
            phase=p.get("phase", ""),
            kind=p.get("kind", "decision"),
            project_id=project_id,
        )

    return _err(
        "invalid_target",
        f"rka_review: unknown target {target!r}",
    )


# ---------------------------------------------------------------------------
# rka_query dispatch — 29 read scopes
# ---------------------------------------------------------------------------
#
# Each scope maps to a legacy @tool function. Kwargs flow through normalized
# parameter names (id / query / limit / filters / options) into the
# legacy-tool signature. The scope keys are the SINGLE source of truth for
# what's queryable; mismatches surface as `invalid_scope` errors.


_QUERY_DISPATCH: dict[str, str] = {
    # always-on minimal-session-start
    "status": "rka_get_status",
    "context": "rka_get_context",
    "pending_maintenance": "rka_get_pending_maintenance",
    "checkpoints": "rka_get_checkpoints",
    "research_map": "rka_get_research_map",
    "review_queue": "rka_get_review_queue",

    # search / get-by-id
    "search": "rka_search",
    "entity": "rka_get",

    # journal / decisions / literature / missions / reports lists
    "journal": "rka_get_journal",
    "literature": "rka_get_literature",
    "report": "rka_get_report",
    "mission": "rka_get_mission",

    # decisions / graph
    "decision_tree": "rka_get_decision_tree",
    "graph": "rka_get_graph",
    "ego_graph": "rka_get_ego_graph",
    "graph_stats": "rka_graph_stats",
    "graph_mermaid": "rka_export_mermaid",

    # claims / clusters
    "clusters": "rka_list_clusters",
    "claims": "rka_get_claims",

    # provenance / multi-hop
    "provenance": "rka_trace_provenance",
    "multi_hop": "rka_multi_hop_retrieval",
    "evidence": "rka_assemble_evidence",

    # session-flavored project-scoped reads
    "summarize": "rka_summarize",
    "generate_summary": "rka_generate_summary",
    "calibration_metrics": "rka_get_calibration_metrics",
    "changelog": "rka_get_changelog",

    # hooks reads
    "hooks": "rka_list_hooks",
    "hook_executions": "rka_get_hook_executions",
    "brain_notifications": "rka_get_brain_notifications",

    # maintenance / freshness reads
    "integrity": "rka_check_integrity",
    "freshness": "rka_check_freshness",
    "contradictions": "rka_detect_contradictions",

    # workspace
    "workspace_tree": "rka_scan_workspace_tree",
    "workspace_scan": "rka_scan_workspace",
    "bootstrap_review": "rka_review_bootstrap",

    # manuscript
    "manuscript": "rka_get_manuscript",
}


async def dispatch_query(
    scope: str,
    *,
    project_id: str,
    id: str | None = None,
    query: str | None = None,
    limit: int | None = None,
    filters: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> str:
    """[ANY] Universal read dispatcher.

    Routes a `scope` discriminator to the matching legacy @tool function,
    normalizing kwargs onto the legacy parameter names.

    Args:
        scope: One of `_QUERY_DISPATCH` keys.
        project_id: RKA project ID (prj_...).
        id: Entity ID when the scope is id-addressed (entity, mission,
            manuscript, ego_graph, provenance, bootstrap_review,
            contradictions).
        query: Query string for search-shaped scopes (search, multi_hop).
        limit: Result limit (folded into filters when applicable).
        filters: Per-scope filter dict.
        options: Per-scope option dict (e.g. {'depth': 'detailed'} for
            'context').
    """
    if scope not in _QUERY_DISPATCH:
        valid = ", ".join(sorted(_QUERY_DISPATCH))
        return _err(
            "invalid_scope",
            f"rka_query: unknown scope {scope!r}",
            valid_scopes=valid,
        )
    tool_name = _QUERY_DISPATCH[scope]
    legacy = _legacy(tool_name)
    f = filters or {}
    o = options or {}

    # --- Scopes with NO kwargs other than project_id ---
    if scope in (
        "status",
        "pending_maintenance",
        "research_map",
        "graph_stats",
        "calibration_metrics",
        "integrity",
    ):
        return await legacy(project_id=project_id)

    # --- search / multi_hop ---
    if scope == "search":
        if not query:
            return _err("missing_field", "rka_query(scope='search'): query is required")
        return await legacy(
            query=query,
            entity_types=f.get("entity_types"),
            limit=limit or f.get("limit", 20),
            project_id=project_id,
        )

    if scope == "multi_hop":
        if not query and not f.get("seeds"):
            return _err(
                "missing_field",
                "rka_query(scope='multi_hop'): query or filters.seeds required",
            )
        return await legacy(
            query=query or "",
            seeds=f.get("seeds"),
            max_depth=f.get("max_depth", 3),
            max_nodes=f.get("max_nodes", 50),
            edge_weights=f.get("edge_weights"),
            project_id=project_id,
        )

    # --- entity (id-prefix dispatcher) ---
    if scope == "entity":
        if not id:
            return _err("missing_field", "rka_query(scope='entity'): id is required")
        return await legacy(id=id, project_id=project_id)

    # --- mission (id optional) ---
    if scope == "mission":
        return await legacy(id=id, project_id=project_id)

    # --- report (mission_id optional) ---
    if scope == "report":
        return await legacy(mission_id=id, project_id=project_id)

    # --- list-style reads with named filters ---
    if scope == "journal":
        return await legacy(
            type=f.get("type"),
            phase=f.get("phase"),
            confidence=f.get("confidence"),
            status=f.get("status"),
            since=f.get("since"),
            limit=limit or f.get("limit", 20),
            project_id=project_id,
        )

    if scope == "literature":
        return await legacy(
            status=f.get("status"),
            query=query or f.get("query"),
            limit=limit or f.get("limit", 20),
            project_id=project_id,
        )

    if scope == "checkpoints":
        return await legacy(
            status=f.get("status", "open"), project_id=project_id,
        )

    if scope == "review_queue":
        return await legacy(
            status=f.get("status", "pending"),
            limit=limit or f.get("limit", 20),
            project_id=project_id,
        )

    if scope == "decision_tree":
        return await legacy(
            root_id=id or f.get("root_id"),
            phase=f.get("phase"),
            active_only=f.get("active_only", False),
            project_id=project_id,
        )

    if scope == "graph":
        return await legacy(
            include_types=f.get("include_types"),
            phase=f.get("phase"),
            limit=limit or f.get("limit", 500),
            project_id=project_id,
        )

    if scope == "ego_graph":
        if not id:
            return _err("missing_field", "rka_query(scope='ego_graph'): id is required")
        return await legacy(
            entity_id=id, depth=f.get("depth", 1), project_id=project_id,
        )

    if scope == "graph_mermaid":
        return await legacy(
            phase=f.get("phase"),
            active_only=f.get("active_only", False),
            project_id=project_id,
        )

    if scope == "clusters":
        return await legacy(
            research_question_id=f.get("research_question_id"),
            confidence=f.get("confidence"),
            limit=limit or f.get("limit", 50),
            project_id=project_id,
        )

    if scope == "claims":
        return await legacy(
            source_entry_id=f.get("source_entry_id"),
            cluster_id=f.get("cluster_id"),
            claim_type=f.get("claim_type") or f.get("type"),
            verified=f.get("verified"),
            stale=f.get("stale"),
            limit=limit or f.get("limit", 20),
            project_id=project_id,
        )

    if scope == "provenance":
        if not id:
            return _err("missing_field", "rka_query(scope='provenance'): id required")
        return await legacy(
            entity_id=id,
            direction=f.get("direction", "both"),
            max_depth=f.get("max_depth", f.get("depth", 4)),
            project_id=project_id,
        )

    if scope == "evidence":
        rq_id = id or f.get("research_question_id")
        if not rq_id:
            return _err(
                "missing_field",
                "rka_query(scope='evidence'): id (research_question_id) required",
            )
        return await legacy(
            research_question_id=rq_id,
            format=f.get("format", "progress_report"),
            project_id=project_id,
        )

    if scope == "context":
        return await legacy(
            topic=query or f.get("topic"),
            phase=f.get("phase"),
            depth=o.get("depth", "summary"),
            project_id=project_id,
        )

    if scope == "summarize":
        return await legacy(
            topic=query or f.get("topic"),
            phase=f.get("phase"),
            entity_ids=f.get("entity_ids"),
            project_id=project_id,
        )

    if scope == "generate_summary":
        return await legacy(
            scope_type=f.get("scope_type", "project"),
            scope_id=id or f.get("scope_id"),
            granularity=f.get("granularity", "paragraph"),
            project_id=project_id,
        )

    if scope == "changelog":
        since = f.get("since")
        if not since:
            return _err(
                "missing_field",
                "rka_query(scope='changelog'): filters.since required",
            )
        return await legacy(
            since=since,
            limit=limit or f.get("limit", 50),
            project_id=project_id,
        )

    if scope == "hooks":
        return await legacy(
            event=f.get("event"),
            enabled_only=f.get("enabled_only", False),
            project_id=project_id,
        )

    if scope == "hook_executions":
        return await legacy(
            hook_id=f.get("hook_id"),
            since=f.get("since"),
            status=f.get("status"),
            limit=limit or f.get("limit", 100),
            project_id=project_id,
        )

    if scope == "brain_notifications":
        return await legacy(
            since=f.get("since"),
            include_cleared=f.get("include_cleared", False),
            limit=limit or f.get("limit", 100),
            project_id=project_id,
        )

    if scope == "freshness":
        return await legacy(
            days_threshold=f.get("days_threshold", 30),
            project_id=project_id,
        )

    if scope == "contradictions":
        if not id:
            return _err(
                "missing_field",
                "rka_query(scope='contradictions'): id (entity_id) required",
            )
        return await legacy(
            entity_id=id,
            similarity_threshold=f.get("similarity_threshold", 0.7),
            max_results=f.get("max_results", 5),
            project_id=project_id,
        )

    if scope == "workspace_tree":
        fp = f.get("folder_path")
        if not fp:
            return _err(
                "missing_field",
                "rka_query(scope='workspace_tree'): filters.folder_path required",
            )
        return await legacy(
            folder_path=fp,
            max_depth=f.get("max_depth", 2),
            project_id=project_id,
        )

    if scope == "workspace_scan":
        fp = f.get("folder_path")
        if not fp:
            return _err(
                "missing_field",
                "rka_query(scope='workspace_scan'): filters.folder_path required",
            )
        return await legacy(
            folder_path=fp,
            ignore_patterns=f.get("ignore_patterns"),
            max_file_size_mb=f.get("max_file_size_mb", 50.0),
            use_llm=f.get("use_llm", True),
            project_id=project_id,
        )

    if scope == "bootstrap_review":
        if not id:
            return _err(
                "missing_field",
                "rka_query(scope='bootstrap_review'): id (scan_id) required",
            )
        return await legacy(scan_id=id, project_id=project_id)

    if scope == "manuscript":
        if not id:
            return _err(
                "missing_field",
                "rka_query(scope='manuscript'): id required",
            )
        return await legacy(manuscript_id=id, project_id=project_id)

    return _err(
        "invalid_scope",
        f"rka_query: scope {scope!r} not yet wired",
    )


# ---------------------------------------------------------------------------
# rka_record_note dispatch — 2 modes (create + ingest_document)
# ---------------------------------------------------------------------------

# Provenance keys consumed by the create / ingest_document modes.
_NOTE_PROVENANCE_KEYS = (
    "related_decisions",
    "related_literature",
    "related_mission",
    "supersedes",
)


def _unpack_provenance(
    provenance: dict[str, Any] | None,
    explicit: dict[str, Any],
    allowed: tuple[str, ...],
) -> dict[str, Any]:
    """Graft A — promote provenance dict entries to top-level kwargs.

    Explicit kwargs always win (caller-supplied wins over provenance).
    """
    if not provenance:
        return explicit
    out = dict(explicit)
    for key in allowed:
        if out.get(key) is None and key in provenance:
            out[key] = provenance[key]
    return out


async def dispatch_record_note(
    content: str,
    *,
    project_id: str,
    source: str = "executor",
    type: str = "note",
    confidence: str = "hypothesis",
    importance: str = "normal",
    verbatim_input: str | None = None,
    phase: str | None = None,
    tags: list[str] | None = None,
    provenance: dict[str, Any] | None = None,
    action: str = "create",
    # ingest_document mode kwargs:
    default_type: str | None = None,
    split_by_headings: bool | None = None,
) -> str:
    """[ANY] Record a journal entry (create or ingest_document).

    Modes (selected by `action`):
      - 'create' (default): POST /api/notes — single note.
      - 'ingest_document': POST /api/ingest/document — markdown
        splitter; many entries from one call.

    Phase-X²' enforcement: source='pi' requires verbatim_input. The
    REST layer accepts the call without it, but the v2.7.0 verb tier
    rejects pre-flight so PI provenance isn't silently lost.

    Provenance: Graft A — pass `provenance={related_decisions:[...],
    related_literature:[...], related_mission:..., supersedes:...}`
    OR the same fields as explicit kwargs.
    """
    # Phase-X²' validation: source='pi' must carry verbatim_input.
    if source == "pi" and not verbatim_input:
        return _err(
            "missing_provenance",
            "rka_record_note(source='pi'): verbatim_input is required "
            "(preserves PI's exact wording for intellectual attribution)",
        )

    explicit = {
        "related_decisions": None,
        "related_literature": None,
        "related_mission": None,
        "supersedes": None,
    }
    merged = _unpack_provenance(provenance, explicit, _NOTE_PROVENANCE_KEYS)

    if action == "ingest_document":
        return await _legacy("rka_ingest_document")(
            content=content,
            source=source if source in (
                "brain", "executor", "pi", "llm", "web_ui", "system",
            ) else "brain",
            default_type=default_type or "finding",
            phase=phase,
            tags=tags,
            related_literature=merged["related_literature"],
            related_decisions=merged["related_decisions"],
            related_mission=merged["related_mission"],
            split_by_headings=(
                True if split_by_headings is None else split_by_headings
            ),
            project_id=project_id,
        )

    if action != "create":
        return _err(
            "invalid_action",
            f"rka_record_note: unknown action {action!r}; valid: create, ingest_document",
        )

    return await _legacy("rka_add_note")(
        content=content,
        type=type,
        source=source,
        phase=phase,
        verbatim_input=verbatim_input,
        related_decisions=merged["related_decisions"],
        related_literature=merged["related_literature"],
        related_mission=merged["related_mission"],
        supersedes=merged["supersedes"],
        confidence=confidence,
        importance=importance,
        tags=tags,
        project_id=project_id,
    )


# ---------------------------------------------------------------------------
# rka_record_decision dispatch — 2 modes (create + supersede)
# ---------------------------------------------------------------------------

_DECISION_PROVENANCE_KEYS = (
    "related_journal",
    "related_literature",
    "parent_id",
)


async def dispatch_record_decision(
    question: str,
    chosen: str,
    rationale: str,
    *,
    project_id: str,
    decided_by: str,
    kind: str = "decision",
    phase: str = "",
    related_journal: list[str] | None = None,
    supersedes_decision_id: str | None = None,
    options: list[dict] | None = None,
    related_literature: list[str] | None = None,
    parent_id: str | None = None,
    assumptions: list[str] | None = None,
    importance: str | None = None,
    justified_by: list[str] | None = None,
    provenance: dict[str, Any] | None = None,
) -> str:
    """[BRAIN/PI] Record a decision (create or supersede).

    Modes:
      - create (default): POST /api/decisions.
      - supersede: POST /api/decisions/{old}/supersede (set by
        `supersedes_decision_id`); atomically marks the old decision
        superseded, creates the replacement, re-distills affected
        knowledge.

    Provenance discipline: related_journal must be a NON-EMPTY list.
    Pass it directly OR through provenance={'related_journal': [...]}.
    """
    rj = related_journal
    if (rj is None or len(rj) == 0) and provenance:
        rj = provenance.get("related_journal")
    if not rj or len(rj) == 0:
        return _err(
            "missing_provenance",
            "rka_record_decision: related_journal must be a non-empty "
            "list — decisions need justifying journal entries (provenance "
            "discipline preserved from Phase-X²)",
        )

    explicit = {
        "related_journal": rj,
        "related_literature": related_literature,
        "parent_id": parent_id,
    }
    merged = _unpack_provenance(
        provenance, explicit, _DECISION_PROVENANCE_KEYS,
    )

    if supersedes_decision_id:
        return await _legacy("rka_supersede_decision")(
            old_decision_id=supersedes_decision_id,
            question=question,
            chosen=chosen,
            rationale=rationale,
            decided_by=decided_by,
            phase=phase,
            kind=kind,
            project_id=project_id,
        )

    return await _legacy("rka_add_decision")(
        question=question,
        phase=phase,
        decided_by=decided_by,
        options=options,
        chosen=chosen,
        rationale=rationale,
        parent_id=merged["parent_id"],
        related_literature=merged["related_literature"],
        related_journal=merged["related_journal"],
        kind=kind,
        assumptions=assumptions,
        project_id=project_id,
    )


# ---------------------------------------------------------------------------
# rka_session dispatch — UNSCOPED (no project_id required)
# ---------------------------------------------------------------------------

_SESSION_ACTIONS = (
    "list_projects",
    "create_project",
    "set_project",
    "reset",
    "digest",
    "health",
    "help",
    "export",
    "generate_claude_md",
)


async def dispatch_session(
    action: str,
    *,
    # project mgmt
    project_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    # export / generate_claude_md
    format: str = "markdown",
    scope: str = "state",
    role: str = "executor",
    # help
    name_lookup: str | None = None,
) -> str:
    """[ANY] Session-level dispatcher — UNSCOPED.

    Most actions take no project_id. The exceptions are `export`,
    `generate_claude_md`, `digest`, and `set_project`, all of which
    need project_id (session-flavored but project-scoped at the REST
    layer).

    Actions:
      - list_projects: discover available projects.
      - create_project: bootstrap a new project (returns project_id).
      - set_project: DEPRECATED no-op (kept for clear warning).
      - reset: clear in-process session tracker.
      - digest: compact session summary.
      - health: API health probe.
      - help: per-verb / per-legacy-tool help.
      - export: data dump (project-scoped).
      - generate_claude_md: render project-specific CLAUDE.md.
    """
    if action not in _SESSION_ACTIONS:
        return _err(
            "invalid_action",
            f"rka_session: unknown action {action!r}",
            valid=list(_SESSION_ACTIONS),
        )

    if action == "list_projects":
        return await _legacy("rka_list_projects")()

    if action == "create_project":
        if not name:
            return _err(
                "missing_field",
                "rka_session(action='create_project'): name is required",
            )
        return await _legacy("rka_create_project")(
            name=name, description=description,
        )

    if action == "set_project":
        if not project_id:
            return _err(
                "missing_field",
                "rka_session(action='set_project'): project_id is required "
                "(though this action is a deprecated no-op since v2.6)",
            )
        return await _legacy("rka_set_project")(project_id=project_id)

    if action == "reset":
        return await _legacy("rka_reset_session")()

    if action == "digest":
        if not project_id:
            return _err(
                "missing_field",
                "rka_session(action='digest'): project_id is required",
            )
        return await _legacy("rka_session_digest")(project_id=project_id)

    if action == "health":
        # Best-effort REST probe — uses the same _client() shape the
        # other dispatchers use.
        from rka.mcp.server import _client

        try:
            async with _client() as c:
                r = await c.get("/api/projects")
                ok = r.is_success
                code = r.status_code
        except Exception as exc:
            return json.dumps({
                "status": "unhealthy",
                "error": str(exc)[:200],
            }, indent=2)
        return json.dumps({
            "status": "healthy" if ok else "degraded",
            "rest_status_code": code,
        }, indent=2)

    if action == "help":
        if not name_lookup:
            return json.dumps({
                "verbs": list(VERBS),
                "session_actions": list(_SESSION_ACTIONS),
                "hint": (
                    "Pass name_lookup=<tool_name> for per-legacy-tool "
                    "help (e.g. name_lookup='rka_add_note')."
                ),
            }, indent=2)
        return await _legacy("rka_help")(name=name_lookup)

    if action == "export":
        if not project_id:
            return _err(
                "missing_field",
                "rka_session(action='export'): project_id is required",
            )
        return await _legacy("rka_export")(
            format=format, scope=scope, project_id=project_id,
        )

    if action == "generate_claude_md":
        if not project_id:
            return _err(
                "missing_field",
                "rka_session(action='generate_claude_md'): project_id is required",
            )
        return await _legacy("rka_generate_claude_md")(
            role=role, project_id=project_id,
        )

    return _err(
        "invalid_action", f"rka_session: unhandled action {action!r}",
    )


# ---------------------------------------------------------------------------
# rka_record_decision Phase-X²' helpers — legacy decision tools don't
# expose `importance` / `justified_by` directly, but the verb signature
# accepts them for forward-compat (PR-2 will widen the REST layer to
# accept them; in PR-1 we silently drop). The dispatcher above already
# routes through `rka_add_decision` / `rka_supersede_decision` which
# don't accept those kwargs.
# ---------------------------------------------------------------------------

# (No-op marker comment so future readers know why those kwargs are
# accepted but not forwarded.)


# ---------------------------------------------------------------------------
# Module-level exports
# ---------------------------------------------------------------------------

VERBS = (
    "rka_query",
    "rka_record_note",
    "rka_record_decision",
    "rka_record_literature",
    "rka_mission",
    "rka_checkpoint",
    "rka_review",
    "rka_session",
)


__all__ = [
    "VERBS",
    "_QUERY_DISPATCH",
    "_SESSION_ACTIONS",
    "dispatch_query",
    "dispatch_record_note",
    "dispatch_record_decision",
    "dispatch_record_literature",
    "dispatch_mission",
    "dispatch_checkpoint",
    "dispatch_review",
    "dispatch_session",
]
