"""Project-level tool manifest schema (`tools.json`).

The orchestrator's onboarding subgraph (Phase D) produces a `tools.json`
per project at `~/rka-projects/{project_id}/tools.json`. Subsequent
missions read this manifest to build the SDK subprocess's MCP server
config (replacing the hardcoded rka+context7 surface used in Phase A).

Three storage tiers, per the PI-ratified design (see
`docs/phase-d-onboarding-design.md`):

  1. **tools.json** — the source of truth for execution. Lives on disk
     in the project's workspace dir. Source-controlled-equivalent for
     the project (the PI can hand-edit if needed, then re-run
     onboarding to re-validate).
  2. **.env** — credential values per the `secrets` declarations in
     tools.json. File-mode 0600, gitignored.
  3. **RKA journal entry** — Audit summary referencing the manifest
     hash. The journal is the discoverable/queryable surface; the file
     is canonical for execution.

Hybrid lifecycle (Q1 ratified): a baseline manifest is frozen at
project-creation onboarding. Per-mission extensions layer on top via
`extension_*.json` files (each linked to the baseline by hash); the
combined toolkit for a mission is the baseline merged with that
mission's extensions.

Auth patterns (Q4 ratified): Phase-D MVP supports `api_key` only.
The schema includes `auth_type` so OAuth/Keychain/SA can land later
without breaking changes.

Criticality (Q2 ratified): each secret declares
`required` / `recommended` / `optional`. The runner enforces missing-
credential behavior per tier at session start.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Optional


# ---------------------------------------------------------------------------
# Schema versions
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "v1"
"""Bump when the on-disk manifest shape changes. Consumers should
reject manifests with a different schema_version (or migrate them)."""

MANIFEST_FILENAME = "tools.json"
"""Canonical filename inside the project workspace dir."""

ENV_FILENAME = ".env"
"""Canonical secrets file inside the project workspace dir."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

AuthType = Literal[
    "api_key",        # Phase D MVP: paste-into-.env + HTTP probe
    "oauth_token",    # Phase D2: like api_key but token can expire
    "oauth_browser",  # Phase D2: browser flow + callback
    "keychain",       # Phase D2: macOS Keychain entry (host-only)
    "service_account", # Phase D2: JSON keyfile
    "none",           # Tool needs no credentials (e.g., rka, context7, fs-mcp)
]

Criticality = Literal[
    "required",     # Missing → escalate; PI must provide or downgrade
    "recommended",  # Missing → escalate once at session start
    "optional",     # Missing → skip with journal note
]

ManifestType = Literal[
    "baseline",   # Initial onboarding result; one per project
    "extension",  # Mid-stream addition (Phase D6 future)
]

ToolType = Literal[
    "mcp_stdio",   # Standard MCP stdio server (npm install + npx, or local binary)
    "mcp_http",    # HTTP-mounted MCP (less common)
    "plugin",      # Claude Code plugin (skill bundle, hooks, etc.)
    "skill",       # Lightweight skill markdown bundle
]


# ---------------------------------------------------------------------------
# Sub-record dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SecretDecl:
    """One credential the tool needs to operate.

    Phase-D MVP supports `auth_type="api_key"` with HTTP probe
    validation. The `probe_url` + `probe_header` fields let the
    onboarding daemon validate the credential without sending the value
    through the Claude Code transcript: a HEAD/GET to probe_url with
    the secret as a header value returns 200 if good, 401/403 if not.
    """

    name: str  # env-var name (e.g., "SEC_EDGAR_API_KEY")
    auth_type: AuthType = "api_key"
    criticality: Criticality = "required"
    # Validation probe (api_key + oauth_token only; other auth_types ignore)
    probe_url: Optional[str] = None
    probe_header: Optional[str] = None  # e.g., "Authorization: Bearer <value>"
    # Human-facing prompt for the credential UX
    description: Optional[str] = None
    # v2.6.0+agentic.5 — back-fill of the `shared_with` semantic that was
    # written into user-added entries during Phase D onboarding but never
    # declared on the dataclass. When the same env var serves multiple
    # tools (canonical case: SEC_EDGAR_USER_AGENT shared between sec-edgar
    # and sec-xbrl-structured), the secondary tool's secret entry sets
    # `shared_with` to the canonical tool's name. Used by the credential-
    # UX flow to avoid double-prompting the operator for the same value.
    shared_with: Optional[str] = None


@dataclass
class ToolDecl:
    """One tool entry in the manifest.

    The tool's `command` + `args` are what the orchestrator's runner
    passes to the SDK subprocess's `mcp_servers` config (for mcp_stdio
    types). For non-MCP tools (plugin/skill), the runner uses different
    integration paths.
    """

    name: str  # canonical name (e.g., "rka", "sec-edgar")
    type: ToolType = "mcp_stdio"
    # Stdio launch (for type=mcp_stdio):
    command: Optional[str] = None  # e.g., "npx" or absolute path
    args: list[str] = field(default_factory=list)
    # Optional install hint shown in the credential UX:
    install_hint: Optional[str] = None  # e.g., "npm install -g @sec-edgar/mcp-server"
    # Secrets this tool needs (empty for credential-free tools):
    secrets: list[SecretDecl] = field(default_factory=list)
    # Provenance metadata (always-on baseline tools, etc.):
    always_on: bool = False  # If True, included in every mission's subprocess config
    rationale: Optional[str] = None  # Why this tool was picked at onboarding
    # Source tracking for the audit trail:
    source: Optional[str] = None  # "registry" | "serpapi_augmented" | "user_added" | "web_search" (legacy)


@dataclass
class TopicMetadata:
    """Project-level topic metadata captured during pi_onboarding_topic.

    Attribute named `research_field` (not `field`) because using `field`
    as an attribute name shadows the dataclasses `field` function in
    the class body, breaking the `keywords` default.
    """

    summary: str
    research_field: Optional[str] = None
    venue: Optional[str] = None
    keywords: list[str] = field(default_factory=list)


@dataclass
class ToolManifest:
    """The canonical project tool manifest, persisted as `tools.json`."""

    project_id: str
    schema_version: str = SCHEMA_VERSION
    manifest_type: ManifestType = "baseline"
    # For extensions, the baseline-manifest hash this extension layers on:
    supersedes_baseline_hash: Optional[str] = None
    # For extensions, the parent extension manifest hash (if chained):
    supersedes_extension_hash: Optional[str] = None
    topic: Optional[TopicMetadata] = None
    tools: list[ToolDecl] = field(default_factory=list)
    # Timestamp fields:
    created_at: str = ""
    # Audit-trail link (filled by audit_entry node, Q5):
    audit_journal_id: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to a plain dict suitable for JSON encoding."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialize to canonical JSON (sorted keys, indented for human
        diff-readability)."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def compute_hash(self) -> str:
        """SHA-256 of the canonical JSON encoding. Used for the
        supersedes chain + the audit-journal-entry's `manifest_hash`
        field."""
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, d: dict) -> "ToolManifest":
        """Reconstruct from a dict (e.g., loaded from disk).

        Tolerant of forward-compatible additions: unknown top-level
        keys are ignored. Required fields raise KeyError. Nested
        ToolDecl + SecretDecl + TopicMetadata are also reconstructed.
        """
        # Required fields:
        project_id = d["project_id"]
        # Optional / defaulted:
        schema_version = d.get("schema_version", SCHEMA_VERSION)
        manifest_type = d.get("manifest_type", "baseline")
        supersedes_baseline_hash = d.get("supersedes_baseline_hash")
        supersedes_extension_hash = d.get("supersedes_extension_hash")
        topic_raw = d.get("topic")
        topic = TopicMetadata(**topic_raw) if topic_raw else None
        # v2.6.0+agentic.5 — forward-compat filter for nested dataclasses.
        # The top-level ToolManifest.from_dict already drops unknown
        # top-level keys (matching the docstring). Mirror that posture
        # for the nested SecretDecl + ToolDecl reconstructions so a
        # stored manifest with extra fields (e.g. user-added entries
        # that carry semantic flags not yet declared on the dataclass)
        # round-trips cleanly. Without this filter, any persisted
        # manifest written via set_project_manifest with a field the
        # dataclass doesn't declare fails to load with a TypeError.
        import dataclasses as _dc

        _secret_fields = {f.name for f in _dc.fields(SecretDecl)}
        _tool_fields = {f.name for f in _dc.fields(ToolDecl)}
        tools = []
        for t in d.get("tools", []):
            secrets = [
                SecretDecl(**{k: v for k, v in s.items() if k in _secret_fields})
                for s in t.get("secrets", [])
            ]
            t_kwargs = {
                k: v for k, v in t.items()
                if k != "secrets" and k in _tool_fields
            }
            tools.append(ToolDecl(**t_kwargs, secrets=secrets))
        return cls(
            project_id=project_id,
            schema_version=schema_version,
            manifest_type=manifest_type,
            supersedes_baseline_hash=supersedes_baseline_hash,
            supersedes_extension_hash=supersedes_extension_hash,
            topic=topic,
            tools=tools,
            created_at=d.get("created_at", ""),
            audit_journal_id=d.get("audit_journal_id"),
        )

    @classmethod
    def from_json(cls, json_text: str) -> "ToolManifest":
        return cls.from_dict(json.loads(json_text))


# ---------------------------------------------------------------------------
# File IO helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Optional resolver — when set, takes precedence over the hardcoded
# convention. Used to look up the PI-provided workspace_path from the
# orchestrator's SQLite. Server startup configures this; tests + standalone
# users get the default $HOME/rka-projects behavior.
_workspace_path_resolver: Optional[Callable[[str], Optional[str]]] = None


def set_workspace_path_resolver(fn: Optional[Callable[[str], Optional[str]]]) -> None:
    """Install a project_id → workspace_path resolver. Called once at server
    startup with ParkedStore.get_project_workspace bound."""
    global _workspace_path_resolver
    _workspace_path_resolver = fn


def workspace_dir(project_id: str, *, root: Optional[Path] = None) -> Path:
    """Resolve the project's workspace directory.

    Resolution order:
      1. Explicit `root` parameter (highest)
      2. PI-provided workspace_path via `_workspace_path_resolver`
         (returns `{workspace_path}/.rka/`)
      3. `RKA_PROJECTS_ROOT` env var
      4. `$HOME/rka-projects` (default convention)

    The PI's workspace path takes precedence so manifests + .env files
    live alongside the PI's research files, not in a separate tree.
    """
    if root is not None:
        return Path(root) / project_id

    if _workspace_path_resolver is not None:
        try:
            ws = _workspace_path_resolver(project_id)
            if ws:
                return Path(ws) / ".rka"
        except Exception:
            pass

    env_root = os.environ.get("RKA_PROJECTS_ROOT")
    base = Path(env_root) if env_root else (Path.home() / "rka-projects")
    return Path(base) / project_id


def ensure_workspace_dir(project_id: str, *, root: Optional[Path] = None) -> Path:
    """Create the workspace dir if missing, with permissions 0700.

    Idempotent — safe to call when the dir already exists.
    """
    d = workspace_dir(project_id, root=root)
    d.mkdir(parents=True, exist_ok=True)
    # Tighten perms even if the dir pre-existed with looser perms.
    try:
        d.chmod(0o700)
    except OSError:
        # Some filesystems (e.g., FAT, network mounts) don't support
        # POSIX perms. We don't fail; the secrets file's own 0600 still
        # provides a layer of defense.
        pass
    return d


def manifest_path(project_id: str, *, root: Optional[Path] = None) -> Path:
    """Canonical manifest path."""
    return workspace_dir(project_id, root=root) / MANIFEST_FILENAME


def env_path(project_id: str, *, root: Optional[Path] = None) -> Path:
    """Canonical .env path."""
    return workspace_dir(project_id, root=root) / ENV_FILENAME


def save_manifest(
    manifest: ToolManifest, *, root: Optional[Path] = None
) -> Path:
    """Write the manifest to its canonical path. Returns the path.

    Stamps `created_at` if not already set. Sets file perms 0600 — the
    manifest itself doesn't contain secret values, but pinning perms
    matches the workspace's secret-handling stance and prevents
    accidental publication via web servers etc.
    """
    if not manifest.created_at:
        manifest.created_at = _now_iso()
    ensure_workspace_dir(manifest.project_id, root=root)
    path = manifest_path(manifest.project_id, root=root)
    path.write_text(manifest.to_json(), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def load_manifest(
    project_id: str, *, root: Optional[Path] = None
) -> Optional[ToolManifest]:
    """Load the manifest if present; return None if not found.

    Raises `json.JSONDecodeError` or `KeyError` for malformed manifests
    — callers should treat that as "manifest exists but is broken"
    rather than "no manifest" (the on-disk file should never be
    truncated; if it is, surface the corruption explicitly).
    """
    path = manifest_path(project_id, root=root)
    if not path.is_file():
        return None
    return ToolManifest.from_json(path.read_text(encoding="utf-8"))


def write_env_template(
    project_id: str,
    secrets: list[SecretDecl],
    *,
    root: Optional[Path] = None,
    overwrite: bool = False,
) -> Path:
    """Write a `.env` template with placeholder values for each secret.

    Lines look like:
        # sec-edgar-mcp (required) — SEC EDGAR API key
        SEC_EDGAR_API_KEY=<paste-here>

    File mode 0600 on creation. If the file already exists and
    `overwrite=False`, the existing file is preserved (so PI edits
    don't get wiped on a re-onboard).
    """
    ensure_workspace_dir(project_id, root=root)
    path = env_path(project_id, root=root)
    if path.exists() and not overwrite:
        return path

    lines = [
        f"# Generated by orchestrator onboarding at {_now_iso()}",
        f"# Project: {project_id}",
        "# File mode 0600. NEVER commit to source control.",
        "# Edit values below — replace each <paste-here> with the actual",
        "# credential, then run the orchestrator's probe-validation step.",
        "",
    ]
    for s in secrets:
        crit = f"({s.criticality})"
        desc = f" — {s.description}" if s.description else ""
        lines.append(f"# {s.name} {crit}{desc}")
        lines.append(f"{s.name}=<paste-here>")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def read_env(
    project_id: str, *, root: Optional[Path] = None
) -> dict[str, str]:
    """Read the project's .env into a dict. Returns {} if missing.

    Skips comments + empty lines. Values are taken verbatim — no shell
    interpolation, no quote-stripping (so a value like `"abc def"` has
    the quotes preserved; callers wanting the unquoted value should
    strip explicitly).
    """
    path = env_path(project_id, root=root)
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        # Skip placeholders so the runner can detect "not yet filled".
        if v.startswith("<") and v.endswith(">"):
            continue
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Helpers for the runner's MCP-server-config builder
# ---------------------------------------------------------------------------


def manifest_to_mcp_servers(
    manifest: ToolManifest,
    env_values: dict[str, str],
    *,
    rka_binary: Optional[str] = None,
    project_id_for_rka: Optional[str] = None,
) -> dict:
    """Convert a manifest + a dict of resolved env values into the
    SDK's `mcp_servers` config shape.

    `rka_binary` is the path to the local `rka` MCP stdio launcher
    (resolved by `shutil.which("rka")` in production). When present,
    the `rka` server is added with `RKA_PROJECT` env if
    `project_id_for_rka` is given, mirroring Phase 2.9 T1 behavior.

    Tools with missing required env vars are still added — the runner's
    pre-flight check (Phase D criticality enforcement) decides whether
    to escalate; this function just builds the config dict.
    """
    config: dict = {}
    for tool in manifest.tools:
        if tool.type != "mcp_stdio":
            # mcp_http / plugin / skill have different integration paths;
            # the runner handles those outside the SDK mcp_servers config.
            continue

        # Special-case the rka entry: command/args may be overridden by
        # the local binary that the runner discovered at startup.
        if tool.name == "rka" and rka_binary:
            command = rka_binary
            args = ["mcp"]
        else:
            if not tool.command:
                # No command and not the rka special case — skip this
                # entry; the runner cannot launch it.
                continue
            command = tool.command
            args = list(tool.args)

        server: dict = {"type": "stdio", "command": command, "args": args}

        # Build the env block: propagate every declared secret that has
        # a value in env_values. Plus RKA_PROJECT for the rka server.
        env_block: dict[str, str] = {}
        if tool.name == "rka" and project_id_for_rka:
            env_block["RKA_PROJECT"] = project_id_for_rka
        for s in tool.secrets:
            val = env_values.get(s.name)
            if val:
                env_block[s.name] = val
        if env_block:
            server["env"] = env_block

        config[tool.name] = server
    return config


def missing_required_secrets(
    manifest: ToolManifest, env_values: dict[str, str]
) -> list[tuple[str, SecretDecl]]:
    """Return a list of (tool_name, SecretDecl) for every secret marked
    `criticality="required"` that doesn't have a value in env_values.

    Used by the runner at session start to escalate per Q2 ratification:
    a non-empty list → checkpoint surfaced to PI.
    """
    out: list[tuple[str, SecretDecl]] = []
    for tool in manifest.tools:
        for s in tool.secrets:
            if s.criticality == "required" and not env_values.get(s.name):
                out.append((tool.name, s))
    return out


def missing_recommended_secrets(
    manifest: ToolManifest, env_values: dict[str, str]
) -> list[tuple[str, SecretDecl]]:
    """Same as missing_required_secrets, but for `recommended` tier."""
    out: list[tuple[str, SecretDecl]] = []
    for tool in manifest.tools:
        for s in tool.secrets:
            if s.criticality == "recommended" and not env_values.get(s.name):
                out.append((tool.name, s))
    return out


# ---------------------------------------------------------------------------
# D2 — Supersedes chain + extension composition (Q1 hybrid lifecycle)
# ---------------------------------------------------------------------------


def extension_filename(mission_id: str) -> str:
    """Canonical filename for a per-mission extension manifest."""
    return f"extension_{mission_id}.json"


def extension_path(
    project_id: str, mission_id: str, *, root: Optional[Path] = None
) -> Path:
    return workspace_dir(project_id, root=root) / extension_filename(mission_id)


def save_extension_manifest(
    extension: ToolManifest,
    mission_id: str,
    *,
    root: Optional[Path] = None,
) -> Path:
    """Write a per-mission extension manifest.

    Each extension declares `supersedes_baseline_hash` so reproduction
    can recover the exact baseline that was in effect when the
    extension was ratified.

    Raises ValueError if `extension.manifest_type != "extension"` —
    extensions and baselines are distinct artifacts and the IO helpers
    enforce that at write time.
    """
    if extension.manifest_type != "extension":
        raise ValueError(
            f"save_extension_manifest: manifest_type must be 'extension', "
            f"got {extension.manifest_type!r}"
        )
    if not extension.supersedes_baseline_hash:
        raise ValueError(
            "save_extension_manifest: supersedes_baseline_hash is required "
            "so reproduction can recover the baseline the extension layers on"
        )
    if not extension.created_at:
        extension.created_at = _now_iso()
    ensure_workspace_dir(extension.project_id, root=root)
    path = extension_path(extension.project_id, mission_id, root=root)
    path.write_text(extension.to_json(), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def load_extension_manifest(
    project_id: str, mission_id: str, *, root: Optional[Path] = None
) -> Optional[ToolManifest]:
    """Load a per-mission extension manifest, returning None if absent."""
    path = extension_path(project_id, mission_id, root=root)
    if not path.is_file():
        return None
    return ToolManifest.from_json(path.read_text(encoding="utf-8"))


def list_extensions(
    project_id: str, *, root: Optional[Path] = None
) -> dict[str, ToolManifest]:
    """Discover every per-mission extension manifest in the workspace.

    Returns `{mission_id: ToolManifest}`. Useful for audit views like
    "what tools were added mid-project, and for which missions?".
    """
    out: dict[str, ToolManifest] = {}
    d = workspace_dir(project_id, root=root)
    if not d.is_dir():
        return out
    prefix = "extension_"
    suffix = ".json"
    for f in d.iterdir():
        name = f.name
        if not (name.startswith(prefix) and name.endswith(suffix)):
            continue
        mission_id = name[len(prefix) : -len(suffix)]
        try:
            ext = ToolManifest.from_json(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            continue  # malformed extension — skip silently
        out[mission_id] = ext
    return out


def compose_effective_manifest(
    project_id: str,
    *,
    mission_id: Optional[str] = None,
    root: Optional[Path] = None,
) -> Optional[ToolManifest]:
    """Compose the effective tool set for a mission (or project baseline).

    Algorithm:
      1. Load the baseline manifest. If missing → return None (caller
         decides whether to escalate or kick off onboarding).
      2. If `mission_id` is given, load that mission's extension
         manifest if present.
      3. Merge: extension tools are *additive* — any tool name in the
         extension that ALSO exists in the baseline overrides the
         baseline entry; any tool name unique to the extension is
         appended. Baseline-only tools pass through.
      4. Return a synthesized ToolManifest with `manifest_type="extension"`
         when mission-scoped, else the bare baseline.

    The returned manifest is NOT written to disk — it's a runtime
    composition used by the runner's MCP-config builder. The on-disk
    baseline + extension files remain the canonical sources.

    `supersedes_baseline_hash` is copied through so audit/reproduction
    tooling can trace back to the exact baseline.
    """
    baseline = load_manifest(project_id, root=root)
    if baseline is None:
        return None
    if mission_id is None:
        return baseline
    extension = load_extension_manifest(project_id, mission_id, root=root)
    if extension is None:
        return baseline

    # Merge: extension tools override or extend the baseline list.
    by_name: dict[str, ToolDecl] = {t.name: t for t in baseline.tools}
    for t in extension.tools:
        by_name[t.name] = t
    merged_tools = list(by_name.values())

    # Synthesize the effective manifest. The composition is workflow
    # config, not on-disk truth, so we deliberately don't compute a
    # hash here (the audit chain references baseline + extension hashes
    # separately).
    return ToolManifest(
        project_id=project_id,
        schema_version=baseline.schema_version,
        manifest_type="extension",
        supersedes_baseline_hash=baseline.compute_hash(),
        supersedes_extension_hash=extension.compute_hash(),
        topic=baseline.topic,
        tools=merged_tools,
        created_at=extension.created_at or baseline.created_at,
        audit_journal_id=extension.audit_journal_id or baseline.audit_journal_id,
    )
