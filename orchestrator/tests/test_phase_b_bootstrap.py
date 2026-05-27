"""Phase B - orchestrator-level credential bootstrap tests.

Covers:
  - bootstrap_catalog.yaml loads + validates the 5 shipped entries
  - propose_for_intent: required/recommended always selected;
    optional matched on substring or "full install" hint
  - render_env_template emits annotated slots + group markers
  - read_env_file ignores comments + placeholders; preserves real values
  - verify_filled classifies missing/valid/rejected/deferred correctly
    via injected HTTP-client fake
  - bootstrap_propose_node populates state correctly
  - bootstrap_emit_template_node writes the file + sets template_path
  - bootstrap_verify_node sets terminal_state based on required-pass
  - phase_b_graph compiles end-to-end through a happy path with a
    fake interrupt_fn
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# bootstrap module
# ---------------------------------------------------------------------------


def test_catalog_loads_with_5_entries():
    from orchestrator import bootstrap as B
    entries = B.load_catalog()
    ids = [e.id for e in entries]
    assert set(ids) == {
        "claude-oauth", "anthropic-api-key",
        "semantic-scholar", "serpapi", "openalex-mailto",
    }


def test_catalog_claude_auth_group_is_mutually_exclusive():
    from orchestrator import bootstrap as B
    entries = B.load_catalog()
    by_id = {e.id: e for e in entries}
    assert by_id["claude-oauth"].group == "claude-auth"
    assert by_id["anthropic-api-key"].group == "claude-auth"
    assert by_id["semantic-scholar"].group is None


def test_propose_empty_intent_selects_required_plus_recommended():
    from orchestrator import bootstrap as B
    entries = B.load_catalog()
    selected = B.propose_for_intent("", entries)
    ids = {e.id for e in selected}
    # Both Claude auth (required, group) + Semantic Scholar (recommended)
    assert "claude-oauth" in ids
    assert "anthropic-api-key" in ids
    assert "semantic-scholar" in ids
    # Optional entries dropped without a mention
    assert "serpapi" not in ids
    assert "openalex-mailto" not in ids


def test_propose_full_install_picks_optional_too():
    from orchestrator import bootstrap as B
    entries = B.load_catalog()
    selected = B.propose_for_intent("give me the full install with everything", entries)
    ids = {e.id for e in selected}
    assert ids == {
        "claude-oauth", "anthropic-api-key",
        "semantic-scholar", "serpapi", "openalex-mailto",
    }


def test_propose_substring_match_picks_specific_optional():
    from orchestrator import bootstrap as B
    entries = B.load_catalog()
    # User mentions SerpAPI by env_var name (case-insensitive)
    selected = B.propose_for_intent("just need serpapi please", entries)
    ids = {e.id for e in selected}
    assert "serpapi" in ids
    assert "openalex-mailto" not in ids


def test_render_env_template_includes_group_marker_and_placeholders():
    from orchestrator import bootstrap as B
    entries = B.load_catalog()
    text = B.render_env_template(entries)
    # Group note appears once per group member
    assert text.count("GROUP `claude-auth`") == 2
    # Every env_var ends up as a paste slot
    for e in entries:
        assert f"{e.env_var}=<paste-here>" in text or f"# {e.env_var}=<paste-here>" in text


def test_render_env_template_marks_existing_values_as_already_set():
    from orchestrator import bootstrap as B
    entries = B.load_catalog()
    existing = {"SEMANTIC_SCHOLAR_API_KEY": "actual-real-secret-DO-NOT-LEAK"}
    text = B.render_env_template(entries, existing_values=existing)
    # The actual secret value MUST NOT appear in the rendered text.
    assert "actual-real-secret-DO-NOT-LEAK" not in text
    # The "already set" marker appears for that entry.
    assert "already set in existing .env" in text


def test_read_env_file_strips_comments_and_placeholders(tmp_path: Path):
    from orchestrator import bootstrap as B
    p = tmp_path / ".env"
    p.write_text(
        "# leading comment\n"
        "REAL_KEY=actual-value\n"
        "PLACEHOLDER_KEY=<paste-here>\n"
        "BLANK=\n"
        "QUOTED='quoted-value'\n"
        "DBLQUOTED=\"double-quoted\"\n"
        "WITH_COMMENT=value-here  # trailing\n",
        encoding="utf-8",
    )
    values = B.read_env_file(p)
    assert values["REAL_KEY"] == "actual-value"
    assert "PLACEHOLDER_KEY" not in values  # placeholder dropped
    assert "BLANK" not in values  # empty dropped
    assert values["QUOTED"] == "quoted-value"
    assert values["DBLQUOTED"] == "double-quoted"
    assert values["WITH_COMMENT"] == "value-here"


def test_verify_filled_classifies_each_outcome():
    from orchestrator import bootstrap as B
    entries = B.load_catalog()
    by_id = {e.id: e for e in entries}

    # Inject a deterministic HTTP fake that returns per-URL classifications.
    calls: list[tuple[str, str]] = []

    def fake_http(method: str, url: str, headers: dict, timeout: float):
        calls.append((method, url))
        # The verify body never sees `value`; we only see the URL after
        # substitution. So we key on host.
        if "anthropic.com" in url:
            return (200, None)  # valid
        if "semanticscholar.org" in url:
            return (401, None)  # rejected
        if "serpapi.com" in url:
            return (0, "TimeoutError: nope")  # unreachable
        if "openalex.org" in url:
            return (200, None)  # valid
        return (500, None)  # other

    env_values = {
        "CLAUDE_CODE_OAUTH_TOKEN": "x",        # no probe (skip method)
        "ANTHROPIC_API_KEY": "x",              # valid
        "SEMANTIC_SCHOLAR_API_KEY": "x",       # rejected
        "SERPAPI_KEY": "x",                    # unreachable
        # OPENALEX_MAILTO intentionally missing
    }
    results = B.verify_filled(
        [by_id["claude-oauth"], by_id["anthropic-api-key"],
         by_id["semantic-scholar"], by_id["serpapi"], by_id["openalex-mailto"]],
        env_values,
        http_client=fake_http,
    )
    by_eid = {r.entry_id: r for r in results}
    assert by_eid["claude-oauth"].classification == "deferred"
    assert by_eid["anthropic-api-key"].classification == "valid"
    assert by_eid["semantic-scholar"].classification == "rejected"
    assert by_eid["serpapi"].classification == "unreachable"
    assert by_eid["openalex-mailto"].classification == "missing"


def test_verify_render_summary_never_includes_values():
    from orchestrator import bootstrap as B
    entries = B.load_catalog()
    results = [
        B.VerifyResult(
            entry_id="claude-oauth", env_var="CLAUDE_CODE_OAUTH_TOKEN",
            classification="deferred", detail="OAuth deferred",
        ),
        B.VerifyResult(
            entry_id="semantic-scholar", env_var="SEMANTIC_SCHOLAR_API_KEY",
            classification="rejected", detail="HTTP 401 (endpoint reachable; key rejected)",
        ),
    ]
    text = B.render_verify_summary(results, catalog=entries)
    assert "Claude Code OAuth token" in text
    assert "Semantic Scholar API key" in text
    # No raw secret content in the summary.
    assert "<paste-here>" not in text


# ---------------------------------------------------------------------------
# Phase B nodes (background)
# ---------------------------------------------------------------------------


class _FakeMCP:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []


def _make_state(**overrides) -> dict:
    base = {
        "workflow_thread_id": "thr_test",
        "mission_id": "_bootstrap_",
        "project_id": "",
        "interrupts": [],
        "decisions_to_present": [],
        "bootstrap_intent": "",
        "bootstrap_proposed_ids": [],
        "bootstrap_ratified_ids": [],
        "bootstrap_template_path": "",
        "bootstrap_verify_results": [],
    }
    base.update(overrides)
    return base


def test_bootstrap_propose_node_picks_required_for_empty_intent():
    from orchestrator.nodes import bootstrap as bnodes
    state = _make_state(bootstrap_intent="")
    out = bnodes.bootstrap_propose_node(state, sdk=None, mcp=_FakeMCP())
    assert out["current_node"] == "bootstrap_propose"
    # Required + recommended (3 entries) selected for empty intent.
    assert set(out["bootstrap_proposed_ids"]) == {
        "claude-oauth", "anthropic-api-key", "semantic-scholar",
    }
    # Decisions-to-present stages each as a renderable item.
    assert len(out["decisions_to_present"]) == 3
    for item in out["decisions_to_present"]:
        assert item["source_node"] == "bootstrap_propose"
        # Never include the env_var value (we don't have one yet).
        assert "value" not in item


def test_bootstrap_emit_template_node_writes_file_with_mode_0600(tmp_path: Path):
    from orchestrator.nodes import bootstrap as bnodes
    env_path = tmp_path / ".env"
    state = _make_state(
        bootstrap_ratified_ids=["claude-oauth", "semantic-scholar"],
    )
    out = bnodes.bootstrap_emit_template_node(
        state, sdk=None, mcp=_FakeMCP(), env_path=env_path
    )
    template_path = Path(out["bootstrap_template_path"])
    assert template_path.is_file()
    assert template_path.name == ".env.example"
    text = template_path.read_text(encoding="utf-8")
    assert "CLAUDE_CODE_OAUTH_TOKEN=<paste-here>" in text
    assert "SEMANTIC_SCHOLAR_API_KEY=<paste-here>" in text
    # File mode 0600 (owner-read/write only) when OS supports it.
    import stat
    mode = stat.S_IMODE(template_path.stat().st_mode)
    assert mode == 0o600 or mode & 0o077 == 0  # tolerate platform quirks


def test_bootstrap_emit_template_preserves_existing_env(tmp_path: Path):
    from orchestrator.nodes import bootstrap as bnodes
    env_path = tmp_path / ".env"
    env_path.write_text(
        "SEMANTIC_SCHOLAR_API_KEY=already-have-this-secret\n",
        encoding="utf-8",
    )
    state = _make_state(
        bootstrap_ratified_ids=["semantic-scholar", "serpapi"],
    )
    out = bnodes.bootstrap_emit_template_node(
        state, sdk=None, mcp=_FakeMCP(), env_path=env_path
    )
    template_text = Path(out["bootstrap_template_path"]).read_text(encoding="utf-8")
    # The existing value MUST NOT be echoed in the template.
    assert "already-have-this-secret" not in template_text
    # And the "already set" marker should be in place for that var.
    assert "SEMANTIC_SCHOLAR_API_KEY" in template_text
    assert "already set in existing .env" in template_text


def test_bootstrap_verify_node_terminal_on_all_pass(tmp_path: Path, monkeypatch):
    from orchestrator import bootstrap as B
    from orchestrator.nodes import bootstrap as bnodes

    env_path = tmp_path / ".env"
    env_path.write_text(
        "CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-fake\n"
        "ANTHROPIC_API_KEY=sk-ant-api03-fake\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        B, "verify_filled",
        lambda entries, env_values, **kw: [
            B.VerifyResult(
                entry_id=e.id, env_var=e.env_var,
                classification="deferred" if e.id == "claude-oauth" else "valid",
                detail="ok",
            )
            for e in entries
        ],
    )
    state = _make_state(bootstrap_ratified_ids=["claude-oauth", "anthropic-api-key"])
    out = bnodes.bootstrap_verify_node(
        state, sdk=None, mcp=_FakeMCP(), env_path=env_path
    )
    assert out["terminal_state"] == "complete"
    assert len(out["bootstrap_verify_results"]) == 2


def test_bootstrap_verify_node_escalates_on_required_fail(tmp_path: Path, monkeypatch):
    from orchestrator import bootstrap as B
    from orchestrator.nodes import bootstrap as bnodes

    monkeypatch.setattr(
        B, "verify_filled",
        lambda entries, env_values, **kw: [
            B.VerifyResult(
                entry_id=e.id, env_var=e.env_var,
                classification="rejected" if e.id == "anthropic-api-key" else "valid",
                detail="HTTP 401",
            )
            for e in entries
        ],
    )
    state = _make_state(bootstrap_ratified_ids=["anthropic-api-key"])
    env_path = tmp_path / ".env"
    env_path.write_text("ANTHROPIC_API_KEY=fake\n", encoding="utf-8")
    out = bnodes.bootstrap_verify_node(
        state, sdk=None, mcp=_FakeMCP(), env_path=env_path
    )
    assert out["terminal_state"] == "escalated"


# ---------------------------------------------------------------------------
# Phase B graph - end-to-end happy path with fake interrupt_fn
# ---------------------------------------------------------------------------


def _stub_interrupt(payload):
    """Same convention as test_phase_o_graph: stub returns "accept" for
    graph-compile smoke tests. Node-level interrupt behavior is covered
    by the unit tests above (propose / emit_template / verify nodes)."""
    return "accept"


def test_phase_b_graph_compiles_with_all_six_nodes():
    from orchestrator import phase_b_graph

    g = phase_b_graph.build_phase_b_graph(
        sdk=None, mcp=_FakeMCP(), interrupt_fn=_stub_interrupt,
    )
    registered = set(g.get_graph().nodes.keys())
    expected = {
        "pi_bootstrap_intent",
        "bootstrap_propose",
        "pi_bootstrap_ratify",
        "bootstrap_emit_template",
        "pi_bootstrap_fill_ack",
        "bootstrap_verify",
    }
    assert expected.issubset(registered), (
        f"missing nodes: {expected - registered}"
    )


def test_phase_b_routing_after_ratify_accept_advances_to_emit():
    """Set-identity routing: ratified_ids non-empty -> emit_template."""
    from orchestrator import phase_b_graph as PBG
    assert PBG._route_after_bootstrap_ratify(
        {"bootstrap_ratified_ids": ["claude-oauth"]}
    ) == "bootstrap_emit_template"


def test_phase_b_routing_after_ratify_empty_ends():
    from orchestrator import phase_b_graph as PBG
    from langgraph.graph import END
    assert PBG._route_after_bootstrap_ratify(
        {"bootstrap_ratified_ids": []}
    ) == END


def test_phase_b_routing_after_fill_ack_accept_advances_to_verify():
    from orchestrator import phase_b_graph as PBG
    result = PBG._route_after_fill_ack({
        "interrupts": [
            {"node_name": "pi_bootstrap_fill_ack", "response": "accept"},
        ],
    })
    assert result == "bootstrap_verify"


def test_phase_b_routing_after_fill_ack_reject_ends():
    from orchestrator import phase_b_graph as PBG
    from langgraph.graph import END
    result = PBG._route_after_fill_ack({
        "interrupts": [
            {"node_name": "pi_bootstrap_fill_ack", "response": "reject"},
        ],
    })
    assert result == END


def test_runner_accept_token_map_has_phase_b_entries():
    """All three Phase B interrupt types must have a configured accept
    token (otherwise resume_token() will raise ValueError when the PI
    accepts the interrupt)."""
    from orchestrator import runner as R
    assert R._ACCEPT_TOKEN_BY_TYPE["pi_bootstrap_intent"] == "approve"
    assert R._ACCEPT_TOKEN_BY_TYPE["pi_bootstrap_ratify"] == "accept"
    assert R._ACCEPT_TOKEN_BY_TYPE["pi_bootstrap_fill_ack"] == "accept"


def test_runner_phase_b_interrupt_types_frozenset_complete():
    from orchestrator.runner import OrchestratorRunner
    assert OrchestratorRunner._PHASE_B_INTERRUPT_TYPES == frozenset({
        "pi_bootstrap_intent",
        "pi_bootstrap_ratify",
        "pi_bootstrap_fill_ack",
    })


def test_parked_store_accepts_phase_b_interrupt_type(tmp_path):
    """Schema migration: the CHECK constraint must accept Phase B types."""
    from orchestrator import parked_store as PS
    store = PS.ParkedStore(str(tmp_path / "test.db"))
    thread_id = store.create_run(
        mission_id="_bootstrap_", project_id="_bootstrap_",
    )
    iid = store.park_interrupt(
        workflow_thread_id=thread_id,
        mission_id="_bootstrap_",
        interrupt_type="pi_bootstrap_intent",
        payload={"title": "test"},
    )
    row = store.get_interrupt(iid)
    assert row["interrupt_type"] == "pi_bootstrap_intent"
    store.close()
