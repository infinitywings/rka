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
    PlanningContributionProposalPrepare,
    PlanningContributionRatification,
    PlanningEvidenceBindingInput,
    PlanningEvaluationMissionCreate,
    PlanningEvaluationResultProposalPrepare,
    PlanningResearchQuestionPromotion,
    parse_json_field,
    validate_planning_payload,
)
from rka.services.base import BaseService, _now


PLANNING_CONTEXT_SCHEMA_VERSION = "rka.manuscript-planning/v1"
PLANNING_COMPARISON_SCHEMA_VERSION = "rka.manuscript-planning-comparison/v1"
ARGUMENT_WORKFLOW_SCHEMA_VERSION = "rka.seed-to-contribution-workflow/v1"
EVALUATION_WORKFLOW_SCHEMA_VERSION = "rka.claim-centered-evaluation/v1"

ARGUMENT_STAGE_ORDER = (
    "seed",
    "paragraph_spine",
    "problem_scope",
    "landscape_gap",
    "response_mechanism",
    "challenge_innovation",
    "rq_contribution",
)
_ARGUMENT_STAGE_LABELS = {
    "seed": "Seed insight",
    "paragraph_spine": "Paragraph spine",
    "problem_scope": "Problem and scope",
    "landscape_gap": "Literature, SOTA, and gap",
    "response_mechanism": "Insight and response",
    "challenge_innovation": "Challenges and innovations",
    "rq_contribution": "Research questions and contributions",
}
_ARGUMENT_STAGE_PREREQUISITES = {
    "seed": (),
    "paragraph_spine": ("seed",),
    "problem_scope": ("seed",),
    "landscape_gap": ("problem_scope",),
    "response_mechanism": ("seed", "landscape_gap"),
    "challenge_innovation": ("response_mechanism",),
    "rq_contribution": (
        "problem_scope",
        "landscape_gap",
        "response_mechanism",
        "challenge_innovation",
    ),
}


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

    async def argument_workflow(self, branch_id: str) -> dict[str, Any]:
        """Project one branch into deterministic seed-to-contribution guidance.

        This is a read-only view over immutable planning heads. It never calls
        a model and never promotes a planning selection into canonical RKA
        semantics.
        """
        branch = await self._require_branch(branch_id)
        artifacts = await self._effective_artifacts(branch_id)
        by_stage = {
            stage: [item for item in artifacts if item["stage_type"] == stage]
            for stage in ARGUMENT_STAGE_ORDER
        }
        stage_views: list[dict[str, Any]] = []
        verdicts: dict[str, str] = {}
        selected_heads: dict[str, dict[str, Any]] = {}

        for stage in ARGUMENT_STAGE_ORDER:
            candidates = [
                item
                for item in by_stage[stage]
                if item["version"]["lifecycle"]
                not in {"parked", "superseded", "archived"}
            ]
            selected = [
                item for item in candidates if item["version"]["lifecycle"] == "selected"
            ]
            current = selected[0] if len(selected) == 1 else (
                candidates[0] if len(candidates) == 1 else None
            )
            blockers: list[str] = []
            warnings: list[str] = []
            prerequisites = list(_ARGUMENT_STAGE_PREREQUISITES[stage])
            missing_prerequisites = [
                prerequisite
                for prerequisite in prerequisites
                if verdicts.get(prerequisite) != "Ready"
            ]
            if missing_prerequisites:
                blockers.append(
                    "Prerequisite stages are not ready: "
                    + ", ".join(missing_prerequisites)
                )
            if len(selected) > 1:
                blockers.append("Multiple artifacts are marked selected for this stage")
            elif current is None:
                if candidates:
                    warnings.append("Choose or combine one candidate before continuing")
                else:
                    blockers.append("No planning artifact has been captured for this stage")

            upstream_conflicts: list[dict[str, Any]] = []
            if current is not None:
                version = current["version"]
                if version["readiness_state"] == "blocked":
                    blockers.append("The selected artifact is explicitly blocked")
                if version["readiness_missing"]:
                    warnings.extend(version["readiness_missing"])
                if version["unresolved_items"]:
                    warnings.extend(version["unresolved_items"])
                if prerequisites:
                    upstream = version["payload"].get("upstream_versions") or []
                    if not upstream:
                        warnings.append("Upstream planning heads have not been pinned")
                    else:
                        for reference in upstream:
                            head = selected_heads.get(str(reference["stage_type"]))
                            if head is None:
                                upstream_conflicts.append(
                                    {"reference": reference, "current": None}
                                )
                                continue
                            head_version = head["version"]
                            if (
                                reference["artifact_id"] != head["id"]
                                or reference["version_id"] != head_version["id"]
                                or int(reference["version"]) != int(head_version["version"])
                            ):
                                upstream_conflicts.append(
                                    {
                                        "reference": reference,
                                        "current": self._comparison_ref(head),
                                    }
                                )
                    if upstream_conflicts:
                        blockers.append("One or more reviewed upstream artifact heads changed")
                warnings.extend(self._stage_contract_findings(stage, version))

            if blockers:
                verdict = "Blocked"
            elif current is None:
                verdict = "Exploratory"
            elif (
                current["version"]["lifecycle"] == "selected"
                and current["version"]["readiness_state"] == "ready"
                and not warnings
            ):
                verdict = "Ready"
            else:
                verdict = "Needs review"
            verdicts[stage] = verdict
            if current is not None and current["version"]["lifecycle"] == "selected":
                selected_heads[stage] = current
            stage_views.append(
                {
                    "stage_type": stage,
                    "label": _ARGUMENT_STAGE_LABELS[stage],
                    "verdict": verdict,
                    "prerequisites": prerequisites,
                    "dependents": [
                        candidate_stage
                        for candidate_stage, candidate_prerequisites
                        in _ARGUMENT_STAGE_PREREQUISITES.items()
                        if stage in candidate_prerequisites
                    ],
                    "current_artifact": current,
                    "candidate_artifacts": candidates,
                    "blockers": sorted(set(blockers)),
                    "warnings": sorted(set(warnings)),
                    "upstream_conflicts": upstream_conflicts,
                    "next_action": self._stage_next_action(stage, verdict, current),
                }
            )

        next_stage = next(
            (item for item in stage_views if item["verdict"] != "Ready"),
            None,
        )
        return {
            "schema_version": ARGUMENT_WORKFLOW_SCHEMA_VERSION,
            "project_id": self.project_id,
            "branch": branch,
            "stages": stage_views,
            "next_recommended_stage": (
                next_stage["stage_type"] if next_stage is not None else None
            ),
            "quick_reader": await self._quick_reader_projection(
                branch=branch,
                selected_heads=selected_heads,
            ),
            "authority": {
                "planning": "provisional",
                "canonical_mutation": "semantic_patch_then_explicit_apply",
                "ratification": "separate_exact_pi_action",
                "llm_at_view_time": False,
            },
        }

    async def list_promotion_events(
        self,
        branch_id: str,
    ) -> list[dict[str, Any]]:
        await self._require_branch(branch_id)
        rows = await self.db.fetchall(
            """SELECT event.*, proposal.status AS proposal_status,
                      decision.status AS decision_status
               FROM manuscript_planning_promotion_events AS event
               LEFT JOIN semantic_patch_proposals AS proposal
                 ON proposal.id = event.proposal_id
                AND proposal.project_id = event.project_id
               LEFT JOIN decisions AS decision
                 ON decision.id = event.decision_id
                AND decision.project_id = event.project_id
               WHERE event.project_id = ? AND event.branch_id = ?
               ORDER BY event.created_at, event.id""",
            [self.project_id, branch_id],
        )
        result = []
        for row in rows:
            item = dict(row)
            item["details"] = parse_json_field(item.get("details"), {})
            result.append(item)
        return result

    async def evaluation_workflow(self, branch_id: str) -> dict[str, Any]:
        """Resolve one planning evaluation matrix against canonical evidence."""
        branch = await self._require_branch(branch_id)
        artifacts = await self._effective_artifacts(branch_id)
        candidates = [
            item
            for item in artifacts
            if item["stage_type"] == "evaluation"
            and item["version"]["lifecycle"] not in {"parked", "superseded", "archived"}
        ]
        selected = [
            item for item in candidates if item["version"]["lifecycle"] == "selected"
        ]
        artifact = selected[0] if len(selected) == 1 else (
            candidates[0] if len(candidates) == 1 else None
        )
        blockers: list[str] = []
        warnings: list[str] = []
        if len(selected) > 1:
            blockers.append("Multiple evaluation artifacts are marked selected")
        elif artifact is None:
            if candidates:
                warnings.append("Choose or combine one evaluation contract")
            else:
                warnings.append("No evaluation contract has been captured")

        rq_artifacts = [
            item
            for item in artifacts
            if item["stage_type"] == "rq_contribution"
            and item["version"]["lifecycle"] == "selected"
        ]
        if len(rq_artifacts) != 1:
            blockers.append("Exactly one selected RQ/contribution artifact is required")
        if artifact is not None:
            version = artifact["version"]
            if version["lifecycle"] != "selected":
                warnings.append("The evaluation contract has not been selected")
            if version["readiness_state"] == "blocked":
                blockers.append("The evaluation artifact is explicitly blocked")
            warnings.extend(version["unresolved_items"])
            warnings.extend(version["readiness_missing"])
            upstream = version["payload"].get("upstream_versions") or []
            rq_refs = [item for item in upstream if item["stage_type"] == "rq_contribution"]
            if len(rq_artifacts) == 1:
                current_rq = rq_artifacts[0]
                if len(rq_refs) != 1:
                    blockers.append("The exact RQ/contribution planning head is not pinned")
                else:
                    reference = rq_refs[0]
                    if (
                        reference["artifact_id"] != current_rq["id"]
                        or reference["version_id"] != current_rq["version"]["id"]
                        or int(reference["version"]) != int(current_rq["version"]["version"])
                    ):
                        blockers.append("The reviewed RQ/contribution head has changed")

        events = await self.list_evaluation_events(branch_id)
        commitments: list[dict[str, Any]] = []
        if artifact is not None:
            for raw in artifact["version"]["payload"].get("commitments", []):
                if "local_key" not in raw:
                    commitments.append(
                        {
                            "legacy": True,
                            "commitment": raw,
                            "verdict": "Blocked",
                            "blockers": [
                                "Legacy free-text commitment must be revised into the ADR 0008 contract"
                            ],
                            "warnings": [],
                            "requirements": [],
                            "next_action": "Add stable claim, RQ, requirement, and evidence bindings",
                        }
                    )
                    continue
                commitments.append(
                    await self._project_evaluation_commitment(
                        branch=branch,
                        artifact=artifact,
                        commitment=raw,
                        events=events,
                    )
                )
        if artifact is not None and not commitments:
            blockers.append("The evaluation artifact has no commitments")

        if blockers or any(item["verdict"] == "Blocked" for item in commitments):
            verdict = "Blocked"
        elif artifact is None:
            verdict = "Exploratory" if not candidates else "Needs review"
        elif (
            artifact["version"]["lifecycle"] != "selected"
            or artifact["version"]["readiness_state"] != "ready"
            or warnings
            or any(item["verdict"] != "Ready" for item in commitments)
        ):
            verdict = "Needs review"
        else:
            verdict = "Ready"
        if verdict == "Blocked":
            next_action = "Resolve missing or conflicting claim/evidence links"
        elif verdict == "Exploratory":
            next_action = "Capture a claim-centered evaluation contract"
        elif verdict == "Needs review":
            next_action = "Review outcomes, interpretation boundaries, and remaining evidence"
        else:
            next_action = "Prepare bounded result units or continue drafting"
        return {
            "schema_version": EVALUATION_WORKFLOW_SCHEMA_VERSION,
            "project_id": self.project_id,
            "branch": branch,
            "artifact": artifact,
            "candidate_artifacts": candidates,
            "verdict": verdict,
            "blockers": sorted(set(blockers)),
            "warnings": sorted(set(warnings)),
            "commitments": commitments,
            "events": events,
            "next_action": next_action,
            "authority": {
                "planning": "provisional",
                "evidence": "canonical_exact_records",
                "outcomes": "explicit_not_inferred_from_direction",
                "canonical_mutation": "explicit_mission_or_semantic_patch",
                "llm_at_view_time": False,
            },
        }

    async def _project_evaluation_commitment(
        self,
        *,
        branch: Mapping[str, Any],
        artifact: Mapping[str, Any],
        commitment: Mapping[str, Any],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        blockers: list[str] = []
        warnings: list[str] = []
        claim = await self.db.fetchone(
            """SELECT claim.*, version.version, version.exact_wording,
                      version.allowed_wording, version.prohibited_wording,
                      (SELECT MAX(current.version)
                         FROM manuscript_claim_versions AS current
                        WHERE current.claim_id = claim.id
                          AND current.project_id = claim.project_id) AS current_version
                 FROM manuscript_claims AS claim
                 JOIN manuscript_claim_versions AS version
                   ON version.claim_id = claim.id
                  AND version.project_id = claim.project_id
                  AND version.version = ?
                WHERE claim.id = ? AND claim.project_id = ?""",
            [commitment["claim_version"], commitment["claim_id"], self.project_id],
        )
        claim_view = dict(claim) if claim is not None else None
        if claim_view is None:
            blockers.append("The exact manuscript claim version does not exist")
        else:
            claim_view["prohibited_wording"] = parse_json_field(
                claim_view.get("prohibited_wording"), []
            )
            if branch.get("manuscript_id") and claim_view["manuscript_id"] != branch["manuscript_id"]:
                blockers.append("The claim belongs to a different manuscript")
            if claim_view["state"] != "active":
                blockers.append("The evaluated manuscript claim is not active")
            if int(claim_view["current_version"]) != int(commitment["claim_version"]):
                blockers.append("The manuscript claim wording changed after this contract")
            ratification = await self.db.fetchone(
                """SELECT ratification.id, ratification.decision_id
                     FROM manuscript_claim_ratifications AS ratification
                     JOIN decisions AS decision
                       ON decision.id = ratification.decision_id
                      AND decision.project_id = ratification.project_id
                    WHERE ratification.project_id = ? AND ratification.claim_id = ?
                      AND ratification.claim_version = ? AND decision.status = 'active'
                      AND decision.decided_by = 'pi' AND decision.superseded_by IS NULL
                      AND decision.chosen = ?
                    ORDER BY ratification.created_at DESC LIMIT 1""",
                [
                    self.project_id,
                    commitment["claim_id"],
                    commitment["claim_version"],
                    claim_view["exact_wording"],
                ],
            )
            claim_view["ratification"] = dict(ratification) if ratification else None
            if ratification is None:
                warnings.append("The exact evaluated claim version is not PI-ratified")

        rq_decisions: list[dict[str, Any]] = []
        for decision_id in commitment.get("research_question_refs", []):
            decision = await self.db.fetchone(
                """SELECT id, question, chosen, status, kind, decided_by, superseded_by
                     FROM decisions WHERE id = ? AND project_id = ?""",
                [decision_id, self.project_id],
            )
            if decision is None:
                blockers.append(f"Research-question decision {decision_id} is missing")
                continue
            item = dict(decision)
            rq_decisions.append(item)
            if (
                item["status"] != "active"
                or item.get("kind") != "research_question"
                or item.get("superseded_by")
            ):
                blockers.append(f"Research-question decision {decision_id} is not active")

        requirements = [
            await self._project_evaluation_requirement(requirement)
            for requirement in commitment.get("requirements", [])
        ]
        for requirement in requirements:
            blockers.extend(requirement["blockers"])
            warnings.extend(requirement["warnings"])

        if commitment.get("disposition") == "selected":
            for field_name, label in (
                ("baselines", "baseline or control"),
                ("metrics", "metric or observation"),
                ("conditions", "tested condition"),
                ("success_criteria", "success criterion"),
                ("failure_criteria", "failure or falsification criterion"),
            ):
                if not commitment.get(field_name):
                    blockers.append(f"Selected commitment needs at least one {label}")
        elif commitment.get("disposition") == "candidate":
            warnings.append("The evaluation commitment has not been selected")

        if blockers:
            verdict = "Blocked"
        elif commitment.get("disposition") == "parked":
            verdict = "Exploratory"
        elif warnings or commitment.get("disposition") != "selected":
            verdict = "Needs review"
        else:
            verdict = "Ready"
        related_events = [
            item for item in events if item["commitment_key"] == commitment["local_key"]
        ]
        if verdict == "Blocked":
            next_action = "Resolve missing evidence or stale canonical references"
        elif verdict == "Needs review":
            next_action = "Review claim effects and interpretation boundaries"
        elif verdict == "Exploratory":
            next_action = "Select or revise this commitment when it becomes central"
        else:
            next_action = "Prepare a result unit from the located evidence"
        return {
            "legacy": False,
            "commitment": dict(commitment),
            "claim": claim_view,
            "research_questions": rq_decisions,
            "requirements": requirements,
            "events": related_events,
            "verdict": verdict,
            "blockers": sorted(set(blockers)),
            "warnings": sorted(set(warnings)),
            "next_action": next_action,
        }

    async def _project_evaluation_requirement(
        self,
        requirement: Mapping[str, Any],
    ) -> dict[str, Any]:
        blockers: list[str] = []
        warnings: list[str] = []
        plan_view = None
        if requirement.get("experiment_id"):
            plan = await self.db.fetchone(
                """SELECT plan.*, experiment.title AS experiment_title,
                          experiment.status AS experiment_status
                     FROM experiment_plan_versions AS plan
                     JOIN experiments AS experiment
                       ON experiment.id = plan.experiment_id
                      AND experiment.project_id = plan.project_id
                    WHERE plan.id = ? AND plan.experiment_id = ?
                      AND plan.version = ? AND plan.project_id = ?""",
                [
                    requirement["plan_version_id"],
                    requirement["experiment_id"],
                    requirement["plan_version"],
                    self.project_id,
                ],
            )
            plan_view = dict(plan) if plan else None
            if plan_view is None:
                blockers.append(
                    f"Requirement {requirement['local_key']} has an invalid exact experiment plan"
                )
        elif requirement.get("required"):
            blockers.append(
                f"Requirement {requirement['local_key']} has no exact experiment plan"
            )

        observations: list[dict[str, Any]] = []
        conclusive = 0
        for binding in requirement.get("observations", []):
            row = await self.db.fetchone(
                """SELECT observation.*, run.experiment_id, run.plan_version,
                          run.status AS run_status, run.label AS run_label
                     FROM experiment_observations AS observation
                     JOIN experiment_runs AS run
                       ON run.id = observation.run_id
                      AND run.project_id = observation.project_id
                    WHERE observation.id = ? AND observation.project_id = ?""",
                [binding["observation_id"], self.project_id],
            )
            observation = dict(row) if row else None
            locator_views: list[dict[str, Any]] = []
            if observation is None:
                blockers.append(f"Observation {binding['observation_id']} is missing")
            else:
                if observation["experiment_id"] != requirement.get("experiment_id"):
                    blockers.append(
                        f"Observation {binding['observation_id']} belongs to another experiment"
                    )
                if int(observation["plan_version"]) != int(requirement.get("plan_version") or 0):
                    blockers.append(
                        f"Observation {binding['observation_id']} used another plan version"
                    )
                for locator_id in binding.get("locator_ids", []):
                    locator = await self.db.fetchone(
                        """SELECT * FROM evidence_locators
                            WHERE id = ? AND observation_id = ? AND project_id = ?""",
                        [locator_id, binding["observation_id"], self.project_id],
                    )
                    if locator is None:
                        blockers.append(
                            f"Locator {locator_id} does not locate observation {binding['observation_id']}"
                        )
                    else:
                        locator_views.append(dict(locator))
            outcome = binding["outcome"]
            effect = binding["claim_effect"]
            if outcome in {"supports", "partially_supports", "fails_to_support"}:
                conclusive += 1
            if effect == "unresolved":
                blockers.append(
                    f"Observation {binding['observation_id']} has an unresolved claim effect"
                )
            elif outcome in {"partially_supports", "fails_to_support", "inconclusive"}:
                warnings.append(
                    f"Observation {binding['observation_id']} {outcome.replace('_', ' ')}; "
                    f"claim effect is {effect.replace('_', ' ')}"
                )
            elif outcome == "exploratory":
                warnings.append(
                    f"Observation {binding['observation_id']} is exploratory and not claim support"
                )
            observations.append(
                {
                    "binding": dict(binding),
                    "observation": observation,
                    "locators": locator_views,
                }
            )
        if requirement.get("required") and conclusive == 0:
            blockers.append(
                f"Requirement {requirement['local_key']} lacks conclusive located evidence"
            )
        if requirement.get("required") and not requirement.get("acceptance_criteria"):
            blockers.append(
                f"Requirement {requirement['local_key']} lacks acceptance criteria"
            )
        if requirement.get("required") and not requirement.get("failure_criteria"):
            blockers.append(
                f"Requirement {requirement['local_key']} lacks falsification criteria"
            )
        return {
            "requirement": dict(requirement),
            "plan": plan_view,
            "observations": observations,
            "conclusive_observation_count": conclusive,
            "verdict": "Blocked" if blockers else ("Needs review" if warnings else "Ready"),
            "blockers": sorted(set(blockers)),
            "warnings": sorted(set(warnings)),
        }

    async def list_evaluation_events(self, branch_id: str) -> list[dict[str, Any]]:
        await self._require_branch(branch_id)
        rows = await self.db.fetchall(
            """SELECT event.*, proposal.status AS proposal_status,
                      mission.status AS mission_status
                 FROM manuscript_evaluation_events AS event
                 LEFT JOIN semantic_patch_proposals AS proposal
                   ON proposal.id = event.proposal_id
                  AND proposal.project_id = event.project_id
                 LEFT JOIN missions AS mission
                   ON mission.id = event.mission_id
                  AND mission.project_id = event.project_id
                WHERE event.project_id = ? AND event.branch_id = ?
                ORDER BY event.created_at, event.id""",
            [self.project_id, branch_id],
        )
        result = []
        for row in rows:
            item = dict(row)
            item["details"] = parse_json_field(item.get("details"), {})
            result.append(item)
        return result

    async def promote_research_question(
        self,
        branch_id: str,
        data: PlanningResearchQuestionPromotion,
    ) -> dict[str, Any]:
        from rka.models.decision import DecisionCreate
        from rka.services.decisions import DecisionService

        async with self.db.transaction():
            branch, artifact, candidate = await self._require_selected_candidate(
                branch_id=branch_id,
                expected_branch_revision=data.expected_branch_revision,
                artifact_id=data.artifact_id,
                expected_artifact_version=data.expected_artifact_version,
                candidate_kind="research_question",
                candidate_key=data.candidate_key,
            )
            await self._assert_no_promotion_action(
                artifact_version_id=str(artifact["version"]["id"]),
                candidate_kind="research_question",
                candidate_key=data.candidate_key,
                action="rq_promoted",
            )
            bindings = artifact["version"]["evidence_bindings"]
            decision = await DecisionService(
                self.db, project_id=self.project_id
            ).create(
                DecisionCreate(
                    question=str(candidate["question"]),
                    chosen=str(candidate["question"]),
                    rationale=(
                        f"{candidate['rationale']}\n\n"
                        f"Scope: {candidate['scope']}\n\n"
                        f"Promotion reason: {data.reason}"
                    ),
                    decided_by="pi",
                    phase=data.phase,
                    related_literature=sorted(
                        {
                            str(item["entity_id"])
                            for item in bindings
                            if item["entity_type"] == "literature"
                        }
                    ),
                    related_journal=sorted(
                        {
                            str(item["entity_id"])
                            for item in bindings
                            if item["entity_type"] == "journal"
                        }
                    ),
                    kind="research_question",
                    tags=[
                        "workbench:rq",
                        f"planning-version:{artifact['version']['id']}",
                        f"candidate:{data.candidate_key}",
                    ],
                    assumptions=candidate.get("assumptions") or None,
                ),
                actor="pi",
            )
            event = await self._insert_promotion_event(
                branch=branch,
                artifact=artifact,
                candidate_kind="research_question",
                candidate_key=data.candidate_key,
                action="rq_promoted",
                target_type="decision",
                target_id=decision.id,
                target_version=None,
                proposal_id=None,
                decision_id=decision.id,
                actor="pi",
                reason=data.reason,
                details={"scope": candidate["scope"]},
            )
        return {"decision": decision.model_dump(), "promotion_event": event}

    async def prepare_contribution_proposal(
        self,
        branch_id: str,
        data: PlanningContributionProposalPrepare,
    ) -> dict[str, Any]:
        from rka.models.semantic_patch import (
            ArgumentSpineReplaceOperation,
            SemanticPatchProposalCreate,
        )
        from rka.services.manuscript_native import NativeManuscriptService
        from rka.services.semantic_patch import SemanticPatchService

        async with self.db.transaction():
            branch, artifact, candidate = await self._require_selected_candidate(
                branch_id=branch_id,
                expected_branch_revision=data.expected_branch_revision,
                artifact_id=data.artifact_id,
                expected_artifact_version=data.expected_artifact_version,
                candidate_kind="contribution",
                candidate_key=data.candidate_key,
            )
            if branch.get("manuscript_id") and branch["manuscript_id"] != data.manuscript_id:
                raise ValueError("contribution target must match the branch manuscript context")
            await self._assert_no_promotion_action(
                artifact_version_id=str(artifact["version"]["id"]),
                candidate_kind="contribution",
                candidate_key=data.candidate_key,
                action="contribution_proposal_prepared",
            )
            manuscript = NativeManuscriptService(self.db, project_id=self.project_id)
            current = await manuscript.get(data.manuscript_id)
            if current is None:
                raise ValueError(f"manuscript {data.manuscript_id!r} not found")
            if int(current.revision) != data.expected_manuscript_revision:
                raise PlanningConflictError(
                    "manuscript revision changed before contribution proposal preparation"
                )
            spine = await manuscript.export_spine_projection(data.manuscript_id)
            claims = list(spine.get("claims") or [])
            units = list(spine.get("units") or [])
            claim_local_key = data.claim_local_key or str(candidate["local_key"])
            known_unit_keys = {
                str(unit.get("local_key") or unit.get("unit_id"))
                for unit in units
                if unit.get("local_key") or unit.get("unit_id")
            }
            claim_spec = {
                "local_key": claim_local_key,
                "kind": candidate["contribution_type"],
                "state": "active",
                "exact_wording": candidate["exact_wording"],
                "allowed_wording": candidate["allowed_wording"],
                "prohibited_wording": candidate["prohibited_wording"],
                "evidence": {
                    "support": candidate.get("support_ids", []),
                    "qualifier": candidate.get("qualifier_ids", []),
                    "counterevidence": candidate.get("counterevidence_ids", []),
                },
                "unit_links": [
                    {"unit_key": key, "relationship": "advances"}
                    for key in candidate.get("intended_units", [])
                    if key in known_unit_keys
                ],
            }
            replaced = False
            next_claims = []
            for claim in claims:
                if (claim.get("local_key") or claim.get("claim_id")) == claim_local_key:
                    next_claims.append(claim_spec)
                    replaced = True
                else:
                    next_claims.append(claim)
            if not replaced:
                next_claims.append(claim_spec)
            proposal = await SemanticPatchService(
                self.db, project_id=self.project_id
            ).create_proposal(
                SemanticPatchProposalCreate(
                    origin="human",
                    intent=f"Promote contribution candidate {data.candidate_key}.",
                    reason=data.reason,
                    created_by=data.actor,
                    operations=[
                        ArgumentSpineReplaceOperation(
                            manuscript_id=data.manuscript_id,
                            expected_revision=data.expected_manuscript_revision,
                            spine={"claims": next_claims, "units": units},
                        )
                    ],
                )
            )
            event = await self._insert_promotion_event(
                branch=branch,
                artifact=artifact,
                candidate_kind="contribution",
                candidate_key=data.candidate_key,
                action="contribution_proposal_prepared",
                target_type="semantic_patch_proposal",
                target_id=str(proposal["id"]),
                target_version=None,
                proposal_id=str(proposal["id"]),
                decision_id=None,
                actor=data.actor,
                reason=data.reason,
                details={
                    "manuscript_id": data.manuscript_id,
                    "claim_local_key": claim_local_key,
                    "exact_wording": candidate["exact_wording"],
                },
            )
        return {"proposal": proposal, "promotion_event": event}

    async def record_contribution_application(
        self,
        proposal_id: str,
        *,
        actor: str,
        reason: str,
    ) -> list[dict[str, Any]]:
        """Append claim-version lineage after a prepared proposal is applied."""
        prepared = await self.db.fetchall(
            """SELECT * FROM manuscript_planning_promotion_events
               WHERE project_id = ? AND proposal_id = ?
                 AND action = 'contribution_proposal_prepared'""",
            [self.project_id, proposal_id],
        )
        events = []
        for row in prepared:
            item = dict(row)
            details = parse_json_field(item.get("details"), {})
            claim = await self.db.fetchone(
                """SELECT claim.id, claim.local_key,
                          version.version, version.exact_wording
                   FROM manuscript_claims AS claim
                   JOIN manuscript_claim_versions AS version
                     ON version.claim_id = claim.id
                    AND version.project_id = claim.project_id
                   WHERE claim.project_id = ? AND claim.manuscript_id = ?
                     AND claim.local_key = ?
                   ORDER BY version.version DESC LIMIT 1""",
                [self.project_id, details["manuscript_id"], details["claim_local_key"]],
            )
            if claim is None or claim["exact_wording"] != details["exact_wording"]:
                raise RuntimeError(
                    "applied contribution proposal did not produce its exact candidate wording"
                )
            artifact = await self._promotion_artifact(item)
            branch = await self._require_branch(str(item["branch_id"]))
            events.append(
                await self._insert_promotion_event(
                    branch=branch,
                    artifact=artifact,
                    candidate_kind="contribution",
                    candidate_key=str(item["candidate_key"]),
                    action="contribution_proposal_applied",
                    target_type="manuscript_claim",
                    target_id=str(claim["id"]),
                    target_version=int(claim["version"]),
                    proposal_id=proposal_id,
                    decision_id=None,
                    actor=actor,
                    reason=reason,
                    details={
                        "manuscript_id": details["manuscript_id"],
                        "claim_local_key": details["claim_local_key"],
                    },
                )
            )
        return events

    async def ratify_contribution(
        self,
        branch_id: str,
        data: PlanningContributionRatification,
    ) -> dict[str, Any]:
        from rka.services.manuscript_native import NativeManuscriptService

        async with self.db.transaction():
            branch, artifact, candidate = await self._require_selected_candidate(
                branch_id=branch_id,
                expected_branch_revision=data.expected_branch_revision,
                artifact_id=data.artifact_id,
                expected_artifact_version=data.expected_artifact_version,
                candidate_kind="contribution",
                candidate_key=data.candidate_key,
            )
            application = await self.db.fetchone(
                """SELECT * FROM manuscript_planning_promotion_events
                   WHERE project_id = ? AND branch_id = ?
                     AND artifact_version_id = ? AND candidate_kind = 'contribution'
                     AND candidate_key = ? AND action = 'contribution_proposal_applied'
                     AND proposal_id = ?
                   ORDER BY created_at DESC LIMIT 1""",
                [
                    self.project_id,
                    branch_id,
                    artifact["version"]["id"],
                    data.candidate_key,
                    data.proposal_id,
                ],
            )
            if application is None:
                raise ValueError("the selected contribution proposal has not been applied")
            claim_ref = data.claim_ref
            claim = await self.db.fetchone(
                """SELECT claim.id, claim.local_key, version.version,
                          version.exact_wording
                   FROM manuscript_claims AS claim
                   JOIN manuscript_claim_versions AS version
                     ON version.claim_id = claim.id
                    AND version.project_id = claim.project_id
                   WHERE claim.project_id = ? AND claim.manuscript_id = ?
                     AND (claim.id = ? OR claim.local_key = ?)
                   ORDER BY version.version DESC LIMIT 1""",
                [self.project_id, data.manuscript_id, claim_ref, claim_ref],
            )
            if claim is None:
                raise ValueError("promoted manuscript claim not found")
            if claim["id"] != application["target_id"]:
                raise ValueError("claim does not match the applied contribution proposal")
            if claim["exact_wording"] != candidate["exact_wording"]:
                raise PlanningConflictError(
                    "current manuscript wording no longer matches the selected candidate"
                )
            ratification = await NativeManuscriptService(
                self.db, project_id=self.project_id
            ).ratify_claim(
                data.manuscript_id,
                claim_id=str(claim["id"]),
                claim_version=int(claim["version"]),
                decision_id=data.decision_id,
                expected_revision=data.expected_manuscript_revision,
                actor="pi",
            )
            event = await self._insert_promotion_event(
                branch=branch,
                artifact=artifact,
                candidate_kind="contribution",
                candidate_key=data.candidate_key,
                action="contribution_ratified",
                target_type="manuscript_claim_ratification",
                target_id=ratification.id,
                target_version=int(claim["version"]),
                proposal_id=data.proposal_id,
                decision_id=data.decision_id,
                actor="pi",
                reason=data.reason,
                details={
                    "manuscript_id": data.manuscript_id,
                    "claim_id": claim["id"],
                    "claim_local_key": claim["local_key"],
                },
            )
        return {
            "ratification": ratification.model_dump(),
            "promotion_event": event,
        }

    async def create_evaluation_mission(
        self,
        branch_id: str,
        data: PlanningEvaluationMissionCreate,
    ) -> dict[str, Any]:
        """Turn one missing evidence slot into an explicit canonical mission."""
        from rka.models.mission import MissionCreate, MissionTask
        from rka.services.missions import MissionService

        async with self.db.transaction():
            branch, artifact, commitment = await self._require_selected_evaluation_commitment(
                branch_id=branch_id,
                expected_branch_revision=data.expected_branch_revision,
                artifact_id=data.artifact_id,
                expected_artifact_version=data.expected_artifact_version,
                commitment_key=data.commitment_key,
            )
            requirement = next(
                (
                    item
                    for item in commitment["requirements"]
                    if item["local_key"] == data.requirement_key
                ),
                None,
            )
            if requirement is None:
                raise PlanningNotFoundError(
                    f"evaluation requirement {data.requirement_key!r} not found"
                )
            if any(
                item["outcome"] in {"supports", "partially_supports", "fails_to_support"}
                for item in requirement.get("observations", [])
            ):
                raise ValueError("missing-evidence mission requires an unresolved evidence slot")
            await self._assert_no_evaluation_action(
                artifact_version_id=str(artifact["version"]["id"]),
                commitment_key=data.commitment_key,
                requirement_key=data.requirement_key,
                action="missing_evidence_mission_created",
            )
            criteria = requirement.get("acceptance_criteria") or commitment["success_criteria"]
            failures = requirement.get("failure_criteria") or commitment["failure_criteria"]
            experiment = (
                f"Use experiment {requirement['experiment_id']} at exact plan "
                f"{requirement['plan_version_id']} (v{requirement['plan_version']})."
                if requirement.get("experiment_id")
                else "Create and review an exact experiment plan before execution."
            )
            mission = await MissionService(
                self.db, project_id=self.project_id
            ).create(
                MissionCreate(
                    phase=data.phase,
                    objective=requirement.get("missing_evidence") or requirement["description"],
                    tasks=[
                        MissionTask(description=experiment),
                        MissionTask(
                            description="Record immutable observations and exact evidence locators."
                        ),
                        MissionTask(
                            description=(
                                "Classify each outcome against the claim without inferring "
                                "support from metric direction."
                            )
                        ),
                    ],
                    context=(
                        f"Evaluation commitment {data.commitment_key} for exact claim "
                        f"{commitment['claim_id']} v{commitment['claim_version']}. "
                        f"Requirement: {requirement['description']}"
                    ),
                    acceptance_criteria="\n".join(criteria) or "Located evidence is recorded.",
                    scope_boundaries="\n".join(commitment.get("conditions", [])) or None,
                    checkpoint_triggers=(
                        "Failure/falsification criteria:\n" + "\n".join(failures)
                        if failures else None
                    ),
                    motivated_by_decision=(
                        data.motivated_by_decision
                        or commitment["research_question_refs"][0]
                    ),
                    tags=[
                        "workbench:evaluation",
                        f"planning-version:{artifact['version']['id']}",
                        f"commitment:{data.commitment_key}",
                        f"requirement:{data.requirement_key}",
                    ],
                ),
                actor=data.actor,
            )
            event = await self._insert_evaluation_event(
                branch=branch,
                artifact=artifact,
                commitment_key=data.commitment_key,
                requirement_key=data.requirement_key,
                action="missing_evidence_mission_created",
                target_type="mission",
                target_id=mission.id,
                target_version=None,
                proposal_id=None,
                mission_id=mission.id,
                actor=data.actor,
                reason=data.reason,
                details={
                    "claim_id": commitment["claim_id"],
                    "claim_version": commitment["claim_version"],
                    "description": requirement["description"],
                    "experiment_id": requirement.get("experiment_id"),
                    "plan_version_id": requirement.get("plan_version_id"),
                },
            )
        return {"mission": mission.model_dump(), "evaluation_event": event}

    async def prepare_evaluation_result_proposal(
        self,
        branch_id: str,
        data: PlanningEvaluationResultProposalPrepare,
    ) -> dict[str, Any]:
        """Prepare a conflict-safe native result unit from exact located evidence."""
        from rka.models.semantic_patch import (
            ArgumentSpineReplaceOperation,
            SemanticPatchProposalCreate,
        )
        from rka.services.manuscript_native import NativeManuscriptService
        from rka.services.semantic_patch import SemanticPatchService

        async with self.db.transaction():
            branch, artifact, commitment = await self._require_selected_evaluation_commitment(
                branch_id=branch_id,
                expected_branch_revision=data.expected_branch_revision,
                artifact_id=data.artifact_id,
                expected_artifact_version=data.expected_artifact_version,
                commitment_key=data.commitment_key,
            )
            if branch.get("manuscript_id") and branch["manuscript_id"] != data.manuscript_id:
                raise ValueError("result target must match the branch manuscript context")
            await self._assert_no_evaluation_action(
                artifact_version_id=str(artifact["version"]["id"]),
                commitment_key=data.commitment_key,
                requirement_key=None,
                action="result_unit_proposal_prepared",
            )
            events = await self.list_evaluation_events(branch_id)
            projected = await self._project_evaluation_commitment(
                branch=branch,
                artifact=artifact,
                commitment=commitment,
                events=events,
            )
            if projected["verdict"] == "Blocked":
                raise ValueError(
                    "result proposal is blocked: " + "; ".join(projected["blockers"])
                )
            located = [
                observation
                for requirement in projected["requirements"]
                for observation in requirement["observations"]
                if observation["observation"] is not None
                and observation["locators"]
                and observation["binding"]["outcome"]
                in {"supports", "partially_supports", "fails_to_support"}
            ]
            if not located:
                raise ValueError("result proposal requires conclusive, exactly located evidence")
            self._require_claim_aligned_result(located)
            artifact_row = None
            if data.artifact_ref.startswith("art_"):
                artifact_row = await self.db.fetchone(
                    """SELECT id, extraction_status, content_hash FROM artifacts
                        WHERE id = ? AND project_id = ?""",
                    [data.artifact_ref, self.project_id],
                )
            else:
                artifact_row = await self.db.fetchone(
                    """SELECT figure.id, artifact.extraction_status, artifact.content_hash
                         FROM figures AS figure
                         JOIN artifacts AS artifact ON artifact.id = figure.artifact_id
                        WHERE figure.id = ? AND artifact.project_id = ?""",
                    [data.artifact_ref, self.project_id],
                )
            if (
                artifact_row is None
                or artifact_row["extraction_status"] != "complete"
                or not artifact_row["content_hash"]
            ):
                raise ValueError(
                    "result artifact must be a same-project complete art_ or fig_ with a content hash"
                )

            manuscript = NativeManuscriptService(self.db, project_id=self.project_id)
            current = await manuscript.get(data.manuscript_id)
            if current is None:
                raise ValueError(f"manuscript {data.manuscript_id!r} not found")
            if int(current.revision) != data.expected_manuscript_revision:
                raise PlanningConflictError(
                    "manuscript revision changed before result proposal preparation"
                )
            spine = await manuscript.export_spine_projection(data.manuscript_id)
            claims = list(spine.get("claims") or [])
            units = list(spine.get("units") or [])
            claim_spec = next(
                (
                    item
                    for item in claims
                    if item.get("rka_manuscript_claim_id") == commitment["claim_id"]
                    and int(item.get("version") or 0) == int(commitment["claim_version"])
                ),
                None,
            )
            if claim_spec is None:
                raise PlanningConflictError("the exact evaluated claim is no longer current")
            unit_links = list(claim_spec.get("unit_links") or [])
            unit_links = [
                link
                for link in unit_links
                if link.get("unit_key") != data.result_unit_local_key
            ]
            unit_links.append(
                {"unit_key": data.result_unit_local_key, "relationship": "tests"}
            )
            claim_spec["unit_links"] = unit_links

            existing_unit = next(
                (
                    item
                    for item in units
                    if (item.get("unit_id") or item.get("local_key"))
                    == data.result_unit_local_key
                ),
                None,
            )
            sequence = (
                int(existing_unit.get("sequence") or 0)
                if existing_unit
                else max((int(item.get("sequence") or 0) for item in units), default=0) + 10
            )
            result_spec = {
                "unit_id": data.result_unit_local_key,
                "kind": "result",
                "location": data.location,
                "title": data.title,
                "artifact_ref": data.artifact_ref,
                "allowed_interpretation": commitment["allowed_interpretation"],
                "prohibited_interpretation": "; ".join(
                    commitment["prohibited_interpretation"]
                ),
                "sequence": sequence,
                "status": "planned",
                "evidence_ids": claim_spec.get("evidence_ids", []),
                "qualifier_ids": claim_spec.get("qualifier_ids", []),
                "counterevidence_ids": claim_spec.get("counterevidence_ids", []),
            }
            units = [
                result_spec
                if (item.get("unit_id") or item.get("local_key"))
                == data.result_unit_local_key
                else item
                for item in units
            ]
            if existing_unit is None:
                units.append(result_spec)
            proposal = await SemanticPatchService(
                self.db, project_id=self.project_id
            ).create_proposal(
                SemanticPatchProposalCreate(
                    origin="human",
                    intent=f"Create result unit for evaluation commitment {data.commitment_key}.",
                    reason=data.reason,
                    created_by=data.actor,
                    operations=[
                        ArgumentSpineReplaceOperation(
                            manuscript_id=data.manuscript_id,
                            expected_revision=data.expected_manuscript_revision,
                            spine={"claims": claims, "units": units},
                        )
                    ],
                )
            )
            observation_ids = [
                item["binding"]["observation_id"] for item in located
            ]
            locator_ids = [
                locator["id"] for item in located for locator in item["locators"]
            ]
            event = await self._insert_evaluation_event(
                branch=branch,
                artifact=artifact,
                commitment_key=data.commitment_key,
                requirement_key=None,
                action="result_unit_proposal_prepared",
                target_type="semantic_patch_proposal",
                target_id=str(proposal["id"]),
                target_version=None,
                proposal_id=str(proposal["id"]),
                mission_id=None,
                actor=data.actor,
                reason=data.reason,
                details={
                    "manuscript_id": data.manuscript_id,
                    "result_unit_local_key": data.result_unit_local_key,
                    "claim_id": commitment["claim_id"],
                    "claim_version": commitment["claim_version"],
                    "artifact_ref": data.artifact_ref,
                    "allowed_interpretation": commitment["allowed_interpretation"],
                    "prohibited_interpretation": commitment["prohibited_interpretation"],
                    "observation_ids": observation_ids,
                    "locator_ids": locator_ids,
                },
            )
        return {"proposal": proposal, "evaluation_event": event}

    @staticmethod
    def _require_claim_aligned_result(
        located: list[Mapping[str, Any]],
    ) -> None:
        """Prevent adverse evidence from being framed as support for the old claim.

        A narrowing or negative result is scientifically useful, but it must
        first revise or replace the manuscript claim and evaluation contract.
        Otherwise copying the old contract's allowed wording into a result
        unit would contradict the binding's explicit claim effect.
        """
        misaligned = [
            item
            for item in located
            if item["binding"]["claim_effect"] != "supports_as_worded"
        ]
        if misaligned:
            effects = sorted(
                {item["binding"]["claim_effect"] for item in misaligned}
            )
            raise ValueError(
                "result proposal requires evidence aligned with the current claim; "
                "revise or replace the claim and evaluation contract for: "
                + ", ".join(effect.replace("_", " ") for effect in effects)
            )

    async def record_evaluation_result_application(
        self,
        proposal_id: str,
        *,
        actor: str,
        reason: str,
    ) -> list[dict[str, Any]]:
        """Append exact result-unit lineage after an evaluation proposal applies."""
        prepared = await self.db.fetchall(
            """SELECT * FROM manuscript_evaluation_events
                WHERE project_id = ? AND proposal_id = ?
                  AND action = 'result_unit_proposal_prepared'""",
            [self.project_id, proposal_id],
        )
        events = []
        for row in prepared:
            item = dict(row)
            details = parse_json_field(item.get("details"), {})
            unit = await self.db.fetchone(
                """SELECT unit.*, manuscript.revision AS manuscript_revision
                     FROM manuscript_units AS unit
                     JOIN manuscripts AS manuscript
                       ON manuscript.id = unit.manuscript_id
                      AND manuscript.project_id = unit.project_id
                    WHERE unit.project_id = ? AND unit.manuscript_id = ?
                      AND unit.local_key = ?""",
                [
                    self.project_id,
                    details["manuscript_id"],
                    details["result_unit_local_key"],
                ],
            )
            if (
                unit is None
                or unit["kind"] != "result"
                or unit["artifact_ref"] != details["artifact_ref"]
                or unit["allowed_interpretation"] != details["allowed_interpretation"]
                or unit["prohibited_interpretation"]
                != "; ".join(details["prohibited_interpretation"])
            ):
                raise RuntimeError(
                    "applied evaluation proposal did not produce its exact bounded result unit"
                )
            artifact = await self._evaluation_artifact(item)
            branch = await self._require_branch(str(item["branch_id"]))
            events.append(
                await self._insert_evaluation_event(
                    branch=branch,
                    artifact=artifact,
                    commitment_key=str(item["commitment_key"]),
                    requirement_key=None,
                    action="result_unit_proposal_applied",
                    target_type="manuscript_unit",
                    target_id=str(unit["id"]),
                    target_version=int(unit["manuscript_revision"]),
                    proposal_id=proposal_id,
                    mission_id=None,
                    actor=actor,
                    reason=reason,
                    details={
                        **details,
                        "manuscript_revision": int(unit["manuscript_revision"]),
                    },
                )
            )
        return events

    async def _require_selected_evaluation_commitment(
        self,
        *,
        branch_id: str,
        expected_branch_revision: int,
        artifact_id: str,
        expected_artifact_version: int,
        commitment_key: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        branch = await self._require_branch(branch_id)
        if branch["state"] != "selected":
            raise ValueError("only the selected planning branch may create evaluation actions")
        if int(branch["revision"]) != expected_branch_revision:
            raise PlanningConflictError(
                f"planning branch revision conflict: expected {expected_branch_revision}, "
                f"found {branch['revision']}"
            )
        artifact = next(
            (
                item
                for item in await self._effective_artifacts(branch_id)
                if item["id"] == artifact_id and item["stage_type"] == "evaluation"
            ),
            None,
        )
        if artifact is None:
            raise PlanningNotFoundError(f"evaluation artifact {artifact_id!r} not found")
        version = artifact["version"]
        if int(version["version"]) != expected_artifact_version:
            raise PlanningConflictError(
                "planning artifact version changed before evaluation action"
            )
        if version["lifecycle"] != "selected" or version["readiness_state"] != "ready":
            raise ValueError("evaluation actions require a selected, ready artifact version")
        if version["unresolved_items"] or version["readiness_missing"]:
            raise ValueError("evaluation action is blocked by unresolved or missing items")
        findings = self._stage_contract_findings("evaluation", version)
        if findings:
            raise ValueError(
                "evaluation contract is not action-ready: " + "; ".join(findings)
            )
        commitment = next(
            (
                item
                for item in version["payload"].get("commitments", [])
                if item.get("local_key") == commitment_key
            ),
            None,
        )
        if commitment is None:
            raise PlanningNotFoundError(
                f"evaluation commitment {commitment_key!r} not found"
            )
        if commitment.get("disposition") != "selected":
            raise ValueError("evaluation commitment must be selected before canonical action")
        return branch, artifact, commitment

    async def _assert_no_evaluation_action(
        self,
        *,
        artifact_version_id: str,
        commitment_key: str,
        requirement_key: str | None,
        action: str,
    ) -> None:
        row = await self.db.fetchone(
            """SELECT id FROM manuscript_evaluation_events
                WHERE project_id = ? AND artifact_version_id = ?
                  AND commitment_key = ? AND requirement_key IS ? AND action = ?
                LIMIT 1""",
            [
                self.project_id,
                artifact_version_id,
                commitment_key,
                requirement_key,
                action,
            ],
        )
        if row is not None:
            raise PlanningConflictError(
                f"evaluation commitment already has a {action.replace('_', ' ')} event"
            )

    async def _evaluation_artifact(self, event: Mapping[str, Any]) -> dict[str, Any]:
        artifact = await self.db.fetchone(
            """SELECT * FROM manuscript_planning_artifacts
                WHERE id = ? AND project_id = ?""",
            [event["artifact_id"], self.project_id],
        )
        version = await self.db.fetchone(
            """SELECT * FROM manuscript_planning_artifact_versions
                WHERE id = ? AND artifact_id = ? AND project_id = ?""",
            [event["artifact_version_id"], event["artifact_id"], self.project_id],
        )
        if artifact is None or version is None:
            raise RuntimeError("evaluation source artifact is missing")
        result = dict(artifact)
        result["version"] = await self._version_row(version)
        return result

    async def _insert_evaluation_event(
        self,
        *,
        branch: Mapping[str, Any],
        artifact: Mapping[str, Any],
        commitment_key: str,
        requirement_key: str | None,
        action: str,
        target_type: str,
        target_id: str,
        target_version: int | None,
        proposal_id: str | None,
        mission_id: str | None,
        actor: str,
        reason: str,
        details: Mapping[str, Any],
    ) -> dict[str, Any]:
        event_id = generate_id("manuscript_evaluation_event")
        version = artifact["version"]
        await self.db.execute(
            """INSERT INTO manuscript_evaluation_events
               (id, project_id, branch_id, artifact_id, artifact_version_id,
                artifact_version, branch_revision, commitment_key,
                requirement_key, action, target_type, target_id, target_version,
                proposal_id, mission_id, actor, reason, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                event_id,
                self.project_id,
                branch["id"],
                artifact["id"],
                version["id"],
                version["version"],
                branch["revision"],
                commitment_key,
                requirement_key,
                action,
                target_type,
                target_id,
                target_version,
                proposal_id,
                mission_id,
                actor,
                reason,
                _canonical_json(dict(details)),
            ],
        )
        row = await self.db.fetchone(
            "SELECT * FROM manuscript_evaluation_events WHERE id = ?", [event_id]
        )
        result = dict(row)
        result["details"] = parse_json_field(result.get("details"), {})
        return result

    async def _require_selected_candidate(
        self,
        *,
        branch_id: str,
        expected_branch_revision: int,
        artifact_id: str,
        expected_artifact_version: int,
        candidate_kind: str,
        candidate_key: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        branch = await self._require_branch(branch_id)
        if branch["state"] != "selected":
            raise ValueError("only the selected planning branch may promote candidates")
        if int(branch["revision"]) != expected_branch_revision:
            raise PlanningConflictError(
                f"planning branch revision conflict: expected {expected_branch_revision}, "
                f"found {branch['revision']}"
            )
        artifact = next(
            (
                item
                for item in await self._effective_artifacts(branch_id)
                if item["id"] == artifact_id and item["stage_type"] == "rq_contribution"
            ),
            None,
        )
        if artifact is None:
            raise PlanningNotFoundError(
                f"RQ/contribution artifact {artifact_id!r} not found on this branch"
            )
        version = artifact["version"]
        if int(version["version"]) != expected_artifact_version:
            raise PlanningConflictError(
                "planning artifact version changed before candidate promotion"
            )
        if version["lifecycle"] != "selected" or version["readiness_state"] != "ready":
            raise ValueError("candidate promotion requires a selected, ready artifact version")
        if version["unresolved_items"] or version["readiness_missing"]:
            raise ValueError("candidate promotion is blocked by unresolved or missing items")
        key = "research_questions" if candidate_kind == "research_question" else "contributions"
        candidate = next(
            (
                item
                for item in version["payload"].get(key, [])
                if isinstance(item, dict) and item.get("local_key") == candidate_key
            ),
            None,
        )
        if candidate is None:
            raise PlanningNotFoundError(
                f"{candidate_kind} candidate {candidate_key!r} not found"
            )
        if candidate.get("disposition") != "selected":
            raise ValueError("candidate must be selected before promotion")
        findings = self._stage_contract_findings("rq_contribution", version)
        if findings:
            raise ValueError("candidate portfolio is not promotion-ready: " + "; ".join(findings))
        return branch, artifact, candidate

    async def _assert_no_promotion_action(
        self,
        *,
        artifact_version_id: str,
        candidate_kind: str,
        candidate_key: str,
        action: str,
    ) -> None:
        row = await self.db.fetchone(
            """SELECT id FROM manuscript_planning_promotion_events
               WHERE project_id = ? AND artifact_version_id = ?
                 AND candidate_kind = ? AND candidate_key = ? AND action = ?
               LIMIT 1""",
            [
                self.project_id,
                artifact_version_id,
                candidate_kind,
                candidate_key,
                action,
            ],
        )
        if row is not None:
            raise PlanningConflictError(
                f"candidate already has a {action.replace('_', ' ')} event"
            )

    async def _promotion_artifact(self, event: Mapping[str, Any]) -> dict[str, Any]:
        artifact = await self.db.fetchone(
            """SELECT * FROM manuscript_planning_artifacts
               WHERE id = ? AND project_id = ?""",
            [event["artifact_id"], self.project_id],
        )
        version = await self.db.fetchone(
            """SELECT * FROM manuscript_planning_artifact_versions
               WHERE id = ? AND artifact_id = ? AND project_id = ?""",
            [event["artifact_version_id"], event["artifact_id"], self.project_id],
        )
        if artifact is None or version is None:
            raise RuntimeError("planning promotion source artifact is missing")
        result = dict(artifact)
        result["version"] = await self._version_row(version)
        return result

    async def _insert_promotion_event(
        self,
        *,
        branch: Mapping[str, Any],
        artifact: Mapping[str, Any],
        candidate_kind: str,
        candidate_key: str,
        action: str,
        target_type: str,
        target_id: str,
        target_version: int | None,
        proposal_id: str | None,
        decision_id: str | None,
        actor: str,
        reason: str,
        details: Mapping[str, Any],
    ) -> dict[str, Any]:
        event_id = generate_id("manuscript_planning_promotion_event")
        version = artifact["version"]
        await self.db.execute(
            """INSERT INTO manuscript_planning_promotion_events
               (id, project_id, branch_id, artifact_id, artifact_version_id,
                artifact_version, branch_revision, candidate_kind, candidate_key,
                action, target_type, target_id, target_version, proposal_id,
                decision_id, actor, reason, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                event_id,
                self.project_id,
                branch["id"],
                artifact["id"],
                version["id"],
                version["version"],
                branch["revision"],
                candidate_kind,
                candidate_key,
                action,
                target_type,
                target_id,
                target_version,
                proposal_id,
                decision_id,
                actor,
                reason,
                _canonical_json(dict(details)),
            ],
        )
        row = await self.db.fetchone(
            "SELECT * FROM manuscript_planning_promotion_events WHERE id = ?",
            [event_id],
        )
        result = dict(row)
        result["details"] = parse_json_field(result.get("details"), {})
        return result

    @staticmethod
    def _stage_contract_findings(stage: str, version: Mapping[str, Any]) -> list[str]:
        payload = version["payload"]
        bindings = version["evidence_bindings"]
        findings: list[str] = []
        if stage == "problem_scope" and not payload.get("out_of_scope"):
            findings.append("Excluded scope is not yet explicit")
        elif stage == "landscape_gap":
            literature_ids = {
                binding["entity_id"]
                for binding in bindings
                if binding["entity_type"] == "literature"
            }
            literature_ids.update(
                literature_id
                for row in payload.get("rows", [])
                for literature_id in row.get("literature_ids", [])
            )
            if not literature_ids:
                findings.append("The SOTA/gap framing has no literature binding")
        elif stage == "response_mechanism" and not payload.get("boundary_conditions"):
            findings.append("Mechanism boundary conditions are not explicit")
        elif stage == "challenge_innovation":
            pairs = payload.get("pairs", [])
            if any(not pair.get("local_key") for pair in pairs):
                findings.append("Challenge/innovation nodes need stable local keys")
            if any(not pair.get("required_evidence") for pair in pairs):
                findings.append("Each innovation needs a required-evidence statement")
        elif stage == "rq_contribution":
            rqs = [item for item in payload.get("research_questions", []) if isinstance(item, dict)]
            contributions = [
                item for item in payload.get("contributions", []) if isinstance(item, dict)
            ]
            if not any(item.get("disposition") == "selected" for item in rqs):
                findings.append("Select at least one bounded RQ candidate")
            selected_contributions = [
                item for item in contributions if item.get("disposition") == "selected"
            ]
            if not selected_contributions:
                findings.append("Select at least one bounded contribution candidate")
            if any(not item.get("support_ids") for item in selected_contributions):
                findings.append("Each selected contribution needs positive evidence")
            if any(item.get("missing_evidence") for item in selected_contributions):
                findings.append("Selected contributions still declare missing evidence")
        elif stage == "evaluation":
            commitments = payload.get("commitments", [])
            if any("local_key" not in item for item in commitments):
                findings.append("Legacy evaluation commitments require structured revision")
            selected_commitments = [
                item
                for item in commitments
                if item.get("local_key") and item.get("disposition") == "selected"
            ]
            if not selected_commitments:
                findings.append("Select at least one claim-centered evaluation commitment")
            for commitment in selected_commitments:
                for field_name in (
                    "baselines",
                    "metrics",
                    "conditions",
                    "success_criteria",
                    "failure_criteria",
                ):
                    if not commitment.get(field_name):
                        findings.append(
                            f"Evaluation commitment {commitment['local_key']} needs {field_name}"
                        )
                for requirement in commitment.get("requirements", []):
                    if requirement.get("required") and not requirement.get("acceptance_criteria"):
                        findings.append(
                            f"Requirement {requirement['local_key']} needs acceptance criteria"
                        )
                    if requirement.get("required") and not requirement.get("failure_criteria"):
                        findings.append(
                            f"Requirement {requirement['local_key']} needs failure criteria"
                        )
        return findings

    @staticmethod
    def _stage_next_action(
        stage: str,
        verdict: str,
        current: Mapping[str, Any] | None,
    ) -> str:
        if current is None:
            return f"Capture or choose a {_ARGUMENT_STAGE_LABELS[stage].lower()} artifact"
        if verdict == "Blocked":
            return "Resolve the blocking dependency or revise the upstream framing"
        if current["version"]["lifecycle"] != "selected":
            return "Select, combine, revise, or park the current alternatives"
        if verdict == "Needs review":
            return "Review evidence, assumptions, boundaries, and unresolved items"
        return "Continue to the next non-ready stage"

    async def _quick_reader_projection(
        self,
        *,
        branch: Mapping[str, Any],
        selected_heads: Mapping[str, dict[str, Any]],
    ) -> dict[str, Any]:
        slots: list[dict[str, Any]] = []
        discrepancies: list[dict[str, Any]] = []

        def add_slot(name: str, value: str | None, artifact: dict[str, Any] | None) -> None:
            if not value or artifact is None:
                return
            slots.append(
                {
                    "slot": name,
                    "text": value,
                    "authority": "provisional",
                    "source": self._comparison_ref(artifact),
                }
            )

        paragraph = selected_heads.get("paragraph_spine")
        paragraph_payload = paragraph["version"]["payload"] if paragraph else {}
        problem = selected_heads.get("problem_scope")
        landscape = selected_heads.get("landscape_gap")
        response = selected_heads.get("response_mechanism")
        challenge = selected_heads.get("challenge_innovation")
        rq_contribution = selected_heads.get("rq_contribution")

        add_slot(
            "problem",
            (problem["version"]["payload"].get("problem") if problem else None)
            or paragraph_payload.get("problem"),
            problem or paragraph,
        )
        add_slot(
            "gap",
            (landscape["version"]["payload"].get("gap") if landscape else None)
            or paragraph_payload.get("gap"),
            landscape or paragraph,
        )
        add_slot(
            "insight",
            (response["version"]["payload"].get("insight") if response else None)
            or paragraph_payload.get("insight"),
            response or paragraph,
        )
        add_slot("response", paragraph_payload.get("response"), paragraph)
        if challenge:
            pairs = challenge["version"]["payload"].get("pairs", [])
            text = " ".join(
                f"{pair['challenge']} -> {pair['innovation']}" for pair in pairs
            )
            add_slot("challenge_innovation", text, challenge)
        else:
            add_slot(
                "challenge_innovation",
                paragraph_payload.get("challenge_innovation"),
                paragraph,
            )

        if rq_contribution:
            payload = rq_contribution["version"]["payload"]
            selected_rqs = [
                item["question"]
                for item in payload.get("research_questions", [])
                if isinstance(item, dict) and item.get("disposition") == "selected"
            ]
            selected_contributions = [
                item["exact_wording"]
                for item in payload.get("contributions", [])
                if isinstance(item, dict) and item.get("disposition") == "selected"
            ]
            add_slot("research_questions", " ".join(selected_rqs), rq_contribution)
            add_slot("contributions", " ".join(selected_contributions), rq_contribution)

        add_slot("evidence_preview", paragraph_payload.get("evidence"), paragraph)
        add_slot("reader_payoff", paragraph_payload.get("payoff"), paragraph)

        comparisons = (
            ("problem", paragraph_payload.get("problem"), problem, "problem"),
            ("gap", paragraph_payload.get("gap"), landscape, "gap"),
            ("insight", paragraph_payload.get("insight"), response, "insight"),
        )
        for slot, paragraph_value, artifact, field in comparisons:
            current_value = artifact["version"]["payload"].get(field) if artifact else None
            if (
                paragraph_value
                and current_value
                and str(paragraph_value).strip() != str(current_value).strip()
            ):
                discrepancies.append(
                    {
                        "slot": slot,
                        "paragraph_value": paragraph_value,
                        "current_stage_value": current_value,
                        "current_stage_source": self._comparison_ref(artifact),
                    }
                )

        canonical_contributions: list[dict[str, Any]] = []
        if branch.get("manuscript_id"):
            from rka.services.manuscript_native import NativeManuscriptService

            context = await NativeManuscriptService(
                self.db, project_id=self.project_id
            ).get_context(str(branch["manuscript_id"]))
            for claim in context.get("claims", []):
                if claim.get("state") != "active":
                    continue
                version = int(claim["version"])
                exact = claim.get("exact_wording")
                ratified = any(
                    item.get("claim_version") == version
                    and item.get("decision_status") == "active"
                    and item.get("decided_by") == "pi"
                    and not item.get("superseded_by")
                    and item.get("chosen") == exact
                    for item in claim.get("ratifications", [])
                )
                canonical_contributions.append(
                    {
                        "claim_id": claim["id"],
                        "local_key": claim["local_key"],
                        "version": version,
                        "exact_wording": exact,
                        "ratified": ratified,
                    }
                )

        return {
            "slots": slots,
            "canonical_contributions": canonical_contributions,
            "discrepancies": discrepancies,
            "llm_generated": False,
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
