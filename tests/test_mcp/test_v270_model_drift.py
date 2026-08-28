"""v2.7.0 Phase 3 — drift-detection lock-tests for typed-arg models.

Pins the typed-arg surface (``rka/mcp/operation_args.py``) against the
canonical sources of truth:

  - ``OPERATIONS_SCHEMA`` in ``rka/mcp/operations_schema.py`` —
    per-operation required/optional/enum lists.
  - ``rka/mcp/_enums.py`` — module-level Literal aliases. Each
    ``Annotated[Literal[...]]`` field in a typed-arg model must
    reuse one of these aliases verbatim (no inline-redefined Literal).
  - ``EXECUTE_OPERATIONS`` in ``rka/mcp/verb_dispatch.py`` — canonical
    set of execute operations the dispatcher routes.

If a future PR bumps an RKA enum or adds a write operation but forgets
to update ``operation_args.py``, these tests fail in CI before the
divergence can ship to the LLM-facing surface.

The lock-tests are intentionally tolerant of additive change: any
typed-arg model NOT in OPERATIONS_SCHEMA fails (drift); any
OPERATIONS_SCHEMA entry without a typed model fails (coverage gap);
any model whose ``operation`` Literal value or required/optional field
partition doesn't match its OPERATIONS_SCHEMA entry fails.
"""

from __future__ import annotations

import typing

import pytest
from pydantic import BaseModel

from rka.mcp import operation_args
from rka.mcp.operation_args import (
    ExecuteArgsUnion,
    QueryArgsUnion,
)
from rka.mcp.operations_schema import OPERATIONS_SCHEMA
from rka.mcp.verb_dispatch import EXECUTE_OPERATIONS


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _union_members(union: typing.Any) -> tuple[type[BaseModel], ...]:
    """Extract the per-branch model classes from ``Annotated[Union[A,B,...], Field(...)]``."""
    inner = typing.get_args(union)[0]
    return typing.get_args(inner)


def _operation_literal(model: type[BaseModel]) -> str:
    """Return the discriminator-Literal value for a typed-arg model."""
    op_field = model.model_fields["operation"]
    return typing.get_args(op_field.annotation)[0]


# ----------------------------------------------------------------------
# Coverage: every model in operation_args.py shows up in a union, and
# every union member matches OPERATIONS_SCHEMA
# ----------------------------------------------------------------------


def test_query_union_member_count_matches_schema_reads() -> None:
    """Every read op in OPERATIONS_SCHEMA must have a model in QueryArgsUnion."""
    typed_ops = {_operation_literal(m) for m in _union_members(QueryArgsUnion)}
    schema_reads = {
        op for op, entry in OPERATIONS_SCHEMA.items() if entry["tool"] == "rka_query"
    }
    assert typed_ops == schema_reads, (
        f"Drift: typed-query union vs OPERATIONS_SCHEMA reads.\n"
        f"  typed only: {typed_ops - schema_reads}\n"
        f"  schema only: {schema_reads - typed_ops}"
    )


def test_execute_union_member_count_matches_schema_writes() -> None:
    """Every write op in OPERATIONS_SCHEMA must have a model in ExecuteArgsUnion."""
    typed_ops = {_operation_literal(m) for m in _union_members(ExecuteArgsUnion)}
    schema_writes = {
        op for op, entry in OPERATIONS_SCHEMA.items() if entry["tool"] == "rka_execute"
    }
    assert typed_ops == schema_writes, (
        f"Drift: typed-execute union vs OPERATIONS_SCHEMA writes.\n"
        f"  typed only: {typed_ops - schema_writes}\n"
        f"  schema only: {schema_writes - typed_ops}"
    )


def test_execute_union_matches_EXECUTE_OPERATIONS_tuple() -> None:
    """The typed ExecuteArgsUnion must mirror the dispatcher's
    EXECUTE_OPERATIONS tuple (single source of truth on what the
    dispatcher knows how to route)."""
    typed_ops = {_operation_literal(m) for m in _union_members(ExecuteArgsUnion)}
    legacy_ops = set(EXECUTE_OPERATIONS)
    assert typed_ops == legacy_ops, (
        f"Drift: ExecuteArgsUnion vs EXECUTE_OPERATIONS.\n"
        f"  typed only: {typed_ops - legacy_ops}\n"
        f"  legacy only: {legacy_ops - typed_ops}"
    )


def test_no_model_appears_in_both_unions() -> None:
    """A model cannot be in both Query and Execute unions."""
    q = {_operation_literal(m) for m in _union_members(QueryArgsUnion)}
    e = {_operation_literal(m) for m in _union_members(ExecuteArgsUnion)}
    overlap = q & e
    assert not overlap, (
        f"Drift: {len(overlap)} model(s) in both unions: {overlap}"
    )


# ----------------------------------------------------------------------
# Per-model: discriminator + extra-forbid + required-field coverage
# ----------------------------------------------------------------------


@pytest.mark.parametrize("model", _union_members(QueryArgsUnion) + _union_members(ExecuteArgsUnion))
def test_each_model_has_discriminator_default(model: type[BaseModel]) -> None:
    """Every model must declare ``operation: Literal['<op>'] = '<op>'`` so
    FastMCP keys the discriminated union."""
    op_field = model.model_fields["operation"]
    assert op_field.default is not None, (
        f"{model.__name__}.operation must have a default value matching "
        f"its Literal[...] annotation."
    )
    # The Literal value and the default must agree.
    literal_val = typing.get_args(op_field.annotation)[0]
    assert op_field.default == literal_val, (
        f"{model.__name__}: operation default {op_field.default!r} does "
        f"not match Literal {literal_val!r}"
    )


@pytest.mark.parametrize("model", _union_members(QueryArgsUnion) + _union_members(ExecuteArgsUnion))
def test_each_model_forbids_extras(model: type[BaseModel]) -> None:
    """Every model must reject unknown kwargs (extra='forbid').

    This is the v2.7.0 pre-mortem failure mode #4 mitigation: a typo
    like ``project_jd`` (j instead of i) must NOT silently pass.
    """
    cfg = model.model_config
    assert cfg.get("extra") == "forbid", (
        f"{model.__name__}: model_config['extra'] must be 'forbid' "
        f"(got {cfg.get('extra')!r})"
    )


@pytest.mark.parametrize("model", _union_members(QueryArgsUnion) + _union_members(ExecuteArgsUnion))
def test_each_model_fields_match_operations_schema(model: type[BaseModel]) -> None:
    """Describe-schema field lists must mirror the actual typed branch."""
    operation = _operation_literal(model)
    entry = OPERATIONS_SCHEMA[operation]
    model_required = {
        name
        for name, field in model.model_fields.items()
        if name != "operation" and field.is_required()
    }
    model_optional = {
        name
        for name, field in model.model_fields.items()
        if name != "operation" and not field.is_required()
    }
    schema_required = set(entry.get("required_fields") or [])
    schema_optional = set(entry.get("optional_fields") or [])

    assert model_required == schema_required, (
        f"{operation}: required-field drift; "
        f"model-only={sorted(model_required - schema_required)}, "
        f"schema-only={sorted(schema_required - model_required)}"
    )
    assert model_optional == schema_optional, (
        f"{operation}: optional-field drift; "
        f"model-only={sorted(model_optional - schema_optional)}, "
        f"schema-only={sorted(schema_optional - model_optional)}"
    )


# ----------------------------------------------------------------------
# Enum-alias drift: each Literal field on a typed-arg model must reuse
# one of the public aliases in rka.mcp._enums.
# ----------------------------------------------------------------------


def _collect_enums_module_literals() -> dict[frozenset[str], str]:
    """Map each Literal[...] alias in rka.mcp._enums to its alias name."""
    from rka.mcp import _enums

    result: dict[frozenset[str], str] = {}
    for name in dir(_enums):
        if name.startswith("_"):
            continue
        value = getattr(_enums, name)
        args = typing.get_args(value)
        if not args:
            continue
        if all(isinstance(a, str) for a in args):
            result[frozenset(args)] = name
    return result


_ENUMS_ALIASES = _collect_enums_module_literals()


@pytest.mark.parametrize("model", _union_members(QueryArgsUnion) + _union_members(ExecuteArgsUnion))
def test_each_literal_field_uses_enums_alias(model: type[BaseModel]) -> None:
    """Any Annotated[Literal[...]] field on a typed-arg model (other than
    the discriminator) must reuse one of the public Literal aliases in
    ``rka.mcp._enums``. Inline-redefined Literal sets are forbidden so
    drift between the typed-arg surface and the orchestrator-side mirror
    stays detectable."""
    for field_name, field in model.model_fields.items():
        if field_name == "operation":
            continue
        annotation = field.annotation
        # Unwrap Optional[X] -> X
        args = typing.get_args(annotation)
        candidates = [annotation] + list(args)
        for cand in candidates:
            inner = typing.get_args(cand)
            # A Literal[...] type has only string args
            if not inner or not all(isinstance(a, str) for a in inner):
                continue
            origin = typing.get_origin(cand)
            if origin is not typing.Literal:
                continue
            literal_values = frozenset(inner)
            assert literal_values in _ENUMS_ALIASES, (
                f"{model.__name__}.{field_name}: inline Literal{list(inner)!r} "
                "is not one of the published aliases in rka.mcp._enums "
                "(drift-detection failure — add a named alias)."
            )


# ----------------------------------------------------------------------
# project_id requirement: every project-scoped model carries project_id
# as a non-defaulted required field.
# ----------------------------------------------------------------------


_UNSCOPED_OPS = {
    "list_projects",
    "capabilities",
    "health",
    "create_project",
    "reset_session",
}


@pytest.mark.parametrize("model", _union_members(QueryArgsUnion) + _union_members(ExecuteArgsUnion))
def test_scoped_models_require_project_id(model: type[BaseModel]) -> None:
    op = _operation_literal(model)
    if op in _UNSCOPED_OPS:
        # Unscoped models must NOT carry project_id (they inherit
        # UnscopedArgs).
        assert "project_id" not in model.model_fields, (
            f"{model.__name__} (op={op!r}) is unscoped but declares project_id."
        )
        return
    assert "project_id" in model.model_fields, (
        f"{model.__name__} (op={op!r}) must declare project_id (scoped op)."
    )
    field = model.model_fields["project_id"]
    assert field.is_required(), (
        f"{model.__name__}.project_id must be a required Field (no default)."
    )


# ----------------------------------------------------------------------
# Round-trip: each model's discriminator field is rendered by FastMCP
# as a JSON Schema `const` matching the operation name.
# ----------------------------------------------------------------------


@pytest.mark.parametrize("model", _union_members(QueryArgsUnion) + _union_members(ExecuteArgsUnion))
def test_each_model_emits_discriminator_const(model: type[BaseModel]) -> None:
    """The Pydantic model JSON Schema must render the discriminator
    field as ``{const: '<op>', default: '<op>', ...}`` so FastMCP's
    discriminator='operation' propertyName works at the union level."""
    schema = model.model_json_schema()
    op_prop = schema["properties"]["operation"]
    op = _operation_literal(model)
    # Pydantic 2 renders `Literal['xxx']` as {'const': 'xxx', 'enum': ['xxx'], ...}
    const_or_enum = op_prop.get("const") or (op_prop.get("enum") or [None])[0]
    assert const_or_enum == op, (
        f"{model.__name__}: discriminator JSON-schema const/enum is "
        f"{const_or_enum!r}, expected {op!r}"
    )


# ----------------------------------------------------------------------
# Cross-cutting validators: spot-check the empirical-hallucination
# guards we explicitly wired in Phase-X²' polish + v2.7.0 Phase 3.
# ----------------------------------------------------------------------


def test_record_decision_requires_non_empty_related_journal() -> None:
    """Phase-X² lesson: confidence='confirmed' was the proximate Run-5
    bug; related_journal=[] is the persistent Brain omission class."""
    from rka.mcp.operation_args import RecordDecisionArgs
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        RecordDecisionArgs(
            project_id="prj_test",
            question="Q?",
            chosen="A",
            rationale="because",
            decided_by="brain",
            kind="decision",
            related_journal=[],  # empty -> validator fires
        )


def test_record_decision_rejects_supervisor_decided_by() -> None:
    """Closes v2.7.0 pre-mortem compromise #1: enum-emit-time catch."""
    from rka.mcp.operation_args import RecordDecisionArgs
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        RecordDecisionArgs(
            project_id="prj_test",
            question="Q?",
            chosen="A",
            rationale="because",
            decided_by="SUPERVISOR",  # not in DecidedByLit
            kind="decision",
            related_journal=["jrn_1"],
        )


def test_submit_checkpoint_alias_collision_requires_description_or_content() -> None:
    """Phase-X²' lesson: the 2026-06-01 hyperscaler-auditing PA-2
    alias-collision class. One of description / content must be set."""
    from rka.mcp.operation_args import SubmitCheckpointArgs
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        SubmitCheckpointArgs(
            project_id="prj_test",
            mission_id="mis_1",
            type="clarification",
            # both description AND content omitted -> validator fires
        )
    # Either field alone is valid.
    SubmitCheckpointArgs(
        project_id="prj_test",
        mission_id="mis_1",
        type="clarification",
        description="d",
    )
    SubmitCheckpointArgs(
        project_id="prj_test",
        mission_id="mis_1",
        type="clarification",
        content="c",
    )


def test_create_mission_requires_motivated_by_decision() -> None:
    """Phase-X² hard contract: every mission has a motivating decision."""
    from rka.mcp.operation_args import CreateMissionArgs

    # Either we get a validation error, or the field is required-non-Optional.
    field = CreateMissionArgs.model_fields.get("motivated_by_decision")
    if field is not None:
        assert field.is_required(), (
            "CreateMissionArgs.motivated_by_decision must be required-non-Optional "
            "to preserve decision->mission causality."
        )


def test_record_note_source_pi_requires_verbatim_input() -> None:
    """Phase-X²' polish: source='pi' must carry verbatim PI wording."""
    from rka.mcp.operation_args import RecordNoteArgs
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        RecordNoteArgs(
            project_id="prj_test",
            content="some content",
            source="pi",
            # missing verbatim_input -> validator fires
        )
    # With verbatim_input set, OK.
    RecordNoteArgs(
        project_id="prj_test",
        content="some content",
        source="pi",
        verbatim_input="PI said this verbatim",
    )


# ----------------------------------------------------------------------
# Public-export hygiene
# ----------------------------------------------------------------------


def test_all_models_re_exported_via_public___all__() -> None:
    """Every per-batch model must be re-exported via operation_args.__all__."""
    public = set(operation_args.__all__)
    missing = []
    for model in _union_members(QueryArgsUnion) + _union_members(ExecuteArgsUnion):
        if model.__name__ not in public:
            missing.append(model.__name__)
    assert not missing, (
        f"Drift: {len(missing)} typed-arg model(s) not re-exported via "
        f"operation_args.__all__: {missing[:5]}..."
    )


# ---------------------------------------------------------------------------
# Maturity — keeping the browse index to what is actually in use
# ---------------------------------------------------------------------------


def test_preview_operations_are_hidden_from_the_browse_index():
    """`rka_describe('')` must not spend the agent's attention on dead surface.

    Measured 2026-08-23 against a five-month-old production store of 5178
    entities: manuscript units, planning branches, experiments, semantic-patch
    proposals, hooks, interpretation candidates and claim-scope versions all
    had ZERO rows. Listing ~40% unreachable operations beside the core ones is
    exactly the "too many interfaces confuse the agent" failure.
    """
    import asyncio
    import json

    from rka.mcp.operations_schema import OPERATIONS_SCHEMA, dispatch_describe

    default = json.loads(asyncio.run(dispatch_describe("")))
    full = json.loads(asyncio.run(dispatch_describe("", include_preview=True)))

    assert default["listed"] < default["total"]
    assert default["preview_hidden"] + default["deprecated_hidden"] == (
        default["total"] - default["listed"]
    )
    assert full["listed"] == len(OPERATIONS_SCHEMA)
    # the hidden set must be discoverable, not silently dropped
    assert "include_preview" in default["preview_hint"]


def test_core_research_loop_stays_stable():
    """The operations a real session uses must never fall into preview."""
    from rka.mcp.operations_schema import operation_maturity

    for op in (
        "status", "context", "search", "entity", "journal", "literature",
        "record_note", "record_decision", "record_literature",
        "create_mission", "submit_report", "submit_checkpoint",
        "research_map", "clusters", "claims", "decision_tree",
        "ego_graph", "multi_hop", "provenance", "collect_report_context",
        "belief_as_of", "staleness_impact", "changes_since", "contradictions",
    ):
        assert operation_maturity(op) == "stable", op


def test_zero_usage_subsystems_are_preview():
    from rka.mcp.operations_schema import operation_maturity

    for op in (
        "create_experiment", "experiment_runs", "record_experiment_observation",
        "create_planning_branch", "planning_branches",
        "create_semantic_patch_proposal", "semantic_patch_proposals",
        "hook_add", "hooks",
        "create_interpretation_candidate", "interpretation_candidates",
        "set_claim_scope", "claim_scope",
        "create_manuscript", "manuscript_context",
    ):
        assert operation_maturity(op) == "preview", op


def test_every_operation_is_classified():
    """No operation may sit outside the stable/preview split."""
    from rka.mcp.operations_schema import OPERATIONS_SCHEMA, operation_maturity

    for op in OPERATIONS_SCHEMA:
        assert operation_maturity(op) in {"stable", "preview"}, op


def test_explicit_deprecation_is_distinct_from_usage_maturity():
    """A compatibility deprecation must be machine-readable without
    pretending the historical usage-derived maturity axis is a contract."""
    import asyncio
    import json

    from rka.mcp.operations_schema import (
        DEPRECATED_OPERATIONS,
        dispatch_describe,
        operation_maturity,
    )

    assert set(DEPRECATED_OPERATIONS) == {"upsert_argument_spine"}
    assert operation_maturity("upsert_argument_spine") == "preview"

    exact = json.loads(asyncio.run(dispatch_describe("upsert_argument_spine")))
    assert exact["deprecated"] is True
    assert exact["deprecation"]["replacement_operations"] == [
        "prepare_semantic_patch_context",
        "create_semantic_patch_proposal",
        "apply_semantic_patch_proposal",
    ]

    default = json.loads(asyncio.run(dispatch_describe("")))
    assert "upsert_argument_spine" not in default["rka_execute"].split(", ")
    assert default["deprecated_operations"] == ["upsert_argument_spine"]
    assert default["deprecated_hidden"] == 1
    assert (
        default["listed"]
        + default["preview_hidden"]
        + default["deprecated_hidden"]
        == default["total"]
    )
