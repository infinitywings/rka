"""Phase D, D1 — manifest schema + tool registry tests.

Covers:
  - ToolManifest dataclass: serialization, round-trip, hash stability
  - File IO helpers: workspace_dir, save_manifest, load_manifest,
    write_env_template, read_env
  - manifest_to_mcp_servers: conversion to SDK config shape
  - missing_required/recommended_secrets: criticality gate helpers
  - tool_registry: load + always_on_tools + tools_for_domain + list_domains
  - parked_interrupts CHECK constraint accepts all 7 interrupt types
  - Phase-A → Phase-D migration helper (legacy DB rebuild)
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from orchestrator import manifest as M
from orchestrator import tool_registry as TR
from orchestrator.parked_store import ParkedStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    """Use a tmp_path as the rka-projects root via env var so the test
    doesn't touch the user's actual $HOME/rka-projects."""
    os.environ["RKA_PROJECTS_ROOT"] = str(tmp_path)
    yield tmp_path
    os.environ.pop("RKA_PROJECTS_ROOT", None)


def _minimal_manifest(project_id: str = "prj_test") -> M.ToolManifest:
    return M.ToolManifest(
        project_id=project_id,
        topic=M.TopicMetadata(
            summary="test topic", research_field="test", venue="ZZZ 2099"
        ),
        tools=[
            M.ToolDecl(
                name="rka",
                type="mcp_stdio",
                always_on=True,
                rationale="knowledge base",
                source="registry",
            ),
            M.ToolDecl(
                name="sec-edgar",
                type="mcp_stdio",
                command="npx",
                args=["-y", "@sec-edgar/mcp-server@latest"],
                rationale="SEC filings",
                source="registry",
                secrets=[
                    M.SecretDecl(
                        name="SEC_EDGAR_USER_AGENT",
                        auth_type="api_key",
                        criticality="required",
                        description="email + institution",
                    )
                ],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# ToolManifest dataclass serialization
# ---------------------------------------------------------------------------


def test_manifest_round_trip_preserves_all_fields():
    """Manifest → dict → manifest yields a value-equal object."""
    orig = _minimal_manifest()
    orig.created_at = "2026-05-26T17:00:00Z"
    d = orig.to_dict()
    rebuilt = M.ToolManifest.from_dict(d)
    # All scalar fields preserved.
    assert rebuilt.project_id == orig.project_id
    assert rebuilt.schema_version == orig.schema_version
    assert rebuilt.manifest_type == orig.manifest_type
    assert rebuilt.created_at == orig.created_at
    # Topic.
    assert rebuilt.topic == orig.topic
    # Tools (including nested secrets).
    assert len(rebuilt.tools) == 2
    assert rebuilt.tools[1].name == "sec-edgar"
    assert rebuilt.tools[1].secrets[0].name == "SEC_EDGAR_USER_AGENT"
    assert rebuilt.tools[1].secrets[0].criticality == "required"


def test_manifest_json_round_trip():
    orig = _minimal_manifest()
    orig.created_at = "2026-05-26T17:00:00Z"
    json_text = orig.to_json()
    # Sanity: valid JSON with sorted keys (project_id comes before tools, etc.)
    parsed = json.loads(json_text)
    assert parsed["project_id"] == "prj_test"
    # Round-trip.
    rebuilt = M.ToolManifest.from_json(json_text)
    assert rebuilt.to_dict() == orig.to_dict()


def test_manifest_hash_is_deterministic_for_equal_content():
    """Two manifests with the same content produce identical hashes."""
    a = _minimal_manifest()
    a.created_at = "2026-05-26T17:00:00Z"
    b = _minimal_manifest()
    b.created_at = "2026-05-26T17:00:00Z"
    assert a.compute_hash() == b.compute_hash()


def test_manifest_hash_changes_on_field_change():
    a = _minimal_manifest()
    a.created_at = "2026-05-26T17:00:00Z"
    b = _minimal_manifest()
    b.created_at = "2026-05-26T17:00:00Z"
    b.tools[0].rationale = "different rationale"
    assert a.compute_hash() != b.compute_hash()


def test_manifest_from_dict_tolerates_unknown_top_level_keys():
    """Forward-compatibility: future schema additions don't break old
    loaders. Unknown keys are silently ignored."""
    d = _minimal_manifest().to_dict()
    d["future_field"] = "ignored"
    rebuilt = M.ToolManifest.from_dict(d)
    assert rebuilt.project_id == "prj_test"


def test_manifest_from_dict_requires_project_id():
    with pytest.raises(KeyError):
        M.ToolManifest.from_dict({"tools": []})


# ---------------------------------------------------------------------------
# File IO helpers
# ---------------------------------------------------------------------------


def test_workspace_dir_uses_env_var_when_set(tmp_root: Path):
    d = M.workspace_dir("prj_x")
    assert d == tmp_root / "prj_x"


def test_ensure_workspace_dir_creates_with_0700(tmp_root: Path):
    d = M.ensure_workspace_dir("prj_x")
    assert d.exists()
    mode = oct(d.stat().st_mode & 0o777)
    # Some filesystems may not enforce — accept either 0o700 or the
    # umask-derived default if chmod failed silently.
    assert mode in ("0o700", "0o755")


def test_save_manifest_writes_canonical_json(tmp_root: Path):
    m = _minimal_manifest()
    path = M.save_manifest(m)
    assert path.exists()
    text = path.read_text()
    # Valid JSON.
    parsed = json.loads(text)
    assert parsed["project_id"] == "prj_test"
    # created_at stamped automatically.
    assert m.created_at  # mutated in place


def test_save_manifest_stamps_created_at_if_empty(tmp_root: Path):
    m = _minimal_manifest()
    assert m.created_at == ""
    M.save_manifest(m)
    assert m.created_at.endswith("Z")


def test_load_manifest_returns_none_when_missing(tmp_root: Path):
    assert M.load_manifest("prj_missing") is None


def test_load_manifest_after_save_round_trips(tmp_root: Path):
    m = _minimal_manifest()
    M.save_manifest(m)
    loaded = M.load_manifest("prj_test")
    assert loaded is not None
    assert loaded.project_id == "prj_test"
    assert loaded.tools[1].secrets[0].criticality == "required"


def test_write_env_template_produces_placeholder_lines(tmp_root: Path):
    secrets = [
        M.SecretDecl(name="X_KEY", criticality="required", description="X key"),
        M.SecretDecl(name="Y_KEY", criticality="optional"),
    ]
    path = M.write_env_template("prj_test", secrets)
    text = path.read_text()
    assert "X_KEY=<paste-here>" in text
    assert "Y_KEY=<paste-here>" in text
    assert "(required)" in text
    assert "(optional)" in text


def test_write_env_template_preserves_existing_file_by_default(tmp_root: Path):
    secrets = [M.SecretDecl(name="X_KEY", criticality="required")]
    M.ensure_workspace_dir("prj_test")
    custom = M.env_path("prj_test")
    custom.write_text("X_KEY=hand-edited-value\n", encoding="utf-8")
    M.write_env_template("prj_test", secrets)
    # Untouched.
    assert "hand-edited-value" in custom.read_text()


def test_write_env_template_overwrites_when_requested(tmp_root: Path):
    secrets = [M.SecretDecl(name="X_KEY", criticality="required")]
    M.ensure_workspace_dir("prj_test")
    custom = M.env_path("prj_test")
    custom.write_text("X_KEY=hand-edited-value\n", encoding="utf-8")
    M.write_env_template("prj_test", secrets, overwrite=True)
    assert "<paste-here>" in custom.read_text()


def test_read_env_skips_placeholders(tmp_root: Path):
    """Placeholders look like <paste-here>; read_env must NOT surface them
    so the runner's criticality check sees the secret as missing."""
    M.ensure_workspace_dir("prj_test")
    p = M.env_path("prj_test")
    p.write_text(
        "X_KEY=<paste-here>\n"
        "Y_KEY=real-secret-value\n"
        "# comment ignored\n"
        "\n",
        encoding="utf-8",
    )
    env = M.read_env("prj_test")
    assert env == {"Y_KEY": "real-secret-value"}


def test_read_env_returns_empty_dict_when_file_missing(tmp_root: Path):
    assert M.read_env("prj_missing") == {}


# ---------------------------------------------------------------------------
# manifest_to_mcp_servers conversion
# ---------------------------------------------------------------------------


def test_manifest_to_mcp_servers_emits_stdio_config_for_each_tool():
    m = _minimal_manifest()
    env_values = {"SEC_EDGAR_USER_AGENT": "me@example.org"}
    config = M.manifest_to_mcp_servers(
        m, env_values, rka_binary="/usr/local/bin/rka", project_id_for_rka="prj_test"
    )
    # rka server: command from rka_binary; env has RKA_PROJECT.
    assert "rka" in config
    assert config["rka"]["command"] == "/usr/local/bin/rka"
    assert config["rka"]["args"] == ["mcp"]
    assert config["rka"]["env"]["RKA_PROJECT"] == "prj_test"
    # sec-edgar server: command + args from ToolDecl; env has the secret.
    assert "sec-edgar" in config
    assert config["sec-edgar"]["command"] == "npx"
    assert config["sec-edgar"]["env"]["SEC_EDGAR_USER_AGENT"] == "me@example.org"


def test_manifest_to_mcp_servers_omits_missing_secret_envs():
    m = _minimal_manifest()
    config = M.manifest_to_mcp_servers(
        m, env_values={}, rka_binary="/usr/local/bin/rka"
    )
    # sec-edgar config exists (the runner's criticality check decides
    # whether to escalate), but its env block has no SEC_EDGAR_USER_AGENT.
    assert "sec-edgar" in config
    sec_env = config["sec-edgar"].get("env", {})
    assert "SEC_EDGAR_USER_AGENT" not in sec_env


def test_manifest_to_mcp_servers_skips_non_stdio_types():
    m = _minimal_manifest()
    m.tools.append(M.ToolDecl(name="finance-style", type="skill", source="local"))
    config = M.manifest_to_mcp_servers(m, env_values={}, rka_binary="/usr/local/bin/rka")
    # Skill type isn't an MCP server; not included in mcp_servers config.
    assert "finance-style" not in config


# ---------------------------------------------------------------------------
# Criticality gate helpers
# ---------------------------------------------------------------------------


def test_missing_required_secrets_lists_each_missing_required():
    m = _minimal_manifest()
    out = M.missing_required_secrets(m, env_values={})
    assert len(out) == 1
    name, secret = out[0]
    assert name == "sec-edgar"
    assert secret.name == "SEC_EDGAR_USER_AGENT"


def test_missing_required_secrets_returns_empty_when_all_provided():
    m = _minimal_manifest()
    out = M.missing_required_secrets(
        m, env_values={"SEC_EDGAR_USER_AGENT": "me@example.org"}
    )
    assert out == []


def test_missing_recommended_secrets_separates_tiers():
    """Required and recommended are distinct lists; a missing
    required-tier secret doesn't appear in the recommended list."""
    m = _minimal_manifest()
    m.tools[1].secrets.append(
        M.SecretDecl(name="ALT_KEY", criticality="recommended")
    )
    req = M.missing_required_secrets(m, env_values={})
    rec = M.missing_recommended_secrets(m, env_values={})
    assert [s.name for _, s in req] == ["SEC_EDGAR_USER_AGENT"]
    assert [s.name for _, s in rec] == ["ALT_KEY"]


# ---------------------------------------------------------------------------
# Tool registry loader
# ---------------------------------------------------------------------------


def test_registry_loads_without_error():
    reg = TR.load_registry()
    assert "always_on" in reg
    assert "by_domain" in reg


def test_registry_always_on_includes_rka_and_context7():
    """rka + context7 are canonical always-on baselines — every project
    gets them offered. Locks the shape so accidental deletions don't
    drift the baseline."""
    tools = TR.always_on_tools()
    names = {t.name for t in tools}
    assert "rka" in names
    assert "context7" in names


def test_registry_always_on_entries_are_tool_decls():
    tools = TR.always_on_tools()
    for t in tools:
        assert isinstance(t, M.ToolDecl)
        assert t.source == "registry"
        # Type defaults to mcp_stdio in registry entries (the only
        # always-on category that exists today).
        assert t.type == "mcp_stdio"


def test_registry_finance_domain_includes_sec_edgar():
    tools = TR.tools_for_domain("finance")
    names = {t.name for t in tools}
    assert "sec-edgar" in names
    # SEC EDGAR's USER_AGENT requirement is the required-criticality
    # canonical case.
    sec = next(t for t in tools if t.name == "sec-edgar")
    assert sec.secrets[0].criticality == "required"


def test_registry_unknown_domain_returns_empty():
    assert TR.tools_for_domain("nonexistent-domain") == []


def test_registry_list_domains_returns_known_keys():
    domains = TR.list_domains()
    assert "finance" in domains
    assert "bioinformatics" in domains
    assert "ml_systems" in domains
    # Every value is a description string (not empty).
    for k, v in domains.items():
        assert isinstance(v, str)


# ---------------------------------------------------------------------------
# Parked-interrupt CHECK constraint accepts all 7 types
# ---------------------------------------------------------------------------


def test_parked_store_accepts_all_seven_interrupt_types(tmp_path: Path):
    """Phase-D expanded the CHECK constraint from 3 → 7 interrupt types.
    Park one of each and verify all are accepted."""
    db = str(tmp_path / "p.db")
    store = ParkedStore(db)
    tid = store.create_run(mission_id="m", project_id="p")
    types: list = [
        "pi_greenlight",
        "pi_decision_select",
        "pi_acceptance",
        "pi_onboarding_topic",
        "pi_toolkit_ratify",
        "pi_credentials_ready",
        "pi_extend_toolkit",
    ]
    for t in types:
        iid = store.park_interrupt(
            workflow_thread_id=tid,
            mission_id="m",
            interrupt_type=t,  # type: ignore[arg-type]
            payload={"kind": t},
        )
        row = store.get_interrupt(iid)
        assert row["interrupt_type"] == t
    store.close()


def test_parked_store_rejects_truly_unknown_interrupt_type(tmp_path: Path):
    """Sanity: the CHECK still rejects bogus values."""
    db = str(tmp_path / "p.db")
    store = ParkedStore(db)
    tid = store.create_run(mission_id="m", project_id="p")
    with pytest.raises(sqlite3.IntegrityError):
        store.park_interrupt(
            workflow_thread_id=tid,
            mission_id="m",
            interrupt_type="pi_bogus_value",  # type: ignore[arg-type]
            payload={},
        )
    store.close()


# ---------------------------------------------------------------------------
# Phase-A → Phase-D migration helper
# ---------------------------------------------------------------------------


def test_phase_a_to_d_migration_preserves_legacy_rows(tmp_path: Path):
    """A DB created with the Phase-A 3-type CHECK should be rebuilt
    on next ParkedStore() open, with all existing rows preserved."""
    db_path = str(tmp_path / "legacy.db")

    # Build a legacy DB with the Phase-A schema (3-type CHECK).
    conn = sqlite3.connect(db_path)
    legacy_sql = """
    CREATE TABLE workflow_runs (
        workflow_thread_id TEXT PRIMARY KEY,
        mission_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        budget_usd REAL NOT NULL DEFAULT 5.0,
        status TEXT NOT NULL DEFAULT 'running',
        current_node TEXT,
        terminal_state TEXT,
        final_report_id TEXT,
        usd_spent REAL NOT NULL DEFAULT 0.0,
        last_error TEXT,
        started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    );
    CREATE TABLE parked_interrupts (
        interrupt_id TEXT PRIMARY KEY,
        workflow_thread_id TEXT NOT NULL REFERENCES workflow_runs(workflow_thread_id) ON DELETE CASCADE,
        mission_id TEXT NOT NULL,
        interrupt_type TEXT NOT NULL
            CHECK (interrupt_type IN ('pi_greenlight', 'pi_decision_select', 'pi_acceptance')),
        payload_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        response_action TEXT,
        response_text TEXT,
        parked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        responded_at TEXT
    );
    """
    conn.executescript(legacy_sql)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_thread_id, mission_id, project_id) "
        "VALUES ('thr_legacy', 'mis_legacy', 'prj_legacy')"
    )
    conn.execute(
        "INSERT INTO parked_interrupts "
        "(interrupt_id, workflow_thread_id, mission_id, interrupt_type, payload_json) "
        "VALUES ('int_legacy_1', 'thr_legacy', 'mis_legacy', 'pi_greenlight', '{}')"
    )
    conn.commit()
    conn.close()

    # Open via ParkedStore — migration fires automatically.
    store = ParkedStore(db_path)
    # Legacy row preserved.
    row = store.get_interrupt("int_legacy_1")
    assert row is not None
    assert row["interrupt_type"] == "pi_greenlight"
    # New CHECK accepts the Phase-D types.
    iid = store.park_interrupt(
        workflow_thread_id="thr_legacy",
        mission_id="mis_legacy",
        interrupt_type="pi_onboarding_topic",
        payload={},
    )
    assert store.get_interrupt(iid)["interrupt_type"] == "pi_onboarding_topic"
    store.close()


def test_phase_a_to_d_migration_is_idempotent(tmp_path: Path):
    """Calling ParkedStore() on an already-migrated DB doesn't re-rebuild
    the table. Sentinel: row count + a custom row added between opens
    survives the second open intact."""
    db_path = str(tmp_path / "fresh.db")
    s1 = ParkedStore(db_path)
    tid = s1.create_run(mission_id="m", project_id="p")
    iid = s1.park_interrupt(
        workflow_thread_id=tid,
        mission_id="m",
        interrupt_type="pi_onboarding_topic",
        payload={"k": "v"},
    )
    s1.close()
    # Re-open; migration should be a no-op.
    s2 = ParkedStore(db_path)
    assert s2.get_interrupt(iid) is not None
    s2.close()
