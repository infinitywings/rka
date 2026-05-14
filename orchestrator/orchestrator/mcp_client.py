"""MCP client wrapper.

Scaffold stub. T9 will implement a thin wrapper around the 13 RKA MCP tools
identified in the v2.3.5 mission spec. Every call auto-tags
`workflow_thread_id` so RKA writes are linkable back to the orchestrator run.

The 13 tools (canonical, as of v2.3.5):

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

- KnowledgePackIntegrityError (422) → surface as a structured CheckpointError
- motivated-by-explained tag suppression respected on retry
"""

from __future__ import annotations


def make_client():
    """Placeholder. Real impl arrives in T9."""
    raise NotImplementedError("mcp_client.make_client arrives in T9")
