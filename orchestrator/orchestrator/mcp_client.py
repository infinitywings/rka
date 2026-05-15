"""MCP client wrapper.

T3-T6 nodes write against the `MCPClient` Protocol. T9 binds the real
stdio-MCP client; tests inject fakes via the same Protocol.

The 13 RKA MCP tools (canonical, current as of v2.3.5):

  1. rka_search
  2. rka_get
  3. rka_get_context
  4. rka_get_journal
  5. rka_get_research_map
  6. rka_get_mission
  7. rka_add_note
  8. rka_add_decision
  9. rka_create_mission
 10. rka_submit_checkpoint
 11. rka_submit_report
 12. rka_get_checkpoints
 13. rka_trace_provenance

Error mapping (Affordances G + E from v2.3.5):
  - KnowledgePackIntegrityError (422) → structured `CheckpointError`
  - motivated-by-explained tag suppression respected on retry

Every write call auto-injects the workflow_thread_id into `tags` (or the
relevant tag-bearing field) so the run's RKA artifacts can be recovered
via `rka_get_journal(tags=[workflow_thread_id])` — mirrors v2.3.5
Affordance F.
"""

from __future__ import annotations

from typing import Any, Protocol


class CheckpointError(Exception):
    """Raised when an MCP call needs the workflow to halt and create a checkpoint.

    Phase 1 catches this at the `escalation_router` utility node (T6) and
    creates an `rka_submit_checkpoint` of type=decision before letting the
    PI interrupt fire.
    """

    def __init__(self, reason: str, *, mcp_response: Any = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.mcp_response = mcp_response


class MCPClient(Protocol):
    """Workflow-tagged wrapper over the 13 RKA MCP tools.

    The `workflow_thread_id` attribute is set at workflow start and
    auto-injected into every write call's `tags=[...]` list.
    """

    workflow_thread_id: str

    # --- reads ---
    def rka_get_status(self) -> dict[str, Any]: ...
    def rka_get_context(
        self, topic: str | None = None, limit: int = 10
    ) -> dict[str, Any]: ...
    def rka_get_journal(
        self,
        *,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]: ...
    def rka_get_mission(self, id: str | None = None) -> dict[str, Any]: ...
    def rka_get_research_map(self) -> dict[str, Any]: ...
    def rka_get_checkpoints(
        self, status: str = "open"
    ) -> list[dict[str, Any]]: ...
    def rka_search(
        self, query: str, *, limit: int = 10
    ) -> list[dict[str, Any]]: ...
    def rka_get(self, id: str) -> dict[str, Any]: ...
    def rka_trace_provenance(self, id: str) -> dict[str, Any]: ...

    # --- writes (auto-tag workflow_thread_id) ---
    def rka_add_note(
        self,
        content: str,
        *,
        type: str = "note",
        source: str = "brain",
        related_mission: str | None = None,
        related_decisions: list[str] | None = None,
        tags: list[str] | None = None,
        confidence: str = "hypothesis",
        importance: str = "normal",
    ) -> str:
        """Returns the new journal entry ID (`jrn_…`)."""
        ...

    def rka_add_decision(
        self,
        content: str,
        *,
        related_journal: list[str],
        tags: list[str] | None = None,
    ) -> str:
        """Returns the new decision ID (`dec_…`)."""
        ...

    def rka_submit_checkpoint(
        self,
        reason: str,
        *,
        type: str = "decision",
        related_mission: str | None = None,
    ) -> str:
        """Returns the new checkpoint ID (`chk_…`)."""
        ...

    def rka_submit_report(
        self,
        content: str,
        *,
        related_mission: str,
        summary: str | None = None,
        findings: list[str] | None = None,
        anomalies: list[str] | None = None,
        recommended_next: list[str] | None = None,
    ) -> str:
        """Returns the new report ID (`rep_…`)."""
        ...

    def rka_create_mission(
        self,
        objective: str,
        *,
        motivated_by_decision: str,
        acceptance_criteria: list[str],
    ) -> str:
        """Returns the new mission ID (`mis_…`)."""
        ...


def make_client() -> MCPClient:
    """Construct the production MCP client. Wired in T9."""
    raise NotImplementedError("mcp_client.make_client arrives in T9")
