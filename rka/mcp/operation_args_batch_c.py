"""DEPRECATED — v2.7.0 Phase 3 reconciliation shim.

This module previously held the Batch C (UPDATE / LIFECYCLE / SUBMIT)
typed-arg models in isolation. In Phase 3 the engineering session
collapsed all four batches (A/B/C/D) into ``rka.mcp.operation_args``
under a single canonical ``ProjectScopedArgs`` / ``UnscopedArgs``
base so the final ``ExecuteArgsUnion`` discriminator-typed union
works (Pydantic requires every branch to inherit a common base for
``Field(discriminator=...)`` to render as JSON Schema ``oneOf``).

For back-compat with any out-of-tree caller that still imports from
``rka.mcp.operation_args_batch_c``, this shim re-exports each Batch C
symbol from the canonical module. New code should import directly
from ``rka.mcp.operation_args``.
"""

from __future__ import annotations

from rka.mcp.operation_args import (
    AdvanceRqArgs,
    BulkUpdateArgs,
    EnrichDoiArgs,
    EvaluateGateArgs,
    LinkLiteratureToZoteroArgs,
    PresentDecisionArgs,
    ProcessPaperArgs,
    ProjectScopedArgs,
    RecordOutcomeArgs,
    RecordPiSelectionArgs,
    ResetSessionArgs,
    ResolveCheckpointArgs,
    SessionDigestArgs,
    SubmitCheckpointArgs,
    SubmitReportArgs,
    SupersedeDecisionArgs,
    UnscopedArgs,
    UpdateDecisionArgs,
    UpdateLiteratureArgs,
    UpdateMissionArgs,
    UpdateMissionStatusArgs,
    UpdateNoteArgs,
    UpdateStatusArgs,
    ValidateReferenceArgs,
)

__all__ = [
    "ProjectScopedArgs",
    "UnscopedArgs",
    "UpdateNoteArgs",
    "UpdateDecisionArgs",
    "UpdateLiteratureArgs",
    "UpdateMissionArgs",
    "UpdateStatusArgs",
    "UpdateMissionStatusArgs",
    "BulkUpdateArgs",
    "SupersedeDecisionArgs",
    "PresentDecisionArgs",
    "RecordPiSelectionArgs",
    "RecordOutcomeArgs",
    "EnrichDoiArgs",
    "LinkLiteratureToZoteroArgs",
    "ProcessPaperArgs",
    "ValidateReferenceArgs",
    "SubmitReportArgs",
    "AdvanceRqArgs",
    "SubmitCheckpointArgs",
    "ResolveCheckpointArgs",
    "EvaluateGateArgs",
    "ResetSessionArgs",
    "SessionDigestArgs",
]
