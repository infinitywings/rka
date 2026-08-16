"""Auditable propose/preview/apply workflow for workbench semantic edits."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic import TypeAdapter

from rka.infra.ids import generate_id
from rka.models.manuscript_native import ManuscriptUpdate
from rka.models.semantic_patch import (
    ContextManifestCreate,
    ManuscriptMetadataUpdateOperation,
    PlanningArtifactUpsertOperation,
    SemanticPatchOperation,
    SemanticPatchProposalCreate,
    SemanticPatchProposalTransition,
)
from rka.services.base import BaseService, _now
from rka.services.entity_resolver import EntityResolverService
from rka.services.manuscript_native import NativeManuscriptService
from rka.services.planning import ManuscriptPlanningService


SEMANTIC_PATCH_SCHEMA_VERSION = "rka.semantic-patch/v1"
CONTEXT_MANIFEST_SCHEMA_VERSION = "rka.context-manifest/v1"
_OPERATION_ADAPTER = TypeAdapter(SemanticPatchOperation)
_PROPOSAL_STATUSES = {
    "proposed", "applied", "rejected", "conflicted", "superseded", "expired"
}


class SemanticPatchNotFoundError(ValueError):
    """A proposal or manifest is absent from the selected project."""


class SemanticPatchConflictError(ValueError):
    """A proposal or target optimistic guard no longer matches."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _loads(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    return json.loads(value) if isinstance(value, str) else value


def _semantic_diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    """Return deterministic leaf changes instead of an executable JSON Patch."""
    if before == after:
        return []
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}/{key}"
            if key not in before:
                changes.append({"path": child, "change": "added", "before": None, "after": after[key]})
            elif key not in after:
                changes.append({"path": child, "change": "removed", "before": before[key], "after": None})
            else:
                changes.extend(_semantic_diff(before[key], after[key], child))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        before_items = {_semantic_list_key(item): item for item in before}
        after_items = {_semantic_list_key(item): item for item in after}
        if (
            None not in before_items
            and None not in after_items
            and len(before_items) == len(before)
            and len(after_items) == len(after)
        ):
            changes = []
            for key in sorted(set(before_items) | set(after_items)):
                child = f"{path}/{_json_pointer_segment(str(key))}"
                if key not in before_items:
                    changes.append(
                        {
                            "path": child,
                            "change": "added",
                            "before": None,
                            "after": after_items[key],
                        }
                    )
                elif key not in after_items:
                    changes.append(
                        {
                            "path": child,
                            "change": "removed",
                            "before": before_items[key],
                            "after": None,
                        }
                    )
                else:
                    changes.extend(
                        _semantic_diff(before_items[key], after_items[key], child)
                    )
            return changes
    return [{"path": path or "/", "change": "changed", "before": before, "after": after}]


def _semantic_list_key(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    for field in ("local_key", "claim_id", "unit_id"):
        key = value.get(field)
        if isinstance(key, str) and key:
            return key
    return None


def _json_pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


class SemanticPatchService(BaseService):
    """Project-scoped immutable proposal ledger and explicit apply gate."""

    async def create_context_manifest(self, data: ContextManifestCreate) -> dict[str, Any]:
        manifest_id = generate_id("semantic_patch_context_manifest")
        async with self.db.transaction():
            # Capture disclosure context and target bases in the same write
            # snapshot that persists the manifest. A concurrent writer cannot
            # make the recorded fingerprints stale between read and insert.
            selected = [item.model_dump(exclude_none=True) for item in data.selected_context]
            ids = [item.entity_id for item in data.selected_context]
            resolved = await EntityResolverService(self.db).resolve_entities(
                self.project_id,
                ids,
                include_sources=data.include_source_closure,
                include_edges=False,
            )
            unresolved = [
                entity_id
                for entity_id in ids
                if not resolved["entities"].get(entity_id, {}).get("found")
            ]
            if unresolved:
                raise ValueError(
                    "context selection contains unresolved or foreign entities: "
                    + ", ".join(sorted(unresolved))
                )
            target_bases = [
                await self._manifest_target_base(target.target_type, target.target_id)
                for target in data.targets
            ]
            payload = {
                "schema_version": CONTEXT_MANIFEST_SCHEMA_VERSION,
                "project_id": self.project_id,
                "origin": data.origin,
                "provider": data.provider,
                "model": data.model,
                "boundary": data.boundary,
                "selected_context": selected,
                "resolved_context": resolved,
                "target_bases": target_bases,
                "constraints": data.constraints,
                "omissions": data.omissions,
                "truncation_notes": data.truncation_notes,
            }
            manifest_hash = _hash(payload)
            await self.db.execute(
                """INSERT INTO semantic_patch_context_manifests
                   (id, project_id, origin, provider, model, boundary,
                    selected_context, resolved_context, target_bases,
                    constraints, omissions, truncation_notes, manifest_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    manifest_id,
                    self.project_id,
                    data.origin,
                    data.provider,
                    data.model,
                    data.boundary,
                    _canonical_json(selected),
                    _canonical_json(resolved),
                    _canonical_json(target_bases),
                    _canonical_json(data.constraints),
                    _canonical_json(data.omissions),
                    _canonical_json(data.truncation_notes),
                    manifest_hash,
                ],
            )
            if data.origin == "host_agent":
                await self._insert_provider_event(
                    call_id=generate_id("semantic_patch_provider_call"),
                    manifest_id=manifest_id,
                    event="started",
                    provider=data.provider,
                    model=data.model,
                    boundary=data.boundary,
                    details={"transport": "host_conversation"},
                )
        return await self.get_context_manifest(manifest_id)

    async def get_context_manifest(self, manifest_id: str) -> dict[str, Any]:
        row = await self.db.fetchone(
            "SELECT * FROM semantic_patch_context_manifests WHERE id = ? AND project_id = ?",
            [manifest_id, self.project_id],
        )
        if row is None:
            raise SemanticPatchNotFoundError(f"context manifest {manifest_id!r} not found")
        result = dict(row)
        for field, fallback in (
            ("selected_context", []),
            ("resolved_context", {}),
            ("target_bases", []),
            ("constraints", []),
            ("omissions", []),
            ("truncation_notes", []),
        ):
            result[field] = _loads(result.get(field), fallback)
        events = await self.db.fetchall(
            """SELECT * FROM semantic_patch_provider_events
               WHERE context_manifest_id = ? AND project_id = ?
               ORDER BY created_at, rowid""",
            [manifest_id, self.project_id],
        )
        result["provider_events"] = []
        for event in events:
            item = dict(event)
            item["details"] = _loads(item.get("details"), {})
            result["provider_events"].append(item)
        result["schema_version"] = CONTEXT_MANIFEST_SCHEMA_VERSION
        return result

    async def create_proposal(self, data: SemanticPatchProposalCreate) -> dict[str, Any]:
        operations = []
        for operation in data.operations:
            serialized = operation.model_dump(mode="json", exclude_unset=True)
            # Pydantic omits a defaulted discriminator when callers construct a
            # typed operation object instead of validating a raw dictionary.
            # Persist it unconditionally so every proposal can be parsed later.
            serialized["operation"] = operation.operation
            operations.append(serialized)
        proposal_id = generate_id("semantic_patch_proposal")
        async with self.db.transaction():
            # Preview and insert share one BEGIN IMMEDIATE snapshot, so the
            # optimistic bases cannot drift while the proposal is being made.
            target_bases: list[dict[str, Any]] = []
            diffs: list[dict[str, Any]] = []
            findings: list[dict[str, Any]] = []
            for index, operation in enumerate(data.operations):
                base, before, after, operation_findings = await self._preview_operation(operation)
                target_bases.append(base)
                diffs.append(
                    {
                        "operation_index": index,
                        "operation": operation.operation,
                        "target": base["target"],
                        "changes": _semantic_diff(before, after),
                    }
                )
                findings.extend(operation_findings)
            if not any(item["changes"] for item in diffs):
                raise ValueError("proposal has no semantic changes")

            manifest_id = None
            provider_call_id = None
            if data.origin != "human":
                manifest = await self.get_context_manifest(str(data.context_manifest_id))
                if (
                    manifest["origin"] != data.origin
                    or manifest["provider"] != data.provider
                    or manifest["model"] != data.model
                    or manifest["boundary"] != data.boundary
                ):
                    raise ValueError("proposal provider boundary does not match its context manifest")
                self._validate_ai_manifest_scope(
                    manifest=manifest,
                    operations=data.operations,
                    target_bases=target_bases,
                )
                manifest_id = manifest["id"]
                provider_call_id = await self._pending_provider_call(manifest_id)
                if provider_call_id is None:
                    raise SemanticPatchConflictError(
                        "AI context manifest has no pending provider call"
                    )

            if data.supersedes_proposal_id:
                previous = await self._require_proposal_row(data.supersedes_proposal_id)
                if previous["status"] not in {"proposed", "conflicted"}:
                    raise SemanticPatchConflictError(
                        "only proposed or conflicted proposals may be superseded"
                    )
                previous_targets = self._base_aggregate_targets(
                    _loads(previous["target_bases"], [])
                )
                if previous_targets != self._base_aggregate_targets(target_bases):
                    raise ValueError(
                        "a superseding proposal must address the same mutable aggregates"
                    )
                await self._transition_row(
                    previous,
                    status="superseded",
                    actor=data.created_by,
                    reason=f"Superseded by {proposal_id}: {data.reason}",
                    details={"superseded_by": proposal_id},
                )
            await self.db.execute(
                """INSERT INTO semantic_patch_proposals
                   (id, project_id, origin, intent, reason, created_by,
                    operations, target_bases, semantic_diff, validation_findings,
                    context_manifest_id, provider, model, boundary,
                    supersedes_proposal_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    proposal_id,
                    self.project_id,
                    data.origin,
                    data.intent,
                    data.reason,
                    data.created_by,
                    _canonical_json(operations),
                    _canonical_json(target_bases),
                    _canonical_json(diffs),
                    _canonical_json(findings),
                    manifest_id,
                    data.provider,
                    data.model,
                    data.boundary,
                    data.supersedes_proposal_id,
                ],
            )
            await self._insert_event(
                proposal_id,
                revision=1,
                action="proposed",
                actor=data.created_by,
                reason=data.reason,
                details={"operation_count": len(operations), "finding_count": len(findings)},
            )
            if provider_call_id:
                await self._insert_provider_event(
                    call_id=provider_call_id,
                    manifest_id=str(manifest_id),
                    event="succeeded",
                    provider=str(data.provider),
                    model=str(data.model),
                    boundary=data.boundary,
                    details={"proposal_id": proposal_id},
                )
        return await self.get_proposal(proposal_id)

    async def list_proposals(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if status is not None and status not in _PROPOSAL_STATUSES:
            raise ValueError("invalid semantic patch proposal status")
        sql = "SELECT id FROM semantic_patch_proposals WHERE project_id = ?"
        params: list[Any] = [self.project_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = await self.db.fetchall(sql, params)
        return [await self.get_proposal(str(row["id"])) for row in rows]

    async def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        row = await self._require_proposal_row(proposal_id)
        result = dict(row)
        for field in ("operations", "target_bases", "semantic_diff", "validation_findings"):
            result[field] = _loads(result.get(field), [])
        events = await self.db.fetchall(
            """SELECT * FROM semantic_patch_proposal_events
               WHERE proposal_id = ? AND project_id = ? ORDER BY proposal_revision""",
            [proposal_id, self.project_id],
        )
        result["events"] = []
        for event in events:
            item = dict(event)
            item["details"] = _loads(item.get("details"), {})
            result["events"].append(item)
        result["context_manifest"] = (
            await self.get_context_manifest(str(result["context_manifest_id"]))
            if result.get("context_manifest_id")
            else None
        )
        result["schema_version"] = SEMANTIC_PATCH_SCHEMA_VERSION
        return result

    async def apply_proposal(
        self,
        proposal_id: str,
        data: SemanticPatchProposalTransition,
    ) -> dict[str, Any]:
        stale = False
        async with self.db.transaction():
            row = await self._require_proposal_row(proposal_id)
            self._assert_open(row, data.expected_revision)
            operations = self._parse_operations(row["operations"])
            stored_bases = _loads(row["target_bases"], [])
            current_bases = [
                await self._current_operation_base(operation) for operation in operations
            ]
            if current_bases != stored_bases:
                await self._transition_row(
                    row,
                    status="conflicted",
                    actor=data.actor,
                    reason=data.reason,
                    details={"expected_bases": stored_bases, "current_bases": current_bases},
                )
                stale = True
            else:
                results = []
                for operation in operations:
                    results.append(await self._apply_operation(operation, data))
                await self._transition_row(
                    row,
                    status="applied",
                    actor=data.actor,
                    reason=data.reason,
                    details={"results": results},
                )
                await ManuscriptPlanningService(
                    self.db, project_id=self.project_id
                ).record_contribution_application(
                    proposal_id,
                    actor=data.actor,
                    reason=data.reason,
                )
        # Raise only after committing the conflict transition. Raising inside
        # the transaction would roll back the evidence that explains staleness.
        if stale:
            raise SemanticPatchConflictError(
                "proposal base is stale; both versions were preserved in the conflict event"
            )
        return await self.get_proposal(proposal_id)

    async def reject_proposal(
        self,
        proposal_id: str,
        data: SemanticPatchProposalTransition,
    ) -> dict[str, Any]:
        async with self.db.transaction():
            row = await self._require_proposal_row(proposal_id)
            self._assert_open(row, data.expected_revision)
            await self._transition_row(
                row,
                status="rejected",
                actor=data.actor,
                reason=data.reason,
                details={},
            )
        return await self.get_proposal(proposal_id)

    async def record_provider_event(
        self,
        *,
        call_id: str,
        manifest_id: str,
        event: str,
        provider: str,
        model: str,
        boundary: str,
        details: Mapping[str, Any] | None = None,
    ) -> str:
        if event not in {"started", "succeeded", "failed"}:
            raise ValueError("invalid provider event")
        async with self.db.transaction():
            manifest = await self.get_context_manifest(manifest_id)
            if (
                manifest["provider"] != provider
                or manifest["model"] != model
                or manifest["boundary"] != boundary
            ):
                raise ValueError("provider event boundary does not match its context manifest")
            return await self._insert_provider_event(
                call_id=call_id,
                manifest_id=manifest_id,
                event=event,
                provider=provider,
                model=model,
                boundary=boundary,
                details=dict(details or {}),
            )

    async def _pending_provider_call(self, manifest_id: str) -> str | None:
        row = await self.db.fetchone(
            """SELECT started.call_id
               FROM semantic_patch_provider_events AS started
               WHERE started.project_id = ? AND started.context_manifest_id = ?
                 AND started.event = 'started'
                 AND NOT EXISTS (
                     SELECT 1 FROM semantic_patch_provider_events AS terminal
                     WHERE terminal.project_id = started.project_id
                       AND terminal.call_id = started.call_id
                       AND terminal.event IN ('succeeded', 'failed')
                 )
               ORDER BY started.created_at DESC, started.rowid DESC
               LIMIT 1""",
            [self.project_id, manifest_id],
        )
        return str(row["call_id"]) if row else None

    async def _insert_provider_event(
        self,
        *,
        call_id: str,
        manifest_id: str,
        event: str,
        provider: str,
        model: str,
        boundary: str,
        details: Mapping[str, Any],
    ) -> str:
        existing = await self.db.fetchall(
            """SELECT event, context_manifest_id, provider, model, boundary
               FROM semantic_patch_provider_events
               WHERE project_id = ? AND call_id = ?
               ORDER BY created_at, rowid""",
            [self.project_id, call_id],
        )
        if event == "started":
            if existing:
                raise SemanticPatchConflictError("provider call already started")
        else:
            if not existing or existing[0]["event"] != "started":
                raise SemanticPatchConflictError(
                    "provider call must record started before a terminal event"
                )
            if any(row["event"] in {"succeeded", "failed"} for row in existing):
                raise SemanticPatchConflictError("provider call already has a terminal event")
            if any(
                row["context_manifest_id"] != manifest_id
                or row["provider"] != provider
                or row["model"] != model
                or row["boundary"] != boundary
                for row in existing
            ):
                raise ValueError("provider call events must share one manifest boundary")
        event_id = generate_id("semantic_patch_provider_event")
        await self.db.execute(
            """INSERT INTO semantic_patch_provider_events
               (id, call_id, project_id, context_manifest_id, event,
                provider, model, boundary, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                event_id,
                call_id,
                self.project_id,
                manifest_id,
                event,
                provider,
                model,
                boundary,
                _canonical_json(dict(details)),
            ],
        )
        return event_id

    async def _preview_operation(
        self, operation: SemanticPatchOperation
    ) -> tuple[dict[str, Any], Any, Any, list[dict[str, Any]]]:
        if isinstance(operation, PlanningArtifactUpsertOperation):
            planning = ManuscriptPlanningService(self.db, project_id=self.project_id)
            context = await planning.get_branch(operation.branch_id)
            branch = context["branch"]
            if int(branch["revision"]) != operation.append.expected_branch_revision:
                raise SemanticPatchConflictError("planning branch revision is already stale")
            artifact = next(
                (
                    item
                    for item in context["effective_artifacts"]
                    if item["stage_type"] == operation.append.stage_type
                    and item["local_key"] == operation.append.local_key
                ),
                None,
            )
            previous_version = int(artifact["version"]["version"]) if artifact else 0
            if previous_version != operation.append.expected_previous_version:
                raise SemanticPatchConflictError("planning artifact version is already stale")
            stored_before = artifact["version"] if artifact else None
            before = self._planning_semantic_snapshot(stored_before)
            after = self._planning_semantic_snapshot(
                operation.append.model_dump(mode="json")
            )
            base = {
                "target": {"type": "planning_artifact", "branch_id": operation.branch_id,
                           "stage_type": operation.append.stage_type,
                           "local_key": operation.append.local_key},
                "branch_revision": int(branch["revision"]),
                "artifact_version": previous_version,
                "fingerprint": _hash(stored_before),
            }
            return base, before, after, []

        manuscript = NativeManuscriptService(self.db, project_id=self.project_id)
        current = await manuscript.get(operation.manuscript_id)
        if current is None:
            raise ValueError(f"manuscript {operation.manuscript_id!r} not found")
        if int(current.revision) != operation.expected_revision:
            raise SemanticPatchConflictError("manuscript revision is already stale")
        if isinstance(operation, ManuscriptMetadataUpdateOperation):
            after_fields = {
                key: getattr(operation, key)
                for key in ("title", "abstract", "venue", "workspace_ref")
                if key in operation.model_fields_set
            }
            validated = ManuscriptUpdate.model_validate(
                {"expected_revision": operation.expected_revision, **after_fields}
            )
            after_fields = {key: getattr(validated, key) for key in after_fields}
            before = {key: getattr(current, key) for key in after_fields}
            after = after_fields
            fingerprint = _hash(before)
            findings: list[dict[str, Any]] = []
        else:
            claims = manuscript._normalize_claim_specs(operation.spine.get("claims"))
            units = manuscript._normalize_unit_specs(operation.spine.get("units"))
            manuscript._assert_unique_local_keys(claims, "claim")
            manuscript._assert_unique_local_keys(units, "unit")
            await self._validate_spine_references(claims, units)
            exported = await manuscript.export_spine_projection(operation.manuscript_id)
            before = {
                "claims": manuscript._normalize_claim_specs(exported.get("claims")),
                "units": manuscript._normalize_unit_specs(exported.get("units")),
            }
            after = {"claims": claims, "units": units}
            fingerprint = _hash(exported)
            findings = self._spine_findings(exported, after)
        base = {
            "target": {"type": operation.operation, "manuscript_id": operation.manuscript_id},
            "manuscript_revision": int(current.revision),
            "fingerprint": fingerprint,
        }
        return base, before, after, findings

    @staticmethod
    def _planning_semantic_snapshot(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        fields = (
            "lifecycle",
            "summary",
            "payload",
            "origin",
            "provider",
            "model",
            "context_hash",
            "unresolved_items",
            "readiness_state",
            "readiness_missing",
            "readiness_notes",
            "promotion_target_type",
            "promotion_target_id",
            "created_by",
            "reason",
        )
        bindings = []
        for binding in value.get("evidence_bindings") or []:
            bindings.append(
                {
                    key: binding.get(key)
                    for key in (
                        "entity_type",
                        "entity_id",
                        "role",
                        "source_version",
                        "locator_kind",
                        "locator_value",
                        "locator_start",
                        "locator_end",
                        "content_hash",
                        "ordinal",
                        "note",
                    )
                }
            )
        return {
            **{field: value.get(field) for field in fields},
            "evidence_bindings": bindings,
        }

    @staticmethod
    def _operation_aggregate_target(
        operation: SemanticPatchOperation,
    ) -> tuple[str, str]:
        if isinstance(operation, PlanningArtifactUpsertOperation):
            return "planning_branch", operation.branch_id
        return "manuscript", operation.manuscript_id

    @classmethod
    def _base_aggregate_targets(cls, bases: list[dict[str, Any]]) -> set[tuple[str, str]]:
        targets: set[tuple[str, str]] = set()
        for base in bases:
            target = base["target"]
            if target["type"] == "planning_artifact":
                targets.add(("planning_branch", str(target["branch_id"])))
            else:
                targets.add(("manuscript", str(target["manuscript_id"])))
        return targets

    def _validate_ai_manifest_scope(
        self,
        *,
        manifest: Mapping[str, Any],
        operations: list[SemanticPatchOperation],
        target_bases: list[dict[str, Any]],
    ) -> None:
        manifest_targets = {
            (str(item["target"]["type"]), str(item["target"]["id"])): item
            for item in manifest["target_bases"]
        }
        disclosed_ids = set(manifest["resolved_context"].get("entities", {}))
        for item in manifest["target_bases"]:
            disclosed_ids.update(self._collect_entity_ids(item.get("snapshot")))

        for operation, base in zip(operations, target_bases, strict=True):
            aggregate = self._operation_aggregate_target(operation)
            manifest_base = manifest_targets.get(aggregate)
            if manifest_base is None:
                raise ValueError(
                    f"AI proposal target {aggregate[0]} {aggregate[1]!r} "
                    "was not disclosed in its context manifest"
                )
            current_revision = (
                base["branch_revision"]
                if aggregate[0] == "planning_branch"
                else base["manuscript_revision"]
            )
            if int(manifest_base["revision"]) != int(current_revision):
                raise SemanticPatchConflictError(
                    f"AI proposal target {aggregate[0]} {aggregate[1]!r} changed "
                    "after its context manifest was captured"
                )

            undisclosed = sorted(self._operation_entity_references(operation) - disclosed_ids)
            if undisclosed:
                raise ValueError(
                    "AI proposal references entities absent from its context manifest: "
                    + ", ".join(undisclosed)
                )

    @staticmethod
    def _collect_entity_ids(value: Any) -> set[str]:
        ids: set[str] = set()
        if isinstance(value, Mapping):
            for key, item in value.items():
                if key in {
                    "id",
                    "entity_id",
                    "evidence_claim_id",
                    "promotion_target_id",
                } and isinstance(item, str):
                    ids.add(item)
                ids.update(SemanticPatchService._collect_entity_ids(item))
        elif isinstance(value, list):
            for item in value:
                ids.update(SemanticPatchService._collect_entity_ids(item))
        return ids

    @staticmethod
    def _operation_entity_references(operation: SemanticPatchOperation) -> set[str]:
        if isinstance(operation, PlanningArtifactUpsertOperation):
            refs = {binding.entity_id for binding in operation.append.evidence_bindings}
            if operation.append.promotion_target_id:
                refs.add(operation.append.promotion_target_id)
            return refs
        if isinstance(operation, ManuscriptMetadataUpdateOperation):
            return set()
        refs: set[str] = set()
        for item in [
            *(operation.spine.get("claims") or []),
            *(operation.spine.get("units") or []),
        ]:
            evidence = item.get("evidence") or {}
            for field, legacy in (
                ("support", "evidence_ids"),
                ("qualifier", "qualifier_ids"),
                ("counterevidence", "counterevidence_ids"),
            ):
                refs.update(evidence.get(field, item.get(legacy, [])) or [])
        return refs

    async def _validate_spine_references(
        self, claims: list[dict[str, Any]], units: list[dict[str, Any]]
    ) -> None:
        claim_ids = sorted(
            {
                entity_id
                for item in [*claims, *units]
                for entity_id in (
                    item["evidence"]["support"]
                    + item["evidence"]["qualifier"]
                    + item["evidence"]["counterevidence"]
                )
            }
        )
        if not claim_ids:
            return
        packet = await EntityResolverService(self.db).resolve_entities(self.project_id, claim_ids)
        unresolved = [entity_id for entity_id in claim_ids if not packet["entities"][entity_id]["found"]]
        if unresolved:
            raise ValueError("spine references unavailable evidence claims: " + ", ".join(unresolved))

    @staticmethod
    def _spine_findings(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
        old = {item["claim_id"]: item for item in before.get("claims", [])}
        new = {item["local_key"]: item for item in after.get("claims", [])}
        findings: list[dict[str, Any]] = []
        for key in sorted(set(old) & set(new)):
            left, right = old[key], new[key]
            checks = (
                ("qualifier_ids", "qualifier", "QUALIFIER_REMOVED"),
                ("counterevidence_ids", "counterevidence", "COUNTEREVIDENCE_REMOVED"),
            )
            for old_field, new_field, code in checks:
                removed = sorted(set(left.get(old_field) or []) - set(right["evidence"][new_field]))
                if removed:
                    findings.append({
                        "severity": "warning", "code": code,
                        "message": f"claim {key} removes {len(removed)} {new_field} binding(s)",
                        "claim_key": key, "entity_ids": removed,
                    })
            removed_wording = sorted(
                set(left.get("prohibited_wording") or []) - set(right["prohibited_wording"])
            )
            if removed_wording:
                findings.append({
                    "severity": "warning", "code": "PROHIBITED_WORDING_REMOVED",
                    "message": f"claim {key} removes wording boundaries",
                    "claim_key": key, "removed": removed_wording,
                })
            if left.get("allowed_wording") != right.get("allowed_wording"):
                findings.append({
                    "severity": "warning", "code": "ALLOWED_WORDING_CHANGED",
                    "message": f"claim {key} changes its allowed-wording boundary",
                    "claim_key": key,
                })
            if left.get("ratified_by") and left.get("text") != right.get("exact_wording"):
                findings.append({
                    "severity": "warning", "code": "RATIFIED_WORDING_CHANGED",
                    "message": (
                        f"claim {key} has ratified wording; apply appends unratified wording "
                        "and does not overwrite the ratification"
                    ),
                    "claim_key": key, "decision_id": left["ratified_by"],
                })
        return findings

    async def _current_operation_base(self, operation: SemanticPatchOperation) -> dict[str, Any]:
        if isinstance(operation, PlanningArtifactUpsertOperation):
            planning = ManuscriptPlanningService(self.db, project_id=self.project_id)
            context = await planning.get_branch(operation.branch_id)
            artifact = next(
                (item for item in context["effective_artifacts"]
                 if item["stage_type"] == operation.append.stage_type
                 and item["local_key"] == operation.append.local_key),
                None,
            )
            before = artifact["version"] if artifact else None
            return {
                "target": {"type": "planning_artifact", "branch_id": operation.branch_id,
                           "stage_type": operation.append.stage_type,
                           "local_key": operation.append.local_key},
                "branch_revision": int(context["branch"]["revision"]),
                "artifact_version": int(artifact["version"]["version"]) if artifact else 0,
                "fingerprint": _hash(before),
            }
        manuscript = NativeManuscriptService(self.db, project_id=self.project_id)
        current = await manuscript.get(operation.manuscript_id)
        if current is None:
            raise SemanticPatchConflictError("proposal target manuscript no longer exists")
        if isinstance(operation, ManuscriptMetadataUpdateOperation):
            fields = {
                key: getattr(current, key)
                for key in ("title", "abstract", "venue", "workspace_ref")
                if key in operation.model_fields_set
            }
            fingerprint = _hash(fields)
        else:
            fingerprint = _hash(await manuscript.export_spine_projection(operation.manuscript_id))
        return {
            "target": {"type": operation.operation, "manuscript_id": operation.manuscript_id},
            "manuscript_revision": int(current.revision),
            "fingerprint": fingerprint,
        }

    async def _apply_operation(
        self,
        operation: SemanticPatchOperation,
        transition: SemanticPatchProposalTransition,
    ) -> dict[str, Any]:
        if isinstance(operation, PlanningArtifactUpsertOperation):
            append = operation.append.model_copy(
                update={"created_by": transition.actor, "reason": transition.reason}
            )
            result = await ManuscriptPlanningService(
                self.db, project_id=self.project_id
            ).append_artifact_version(operation.branch_id, append)
            return {"operation": operation.operation, "branch_revision": result["branch"]["revision"]}
        manuscript = NativeManuscriptService(self.db, project_id=self.project_id)
        if isinstance(operation, ManuscriptMetadataUpdateOperation):
            fields = {
                key: getattr(operation, key)
                for key in ("title", "abstract", "venue", "workspace_ref")
                if key in operation.model_fields_set
            }
            result = await manuscript.update(
                operation.manuscript_id,
                ManuscriptUpdate.model_validate(
                    {"expected_revision": operation.expected_revision, **fields}
                ),
                actor=transition.actor,
            )
            return {"operation": operation.operation, "manuscript_revision": result.revision}
        result = await manuscript.upsert_argument_spine(
            operation.manuscript_id,
            expected_revision=operation.expected_revision,
            spine=operation.spine,
            actor=transition.actor,
        )
        return {
            "operation": operation.operation,
            "manuscript_revision": result["manuscript"]["revision"],
        }

    async def _manifest_target_base(self, target_type: str, target_id: str) -> dict[str, Any]:
        if target_type == "planning_branch":
            context = await ManuscriptPlanningService(
                self.db, project_id=self.project_id
            ).get_branch(target_id)
            return {
                "target": {"type": target_type, "id": target_id},
                "revision": int(context["branch"]["revision"]),
                "fingerprint": _hash(context),
                "snapshot": context,
            }
        context = await NativeManuscriptService(
            self.db, project_id=self.project_id
        ).get_context(target_id)
        return {
            "target": {"type": target_type, "id": target_id},
            "revision": int(context["manuscript"]["revision"]),
            "fingerprint": _hash(context),
            "snapshot": context,
        }

    @staticmethod
    def _parse_operations(value: Any) -> list[SemanticPatchOperation]:
        return [_OPERATION_ADAPTER.validate_python(item) for item in _loads(value, [])]

    async def _require_proposal_row(self, proposal_id: str) -> dict[str, Any]:
        row = await self.db.fetchone(
            "SELECT * FROM semantic_patch_proposals WHERE id = ? AND project_id = ?",
            [proposal_id, self.project_id],
        )
        if row is None:
            raise SemanticPatchNotFoundError(f"semantic patch proposal {proposal_id!r} not found")
        return dict(row)

    @staticmethod
    def _assert_open(row: Mapping[str, Any], expected_revision: int) -> None:
        if row["status"] != "proposed":
            raise SemanticPatchConflictError(f"proposal is already {row['status']!r}")
        if int(row["revision"]) != expected_revision:
            raise SemanticPatchConflictError(
                f"proposal revision conflict: expected {expected_revision}, found {row['revision']}"
            )

    async def _transition_row(
        self,
        row: Mapping[str, Any],
        *,
        status: str,
        actor: str,
        reason: str,
        details: dict[str, Any],
    ) -> None:
        revision = int(row["revision"]) + 1
        timestamp = _now()
        cursor = await self.db.execute(
            """UPDATE semantic_patch_proposals
               SET status = ?, revision = revision + 1, updated_at = ?,
                   applied_at = CASE WHEN ? = 'applied' THEN ? ELSE applied_at END,
                   closed_at = ?
               WHERE id = ? AND project_id = ? AND status = ? AND revision = ?""",
            [status, timestamp, status, timestamp, timestamp,
             row["id"], self.project_id, row["status"], row["revision"]],
        )
        if cursor.rowcount != 1:
            raise SemanticPatchConflictError("proposal changed concurrently")
        await self._insert_event(
            str(row["id"]), revision=revision, action=status,
            actor=actor, reason=reason, details=details,
        )

    async def _insert_event(
        self,
        proposal_id: str,
        *,
        revision: int,
        action: str,
        actor: str,
        reason: str,
        details: dict[str, Any],
    ) -> None:
        await self.db.execute(
            """INSERT INTO semantic_patch_proposal_events
               (id, proposal_id, project_id, proposal_revision, action, actor, reason, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [generate_id("semantic_patch_proposal_event"), proposal_id, self.project_id,
             revision, action, actor, reason, _canonical_json(details)],
        )
