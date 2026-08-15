"""Recoverable manuscript-planning branches and immutable artifact versions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from rka.infra.ids import generate_id
from rka.models.planning import (
    PlanningArtifactVersionAppend,
    PlanningBranchCreate,
    PlanningBranchTransition,
    PlanningEvidenceBindingInput,
    parse_json_field,
    validate_planning_payload,
)
from rka.services.base import BaseService, _now


PLANNING_CONTEXT_SCHEMA_VERSION = "rka.manuscript-planning/v1"
PLANNING_COMPARISON_SCHEMA_VERSION = "rka.manuscript-planning-comparison/v1"


class PlanningNotFoundError(ValueError):
    """A planning branch or artifact is absent from this project."""


class PlanningConflictError(ValueError):
    """An optimistic revision, version, or lifecycle precondition failed."""


_ENTITY_TABLES: dict[str, str] = {
    "journal": "journal",
    "literature": "literature",
    "decision": "decisions",
    "claim": "claims",
    "claim_scope": "claim_scope_versions",
    "cluster": "evidence_clusters",
    "interpretation_candidate": "interpretation_candidates",
    "experiment": "experiments",
    "experiment_plan_version": "experiment_plan_versions",
    "experiment_run": "experiment_runs",
    "experiment_observation": "experiment_observations",
    "evidence_locator": "evidence_locators",
    "artifact": "artifacts",
    "manuscript": "manuscripts",
    "manuscript_claim": "manuscript_claims",
    "manuscript_unit": "manuscript_units",
}


def _context_key(manuscript_id: str | None) -> str:
    return manuscript_id or "project"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ManuscriptPlanningService(BaseService):
    """Project-scoped copy-on-write planning service.

    Branch rows are resumable heads. Artifact versions, evidence bindings, and
    branch events are append-only provenance. Nothing here ratifies or mutates
    canonical manuscript semantics.
    """

    async def create_branch(self, data: PlanningBranchCreate) -> dict[str, Any]:
        async with self.db.transaction():
            parent: dict[str, Any] | None = None
            manuscript_id = data.manuscript_id
            if data.parent_branch_id:
                parent = await self._require_branch(data.parent_branch_id)
                parent_manuscript = parent.get("manuscript_id")
                if manuscript_id is not None and manuscript_id != parent_manuscript:
                    raise ValueError("child branch manuscript must match its parent context")
                manuscript_id = parent_manuscript

            base_revision: int | None = None
            if manuscript_id is not None:
                manuscript = await self.db.fetchone(
                    "SELECT revision FROM manuscripts WHERE id = ? AND project_id = ?",
                    [manuscript_id, self.project_id],
                )
                if manuscript is None:
                    raise ValueError(
                        f"manuscript {manuscript_id!r} is not available in this project"
                    )
                base_revision = (
                    int(parent["base_manuscript_revision"])
                    if parent is not None
                    else int(manuscript["revision"])
                )

            context_key = _context_key(manuscript_id)
            parent_branch_revision = int(parent["revision"]) if parent is not None else None
            selected = await self.db.fetchone(
                """SELECT id FROM manuscript_planning_branches
                   WHERE project_id = ? AND context_key = ? AND state = 'selected'""",
                [self.project_id, context_key],
            )
            state = "active" if selected else "selected"
            branch_id = generate_id("manuscript_planning_branch")
            try:
                await self.db.execute(
                    """INSERT INTO manuscript_planning_branches
                       (id, project_id, manuscript_id, context_key, name, purpose,
                        parent_branch_id, parent_branch_revision,
                        base_manuscript_revision, state, created_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        branch_id,
                        self.project_id,
                        manuscript_id,
                        context_key,
                        data.name,
                        data.purpose,
                        data.parent_branch_id,
                        parent_branch_revision,
                        base_revision,
                        state,
                        data.created_by,
                    ],
                )
            except sqlite3.IntegrityError as exc:
                raise PlanningConflictError(str(exc)) from exc
            await self._insert_branch_event(
                branch_id=branch_id,
                revision=1,
                action="created",
                from_state=None,
                to_state=state,
                actor=data.created_by,
                reason=data.reason,
                details={"parent_branch_id": data.parent_branch_id},
            )
        return await self.get_branch(branch_id)

    async def list_branches(
        self,
        *,
        manuscript_id: str | None = None,
        include_archived: bool = True,
    ) -> list[dict[str, Any]]:
        context_key = _context_key(manuscript_id)
        sql = """SELECT * FROM manuscript_planning_branches
                 WHERE project_id = ? AND context_key = ?"""
        params: list[Any] = [self.project_id, context_key]
        if not include_archived:
            sql += " AND state NOT IN ('archived', 'superseded')"
        sql += " ORDER BY CASE state WHEN 'selected' THEN 0 WHEN 'active' THEN 1 ELSE 2 END, updated_at DESC, id"
        rows = await self.db.fetchall(sql, params)
        return [dict(row) for row in rows]

    async def get_branch(self, branch_id: str) -> dict[str, Any]:
        branch = await self._require_branch(branch_id)
        artifacts = await self._effective_artifacts(branch_id)
        events = await self.db.fetchall(
            """SELECT * FROM manuscript_planning_branch_events
               WHERE branch_id = ? AND project_id = ?
               ORDER BY branch_revision ASC""",
            [branch_id, self.project_id],
        )
        return {
            "schema_version": PLANNING_CONTEXT_SCHEMA_VERSION,
            "project_id": self.project_id,
            "branch": branch,
            "effective_artifacts": artifacts,
            "parking_lot": [
                artifact for artifact in artifacts if artifact["version"]["lifecycle"] == "parked"
            ],
            "events": [self._event_row(row) for row in events],
        }

    async def resume(self, *, manuscript_id: str | None = None) -> dict[str, Any] | None:
        """Return the exact selected branch head for this planning context."""
        row = await self.db.fetchone(
            """SELECT id FROM manuscript_planning_branches
               WHERE project_id = ? AND context_key = ? AND state = 'selected'""",
            [self.project_id, _context_key(manuscript_id)],
        )
        return await self.get_branch(str(row["id"])) if row else None

    async def transition_branch(
        self,
        branch_id: str,
        data: PlanningBranchTransition,
    ) -> dict[str, Any]:
        async with self.db.transaction():
            branch = await self._require_branch(branch_id)
            current_state = str(branch["state"])
            if int(branch["revision"]) != data.expected_revision:
                raise PlanningConflictError(
                    f"planning branch revision conflict: expected {data.expected_revision}, "
                    f"found {branch['revision']}"
                )
            if current_state == data.target_state:
                raise ValueError(f"planning branch is already {current_state!r}")
            if current_state == "superseded":
                raise ValueError("superseded planning branches are terminal")
            if current_state == "selected" and data.target_state != "selected":
                raise ValueError("select another branch before archiving or deactivating this one")

            if data.target_state == "selected":
                previous = await self.db.fetchone(
                    """SELECT * FROM manuscript_planning_branches
                       WHERE project_id = ? AND context_key = ? AND state = 'selected'
                         AND id <> ?""",
                    [self.project_id, branch["context_key"], branch_id],
                )
                if previous is not None:
                    previous_revision = int(previous["revision"]) + 1
                    await self.db.execute(
                        """UPDATE manuscript_planning_branches
                           SET state = 'active', revision = revision + 1, updated_at = ?
                           WHERE id = ? AND project_id = ?""",
                        [_now(), previous["id"], self.project_id],
                    )
                    await self._insert_branch_event(
                        branch_id=str(previous["id"]),
                        revision=previous_revision,
                        action="activated",
                        from_state="selected",
                        to_state="active",
                        actor=data.actor,
                        reason=f"Selection moved to {branch_id}: {data.reason}",
                        details={"selected_branch_id": branch_id},
                    )

            action = {
                "selected": "selected",
                "active": "activated",
                "archived": "archived",
                "superseded": "superseded",
            }[data.target_state]
            cursor = await self.db.execute(
                """UPDATE manuscript_planning_branches
                   SET state = ?, revision = revision + 1, updated_at = ?
                   WHERE id = ? AND project_id = ? AND revision = ?""",
                [
                    data.target_state,
                    _now(),
                    branch_id,
                    self.project_id,
                    data.expected_revision,
                ],
            )
            if cursor.rowcount != 1:
                raise PlanningConflictError("planning branch changed concurrently")
            await self._insert_branch_event(
                branch_id=branch_id,
                revision=data.expected_revision + 1,
                action=action,
                from_state=current_state,
                to_state=data.target_state,
                actor=data.actor,
                reason=data.reason,
                details={},
            )
        return await self.get_branch(branch_id)

    async def append_artifact_version(
        self,
        branch_id: str,
        data: PlanningArtifactVersionAppend,
    ) -> dict[str, Any]:
        """Append an immutable artifact version and advance its branch head."""
        async with self.db.transaction():
            branch = await self._require_branch(branch_id)
            if branch["state"] not in {"active", "selected"}:
                raise ValueError("artifacts may only be edited on active or selected branches")
            if int(branch["revision"]) != data.expected_branch_revision:
                raise PlanningConflictError(
                    f"planning branch revision conflict: expected {data.expected_branch_revision}, "
                    f"found {branch['revision']}"
                )

            artifact = await self.db.fetchone(
                """SELECT * FROM manuscript_planning_artifacts
                   WHERE project_id = ? AND branch_id = ?
                     AND stage_type = ? AND local_key = ?""",
                [self.project_id, branch_id, data.stage_type, data.local_key],
            )
            derived_from_version_id: str | None = None
            if artifact is None:
                if data.expected_previous_version != 0:
                    raise PlanningConflictError(
                        "first branch-local artifact version requires expected_previous_version=0"
                    )
                inherited = await self._effective_artifact(
                    branch_id,
                    stage_type=data.stage_type,
                    local_key=data.local_key,
                )
                derived_from_version_id = (
                    str(inherited["version"]["id"]) if inherited is not None else None
                )
                artifact_id = generate_id("manuscript_planning_artifact")
                await self.db.execute(
                    """INSERT INTO manuscript_planning_artifacts
                       (id, branch_id, project_id, local_key, stage_type, created_by)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        artifact_id,
                        branch_id,
                        self.project_id,
                        data.local_key,
                        data.stage_type,
                        data.created_by,
                    ],
                )
                previous_version_id = None
                next_version = 1
            else:
                artifact_id = str(artifact["id"])
                current_version = int(artifact["current_version"])
                if current_version != data.expected_previous_version:
                    raise PlanningConflictError(
                        f"planning artifact version conflict: expected "
                        f"{data.expected_previous_version}, found {current_version}"
                    )
                previous_version_id = str(artifact["current_version_id"])
                next_version = current_version + 1

            await self._validate_bindings(data.evidence_bindings)
            if data.promotion_target_type and data.promotion_target_id:
                await self._require_entity(
                    data.promotion_target_type,
                    data.promotion_target_id,
                )

            version_id = generate_id("manuscript_planning_artifact_version")
            await self.db.execute(
                """INSERT INTO manuscript_planning_artifact_versions
                   (id, artifact_id, branch_id, project_id, version, branch_revision, lifecycle,
                    summary, payload, origin, provider, model, context_hash,
                    unresolved_items, readiness_state, readiness_missing,
                    readiness_notes, promotion_target_type, promotion_target_id,
                    created_by, reason, supersedes_version_id, derived_from_version_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    version_id,
                    artifact_id,
                    branch_id,
                    self.project_id,
                    next_version,
                    data.expected_branch_revision + 1,
                    data.lifecycle,
                    data.summary,
                    _canonical_json(data.payload),
                    data.origin,
                    data.provider,
                    data.model,
                    data.context_hash,
                    _canonical_json(data.unresolved_items),
                    data.readiness_state,
                    _canonical_json(data.readiness_missing),
                    data.readiness_notes,
                    data.promotion_target_type,
                    data.promotion_target_id,
                    data.created_by,
                    data.reason,
                    previous_version_id,
                    derived_from_version_id,
                ],
            )
            for binding in data.evidence_bindings:
                await self._insert_binding(version_id, artifact_id, binding)

            artifact_cursor = await self.db.execute(
                """UPDATE manuscript_planning_artifacts
                   SET current_version = current_version + 1,
                       current_version_id = ?, updated_at = ?
                   WHERE id = ? AND project_id = ? AND current_version = ?""",
                [version_id, _now(), artifact_id, self.project_id, next_version - 1],
            )
            if artifact_cursor.rowcount != 1:
                raise PlanningConflictError("planning artifact changed concurrently")
            branch_cursor = await self.db.execute(
                """UPDATE manuscript_planning_branches
                   SET revision = revision + 1, updated_at = ?
                   WHERE id = ? AND project_id = ? AND revision = ?""",
                [_now(), branch_id, self.project_id, data.expected_branch_revision],
            )
            if branch_cursor.rowcount != 1:
                raise PlanningConflictError("planning branch changed concurrently")
            await self._insert_branch_event(
                branch_id=branch_id,
                revision=data.expected_branch_revision + 1,
                action="artifact_version_appended",
                from_state=str(branch["state"]),
                to_state=str(branch["state"]),
                actor=data.created_by,
                reason=data.reason,
                details={
                    "artifact_id": artifact_id,
                    "artifact_version_id": version_id,
                    "stage_type": data.stage_type,
                    "local_key": data.local_key,
                    "version": next_version,
                },
            )
        return await self.get_branch(branch_id)

    async def list_artifact_versions(self, artifact_id: str) -> list[dict[str, Any]]:
        artifact = await self.db.fetchone(
            """SELECT id FROM manuscript_planning_artifacts
               WHERE id = ? AND project_id = ?""",
            [artifact_id, self.project_id],
        )
        if artifact is None:
            raise PlanningNotFoundError(f"planning artifact {artifact_id!r} not found")
        rows = await self.db.fetchall(
            """SELECT * FROM manuscript_planning_artifact_versions
               WHERE artifact_id = ? AND project_id = ? ORDER BY version ASC""",
            [artifact_id, self.project_id],
        )
        return [await self._version_row(row) for row in rows]

    async def compare_branches(
        self,
        base_branch_id: str,
        other_branch_id: str,
    ) -> dict[str, Any]:
        base = await self._require_branch(base_branch_id)
        other = await self._require_branch(other_branch_id)
        if base["context_key"] != other["context_key"]:
            raise ValueError("planning branches must share manuscript context to compare")
        base_artifacts = {
            (item["stage_type"], item["local_key"]): item
            for item in await self._effective_artifacts(base_branch_id)
        }
        other_artifacts = {
            (item["stage_type"], item["local_key"]): item
            for item in await self._effective_artifacts(other_branch_id)
        }
        changes: list[dict[str, Any]] = []
        for stage_type, local_key in sorted(set(base_artifacts) | set(other_artifacts)):
            left = base_artifacts.get((stage_type, local_key))
            right = other_artifacts.get((stage_type, local_key))
            if left is None:
                status = "added"
            elif right is None:
                status = "removed"
            elif self._artifact_digest(left) == self._artifact_digest(right):
                status = "unchanged"
            else:
                status = "changed"
            changes.append(
                {
                    "stage_type": stage_type,
                    "local_key": local_key,
                    "status": status,
                    "base": self._comparison_ref(left),
                    "other": self._comparison_ref(right),
                }
            )
        return {
            "schema_version": PLANNING_COMPARISON_SCHEMA_VERSION,
            "project_id": self.project_id,
            "context_key": base["context_key"],
            "base_branch": base,
            "other_branch": other,
            "summary": {
                status: sum(1 for item in changes if item["status"] == status)
                for status in ("added", "removed", "changed", "unchanged")
            },
            "changes": changes,
        }

    async def _effective_artifacts(self, branch_id: str) -> list[dict[str, Any]]:
        ancestry = await self._branch_ancestry(branch_id)
        effective: dict[tuple[str, str], dict[str, Any]] = {}
        for depth, (branch, maximum_revision) in enumerate(ancestry):
            rows = await self.db.fetchall(
                """SELECT * FROM manuscript_planning_artifacts
                   WHERE branch_id = ? AND project_id = ?
                   ORDER BY stage_type, local_key""",
                [branch["id"], self.project_id],
            )
            for row in rows:
                key = (str(row["stage_type"]), str(row["local_key"]))
                if key in effective or int(row["current_version"]) == 0:
                    continue
                version = await self.db.fetchone(
                    """SELECT * FROM manuscript_planning_artifact_versions
                       WHERE artifact_id = ? AND project_id = ?
                         AND branch_revision <= ?
                       ORDER BY branch_revision DESC LIMIT 1""",
                    [row["id"], self.project_id, maximum_revision],
                )
                if version is None:
                    continue
                item = dict(row)
                item["version"] = await self._version_row(version)
                item["resolved_from_branch_id"] = branch["id"]
                item["is_inherited"] = depth > 0
                effective[key] = item
        return [effective[key] for key in sorted(effective)]

    async def _effective_artifact(
        self,
        branch_id: str | None,
        *,
        stage_type: str,
        local_key: str,
    ) -> dict[str, Any] | None:
        if branch_id is None:
            return None
        for item in await self._effective_artifacts(branch_id):
            if item["stage_type"] == stage_type and item["local_key"] == local_key:
                return item
        return None

    async def _branch_ancestry(self, branch_id: str) -> list[tuple[dict[str, Any], int]]:
        ancestry: list[tuple[dict[str, Any], int]] = []
        seen: set[str] = set()
        current_id: str | None = branch_id
        maximum_revision: int | None = None
        while current_id is not None:
            if current_id in seen:
                raise RuntimeError("planning branch ancestry contains a cycle")
            seen.add(current_id)
            branch = await self._require_branch(current_id)
            resolved_revision = (
                int(branch["revision"]) if maximum_revision is None else maximum_revision
            )
            ancestry.append((branch, resolved_revision))
            maximum_revision = (
                int(branch["parent_branch_revision"])
                if branch["parent_branch_id"] is not None
                else None
            )
            current_id = str(branch["parent_branch_id"]) if branch["parent_branch_id"] else None
        return ancestry

    async def _require_branch(self, branch_id: str) -> dict[str, Any]:
        row = await self.db.fetchone(
            """SELECT * FROM manuscript_planning_branches
               WHERE id = ? AND project_id = ?""",
            [branch_id, self.project_id],
        )
        if row is None:
            raise PlanningNotFoundError(f"planning branch {branch_id!r} not found")
        return dict(row)

    async def _validate_bindings(
        self,
        bindings: list[PlanningEvidenceBindingInput],
    ) -> None:
        seen: set[tuple[str, str, str, int]] = set()
        for binding in bindings:
            key = (
                binding.entity_type,
                binding.entity_id,
                binding.role,
                binding.ordinal,
            )
            if key in seen:
                raise ValueError(f"duplicate planning evidence binding {key!r}")
            seen.add(key)
            await self._require_entity(binding.entity_type, binding.entity_id)

    async def _require_entity(self, entity_type: str, entity_id: str) -> None:
        table = _ENTITY_TABLES.get(entity_type)
        if table is None:
            raise ValueError(f"unsupported planning evidence entity type {entity_type!r}")
        row = await self.db.fetchone(
            f"SELECT id FROM {table} WHERE id = ? AND project_id = ?",
            [entity_id, self.project_id],
        )
        if row is None:
            raise ValueError(f"{entity_type} {entity_id!r} is not available in this project")

    async def _insert_binding(
        self,
        version_id: str,
        artifact_id: str,
        binding: PlanningEvidenceBindingInput,
    ) -> None:
        await self.db.execute(
            """INSERT INTO manuscript_planning_evidence_bindings
               (id, artifact_version_id, artifact_id, project_id, entity_type,
                entity_id, role, source_version, locator_kind, locator_value,
                locator_start, locator_end, content_hash, ordinal, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                generate_id("manuscript_planning_evidence_binding"),
                version_id,
                artifact_id,
                self.project_id,
                binding.entity_type,
                binding.entity_id,
                binding.role,
                binding.source_version,
                binding.locator_kind,
                binding.locator_value,
                binding.locator_start,
                binding.locator_end,
                binding.content_hash,
                binding.ordinal,
                binding.note,
            ],
        )

    async def _insert_branch_event(
        self,
        *,
        branch_id: str,
        revision: int,
        action: str,
        from_state: str | None,
        to_state: str,
        actor: str,
        reason: str,
        details: dict[str, Any],
    ) -> None:
        await self.db.execute(
            """INSERT INTO manuscript_planning_branch_events
               (id, branch_id, project_id, branch_revision, action,
                from_state, to_state, actor, reason, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                generate_id("manuscript_planning_branch_event"),
                branch_id,
                self.project_id,
                revision,
                action,
                from_state,
                to_state,
                actor,
                reason,
                _canonical_json(details),
            ],
        )

    async def _version_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["payload"] = parse_json_field(result.get("payload"), {})
        result["payload"] = validate_planning_payload(
            str(result["payload"].get("stage_type", ""))
            if "stage_type" in result["payload"]
            else await self._stage_for_artifact(str(result["artifact_id"])),
            result["payload"],
        )
        result["unresolved_items"] = parse_json_field(result.get("unresolved_items"), [])
        result["readiness_missing"] = parse_json_field(result.get("readiness_missing"), [])
        bindings = await self.db.fetchall(
            """SELECT * FROM manuscript_planning_evidence_bindings
               WHERE artifact_version_id = ? AND project_id = ?
               ORDER BY ordinal, entity_type, entity_id, role, id""",
            [result["id"], self.project_id],
        )
        result["evidence_bindings"] = [dict(binding) for binding in bindings]
        return result

    async def _stage_for_artifact(self, artifact_id: str) -> str:
        row = await self.db.fetchone(
            """SELECT stage_type FROM manuscript_planning_artifacts
               WHERE id = ? AND project_id = ?""",
            [artifact_id, self.project_id],
        )
        if row is None:
            raise RuntimeError(f"planning artifact {artifact_id!r} is missing")
        return str(row["stage_type"])

    @staticmethod
    def _event_row(row: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["details"] = parse_json_field(result.get("details"), {})
        return result

    @staticmethod
    def _artifact_digest(artifact: dict[str, Any]) -> str:
        version = artifact["version"]
        comparable = {
            "lifecycle": version["lifecycle"],
            "summary": version["summary"],
            "payload": version["payload"],
            "unresolved_items": version["unresolved_items"],
            "readiness_state": version["readiness_state"],
            "readiness_missing": version["readiness_missing"],
            "readiness_notes": version["readiness_notes"],
            "promotion_target_type": version["promotion_target_type"],
            "promotion_target_id": version["promotion_target_id"],
            "evidence_bindings": [
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
                for binding in version["evidence_bindings"]
            ],
        }
        return hashlib.sha256(_canonical_json(comparable).encode()).hexdigest()

    @staticmethod
    def _comparison_ref(artifact: dict[str, Any] | None) -> dict[str, Any] | None:
        if artifact is None:
            return None
        return {
            "artifact_id": artifact["id"],
            "version_id": artifact["version"]["id"],
            "version": artifact["version"]["version"],
            "summary": artifact["version"]["summary"],
            "lifecycle": artifact["version"]["lifecycle"],
            "resolved_from_branch_id": artifact["resolved_from_branch_id"],
            "is_inherited": artifact["is_inherited"],
        }
