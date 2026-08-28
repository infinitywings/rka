"""Stable test-ownership manifest for the split RKA ecosystem.

Core is the default profile.  The exact paths below preserve frozen contracts
that still live in this repository while their owning products are separate or
shelved.  Path-based ownership is deliberate: keyword matching would wrongly
exclude Core compatibility tests that happen to mention manuscripts or LLMs.
"""

from __future__ import annotations


WRITER_TEST_PATHS = frozenset(
    {
        "eval-harness/v3/tests/test_writing_metrics.py",
        "tests/test_api/test_change_tracking_routes.py",
        "tests/test_api/test_manuscript_planning.py",
        "tests/test_api/test_manuscript_sources.py",
        "tests/test_api/test_native_manuscripts.py",
        "tests/test_api/test_semantic_patches.py",
        "tests/test_db/test_migration_032.py",
        "tests/test_db/test_migration_033.py",
        "tests/test_db/test_migration_034.py",
        "tests/test_db/test_migration_036.py",
        "tests/test_db/test_migration_038.py",
        "tests/test_db/test_migration_039.py",
        "tests/test_db/test_migration_043.py",
        "tests/test_db/test_migration_044.py",
        "tests/test_db/test_migration_047.py",
        "tests/test_db/test_migration_048.py",
        "tests/test_db/test_migration_049.py",
        "tests/test_db/test_migration_050.py",
        "tests/test_manuscript_native_models.py",
        "tests/test_mcp/test_manuscript_planning.py",
        "tests/test_mcp/test_native_manuscript_operations.py",
        "tests/test_services/test_evaluation_contract.py",
        "tests/test_services/test_knowledge_pack_native.py",
        "tests/test_services/test_knowledge_pack_planning.py",
        "tests/test_services/test_knowledge_pack_semantic_patch.py",
        "tests/test_services/test_manuscript_planning.py",
        "tests/test_services/test_manuscript_project_scope.py",
        "tests/test_services/test_manuscript_source.py",
        "tests/test_services/test_native_manuscript_service.py",
        "tests/test_services/test_outline.py",
        "tests/test_services/test_semantic_patch.py",
    }
)


AGENTIC_TEST_PATHS = frozenset(
    {
        "tests/test_api/test_app_lifespan.py",
        "tests/test_api/test_llm_health.py",
        "tests/test_infra/test_llm_call_is_bounded.py",
        "tests/test_services/test_llm_failure_is_visible.py",
        "tests/test_services/test_summary_qa.py",
    }
)


def owner_for_test(path: str) -> str:
    """Return the explicit downstream owner, or ``core`` by default."""
    normalized = path.replace("\\", "/")
    if normalized in WRITER_TEST_PATHS:
        return "writer"
    if normalized in AGENTIC_TEST_PATHS:
        return "agentic"
    return "core"
