"""Phase B background nodes — orchestrator-level credential bootstrap.

Three non-interrupt nodes that bracket the three Phase B PI interrupts
(`pi_bootstrap_intent`, `pi_bootstrap_ratify`, `pi_bootstrap_fill_ack`):

    bootstrap_propose       — load catalog, run propose_for_intent,
                              stage decisions_to_present for the
                              ratify interrupt
    bootstrap_emit_template — write orchestrator/.env.example next to
                              the live .env, with annotated slots
    bootstrap_verify        — read the filled .env, probe each
                              ratified entry, write a report

All three are pure-Python — they delegate to `orchestrator.bootstrap`
which holds the catalog/template/verify logic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator import bootstrap as B
from orchestrator.llm_client import SDKClient  # noqa: F401 (signature parity)
from orchestrator.mcp_client import MCPClient  # noqa: F401
from orchestrator.state import ResearchWorkflowState

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# B2 — bootstrap_propose
# ---------------------------------------------------------------------------


def bootstrap_propose_node(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
) -> dict:
    """Load the catalog + match the PI's intent + stage for ratification.

    Writes:
      - bootstrap_proposed_ids — id slugs from the match
      - decisions_to_present  — append a PI-renderable view block
                                 tagged `source_node='bootstrap_propose'`
    """
    intent = state.get("bootstrap_intent", "") or ""
    try:
        catalog = B.load_catalog()
    except B.BootstrapCatalogError as exc:
        return {
            "current_node": "bootstrap_propose",
            "errors": [
                {
                    "node_name": "bootstrap_propose",
                    "error_type": "bootstrap_catalog_load_failed",
                    "detail": str(exc)[:300],
                    "timestamp": _now_iso(),
                }
            ],
        }
    selected = B.propose_for_intent(intent, catalog)
    items: list[dict[str, Any]] = []
    for e in selected:
        items.append(
            {
                "source_node": "bootstrap_propose",
                "entry_id": e.id,
                "label": e.label,
                "env_var": e.env_var,
                "criticality": e.criticality,
                "group": e.group or "",
                "purpose": e.purpose,
                "signup_url": e.signup_url,
                "format_hint": e.format_hint,
            }
        )
    return {
        "current_node": "bootstrap_propose",
        "bootstrap_proposed_ids": [e.id for e in selected],
        "decisions_to_present": items,
    }


# ---------------------------------------------------------------------------
# B4 — bootstrap_emit_template
# ---------------------------------------------------------------------------


def bootstrap_emit_template_node(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    *,
    env_path: Path | None = None,
) -> dict:
    """Write `<env_path>.example` with annotated slots for the ratified subset.

    Defaults to `orchestrator/.env.example`. The live `.env` (if any) is
    read into existing_values so already-set vars get a comment marker
    "(already set in existing .env; uncomment to replace)" instead of an
    overwrite slot.

    Writes:
      - bootstrap_template_path  — absolute path of the file produced
      - decisions_to_present     — appends a summary block tagged
                                    `source_node='bootstrap_emit_template'`
                                    for the fill_ack interrupt to render
    """
    ratified_ids = state.get("bootstrap_ratified_ids", []) or []
    if not ratified_ids:
        return {
            "current_node": "bootstrap_emit_template",
            "errors": [
                {
                    "node_name": "bootstrap_emit_template",
                    "error_type": "bootstrap_no_ratified_ids",
                    "detail": "ratified_ids empty; ratify must accept before emit",
                    "timestamp": _now_iso(),
                }
            ],
        }
    try:
        catalog = B.load_catalog()
    except B.BootstrapCatalogError as exc:
        return {
            "current_node": "bootstrap_emit_template",
            "errors": [
                {
                    "node_name": "bootstrap_emit_template",
                    "error_type": "bootstrap_catalog_load_failed",
                    "detail": str(exc)[:300],
                    "timestamp": _now_iso(),
                }
            ],
        }
    chosen = [e for e in catalog if e.id in set(ratified_ids)]

    live_env_path = env_path or B.DEFAULT_ENV_PATH
    existing = B.read_env_file(live_env_path) if live_env_path.is_file() else {}
    text = B.render_env_template(chosen, existing_values=existing)

    template_path = live_env_path.with_suffix(live_env_path.suffix + ".example")
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text(text, encoding="utf-8")
    try:
        template_path.chmod(0o600)
    except OSError:
        pass  # best-effort; cross-platform safety

    items: list[dict[str, Any]] = []
    for e in chosen:
        items.append(
            {
                "source_node": "bootstrap_emit_template",
                "entry_id": e.id,
                "env_var": e.env_var,
                "criticality": e.criticality,
                "label": e.label,
                "signup_url": e.signup_url,
                "already_set_in_live_env": bool(existing.get(e.env_var)),
            }
        )
    return {
        "current_node": "bootstrap_emit_template",
        "bootstrap_template_path": str(template_path),
        "decisions_to_present": items,
    }


# ---------------------------------------------------------------------------
# B6 — bootstrap_verify
# ---------------------------------------------------------------------------


def bootstrap_verify_node(
    state: ResearchWorkflowState,
    sdk: SDKClient,
    mcp: MCPClient,
    *,
    env_path: Path | None = None,
) -> dict:
    """Read the live `.env`, probe each ratified entry, attach a report.

    The report shape (each entry):
      {
        entry_id, env_var, classification, detail
      }

    `classification` is one of: valid | rejected | missing | unreachable
    | deferred | skipped. Values are NEVER included.

    Writes:
      - bootstrap_verify_results — list[dict] for the runner to render
      - terminal_state            — "complete" iff every required entry
                                     verified as valid OR deferred;
                                     else "escalated"
    """
    ratified_ids = state.get("bootstrap_ratified_ids", []) or []
    if not ratified_ids:
        return {
            "current_node": "bootstrap_verify",
            "errors": [
                {
                    "node_name": "bootstrap_verify",
                    "error_type": "bootstrap_no_ratified_ids",
                    "detail": "ratified_ids empty; verify must follow ratify accept",
                    "timestamp": _now_iso(),
                }
            ],
        }
    try:
        catalog = B.load_catalog()
    except B.BootstrapCatalogError as exc:
        return {
            "current_node": "bootstrap_verify",
            "errors": [
                {
                    "node_name": "bootstrap_verify",
                    "error_type": "bootstrap_catalog_load_failed",
                    "detail": str(exc)[:300],
                    "timestamp": _now_iso(),
                }
            ],
        }
    chosen = [e for e in catalog if e.id in set(ratified_ids)]

    live_env_path = env_path or B.DEFAULT_ENV_PATH
    env_values = B.read_env_file(live_env_path) if live_env_path.is_file() else {}
    results = B.verify_filled(chosen, env_values)
    results_dicts = [
        {
            "entry_id": r.entry_id,
            "env_var": r.env_var,
            "classification": r.classification,
            "detail": r.detail,
        }
        for r in results
    ]

    # Determine terminal state: every `required` entry must be valid or
    # deferred for the bootstrap to be considered complete. The runner
    # decides how to surface this to the PI.
    crit_by_id = {e.id: e.criticality for e in chosen}
    failed_required = [
        r for r in results
        if crit_by_id.get(r.entry_id) == "required"
        and r.classification not in ("valid", "deferred")
    ]
    terminal = "complete" if not failed_required else "escalated"

    return {
        "current_node": "bootstrap_verify",
        "bootstrap_verify_results": results_dicts,
        "terminal_state": terminal,
    }
