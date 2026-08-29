"""Interpretation Staging lifecycle and explicit claim promotion."""

from __future__ import annotations

import json
from typing import Any

from rka.infra.ids import generate_id
from rka.models.claim import ClaimCreate, ClaimScopeCondition, ClaimScopeWrite
from rka.models.interpretation import (
    InterpretationCandidate,
    InterpretationCandidateCreate,
    InterpretationCandidateDetail,
    InterpretationHint,
    InterpretationHintCreate,
    InterpretationPromotion,
    InterpretationReviewEvent,
    InterpretationTriage,
)
from rka.services.base import BaseService, _precise_now
from rka.services.claims import ClaimService


class InterpretationNotFoundError(ValueError):
    """The candidate is absent from the active project."""


class InterpretationConflictError(ValueError):
    """The caller's expected revision or requested transition is stale."""


class InterpretationService(BaseService):
    """Manage candidate interpretation without conflating it with evidence."""

    _SOURCE_TABLES = {
        "journal": "journal",
        "literature": "literature",
        "artifact": "artifacts",
        "experiment_observation": "experiment_observations",
    }
    _DISPOSITION_BY_ACTION = {
        "merge": "merged",
        "defer": "deferred",
        "reject": "rejected",
        "classify_decision": "classified_decision",
        "classify_plan": "classified_plan",
        "classify_author_intent": "classified_author_intent",
        "request_evidence_mission": "evidence_mission_requested",
    }

    async def create(self, data: InterpretationCandidateCreate) -> InterpretationCandidate:
        await self._require_source(data.source_type, data.source_id)
        await self._validate_locator_grounding(data)
        candidate_id = generate_id("interpretation_candidate")
        now = _precise_now()
        async with self.db.transaction():
            await self.db.execute(
                """INSERT INTO interpretation_candidates (
                       id, project_id, source_type, source_id, locator_kind,
                       locator_start, locator_end, locator_value, statement,
                       epistemic_kind, scope_conditions, uncertainty,
                       uncertainty_note, falsifier, proposed_claim_type,
                       created_by, extraction_tool, extraction_model,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    candidate_id,
                    self.project_id,
                    data.source_type,
                    data.source_id,
                    data.locator_kind,
                    data.locator_start,
                    data.locator_end,
                    data.locator_value,
                    data.statement,
                    data.epistemic_kind,
                    json.dumps(data.scope_conditions),
                    data.uncertainty,
                    data.uncertainty_note,
                    data.falsifier,
                    data.proposed_claim_type,
                    data.created_by,
                    data.extraction_tool,
                    data.extraction_model,
                    now,
                    now,
                ],
            )
            await self.add_link(
                "interpretation_candidate",
                candidate_id,
                "derived_from",
                data.source_type,
                data.source_id,
                created_by=data.created_by,
            )
            await self._append_event(
                candidate_id,
                action="created",
                from_status=None,
                to_status="pending",
                actor=data.created_by,
                candidate_revision=1,
                target_type=data.source_type,
                target_id=data.source_id,
            )
            await self.audit(
                "create",
                "interpretation_candidate",
                candidate_id,
                self._audit_actor(data.created_by),
                {"source_type": data.source_type, "source_id": data.source_id},
            )
        candidate = await self.get(candidate_id)
        assert candidate is not None
        return candidate

    async def get(self, candidate_id: str) -> InterpretationCandidate | None:
        row = await self._candidate_row(candidate_id)
        return self._row_to_candidate(row) if row else None

    async def get_detail(self, candidate_id: str) -> InterpretationCandidateDetail | None:
        row = await self._candidate_row(candidate_id)
        if row is None:
            return None
        hints = await self.db.fetchall(
            """SELECT * FROM interpretation_candidate_hints
               WHERE candidate_id = ? AND project_id = ?
               ORDER BY kind, confidence DESC, created_at, id""",
            [candidate_id, self.project_id],
        )
        events = await self.db.fetchall(
            """SELECT * FROM interpretation_review_events
               WHERE candidate_id = ? AND project_id = ?
               ORDER BY created_at, id""",
            [candidate_id, self.project_id],
        )
        promotions = await self.db.fetchall(
            """SELECT * FROM interpretation_promotions
               WHERE candidate_id = ? AND project_id = ?
               ORDER BY promoted_at, id""",
            [candidate_id, self.project_id],
        )
        return InterpretationCandidateDetail(
            **self._row_to_candidate(row).model_dump(),
            hints=[InterpretationHint(**dict(item)) for item in hints],
            review_events=[InterpretationReviewEvent(**dict(item)) for item in events],
            promotions=[InterpretationPromotion(**dict(item)) for item in promotions],
        )

    async def list(
        self,
        *,
        review_status: str | None = None,
        disposition: str | None = None,
        epistemic_kind: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InterpretationCandidate]:
        conditions = ["c.project_id = ?"]
        params: list[Any] = [self.project_id]
        for column, value in (
            ("review_status", review_status),
            ("disposition", disposition),
            ("epistemic_kind", epistemic_kind),
            ("source_type", source_type),
            ("source_id", source_id),
        ):
            if value is not None:
                conditions.append(f"c.{column} = ?")
                params.append(value)
        params.extend([limit, offset])
        rows = await self.db.fetchall(
            f"""{self._candidate_select()}
                WHERE {" AND ".join(conditions)}
                ORDER BY CASE c.review_status
                    WHEN 'in_review' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
                    c.created_at ASC, c.id ASC
                LIMIT ? OFFSET ?""",
            params,
        )
        return [self._row_to_candidate(row) for row in rows]

    async def add_hint(
        self,
        candidate_id: str,
        data: InterpretationHintCreate,
    ) -> InterpretationCandidateDetail:
        if candidate_id == data.related_candidate_id:
            raise ValueError("a candidate cannot hint against itself")
        hint_id = generate_id("interpretation_hint")
        async with self.db.transaction():
            source = await self._require_candidate_revision(candidate_id, data.expected_revision)
            target = await self._candidate_row(data.related_candidate_id)
            if target is None:
                raise InterpretationNotFoundError(
                    "related candidate is not available in this project"
                )
            await self.db.execute(
                """INSERT INTO interpretation_candidate_hints (
                       id, project_id, candidate_id, related_candidate_id,
                       kind, confidence, rationale, created_by
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    hint_id,
                    self.project_id,
                    candidate_id,
                    data.related_candidate_id,
                    data.kind,
                    data.confidence,
                    data.rationale.strip(),
                    data.created_by,
                ],
            )
            new_revision = int(source["revision"]) + 1
            await self._update_candidate_revision_only(
                candidate_id, data.expected_revision, new_revision
            )
            await self._append_event(
                candidate_id,
                action="hint_added",
                from_status=source["review_status"],
                to_status=source["review_status"],
                actor=data.created_by,
                reason=data.rationale.strip(),
                target_type="interpretation_candidate",
                target_id=data.related_candidate_id,
                candidate_revision=new_revision,
            )
            await self.audit(
                "update",
                "interpretation_candidate",
                candidate_id,
                self._audit_actor(data.created_by),
                {"operation": "add_hint", "hint_id": hint_id, "kind": data.kind},
            )
        detail = await self.get_detail(candidate_id)
        assert detail is not None
        return detail

    async def triage(
        self,
        candidate_id: str,
        data: InterpretationTriage,
    ) -> InterpretationCandidateDetail:
        async with self.db.transaction():
            row = await self._require_candidate_revision(candidate_id, data.expected_revision)
            if data.action == "start_review":
                self._require_status(row, {"pending"}, data.action)
                await self._transition(row, data, status="in_review", disposition=None)
            elif data.action == "promote":
                self._require_status(row, {"pending", "in_review"}, data.action)
                await self._promote(row, data)
            elif data.action == "revoke_promotion":
                self._require_status(row, {"resolved"}, data.action)
                if row["disposition"] != "promoted":
                    raise InterpretationConflictError(
                        "only a promoted candidate can revoke its promotion"
                    )
                await self._revoke_promotion(row, data)
            elif data.action == "classify_evidence":
                self._require_status(row, {"pending", "in_review"}, data.action)
                await self._classify_evidence(row, data)
            elif data.action == "revoke_evidence":
                self._require_status(row, {"resolved"}, data.action)
                if row["disposition"] != "classified_evidence":
                    raise InterpretationConflictError(
                        "only classified evidence can revoke its claim relation"
                    )
                await self._revoke_evidence(row, data)
            elif data.action == "reopen":
                self._require_status(row, {"resolved"}, data.action)
                admitted = await self.db.fetchone(
                    """SELECT id FROM source_admissions
                       WHERE candidate_id = ? AND project_id = ?""",
                    [row["id"], self.project_id],
                )
                if admitted is not None:
                    raise InterpretationConflictError(
                        "an admitted registered-source interpretation is final and cannot be reopened"
                    )
                if row["disposition"] == "classified_evidence":
                    raise InterpretationConflictError(
                        "classified evidence must use revoke_evidence before reopening"
                    )
                await self._transition(
                    row,
                    data,
                    status="pending",
                    disposition=None,
                    target_type=None,
                    target_id=None,
                )
            else:
                self._require_status(row, {"pending", "in_review"}, data.action)
                await self._apply_disposition(row, data)
        detail = await self.get_detail(candidate_id)
        assert detail is not None
        return detail

    async def _apply_disposition(self, row: dict, data: InterpretationTriage) -> None:
        disposition = self._DISPOSITION_BY_ACTION[data.action]
        target_type = None
        target_id = None
        if data.action == "merge":
            if data.target_candidate_id == row["id"]:
                raise ValueError("a candidate cannot merge into itself")
            target = await self._candidate_row(data.target_candidate_id or "")
            if target is None:
                raise InterpretationNotFoundError("merge target is not available in this project")
            target_type = "interpretation_candidate"
            target_id = data.target_candidate_id
        elif data.action == "request_evidence_mission":
            target_type = "mission"
            target_id = data.target_entity_id
            if target_id:
                await self._require_entity("missions", target_id)
        elif data.action == "classify_decision":
            target_type = "decision"
            target_id = data.target_entity_id
            if target_id:
                await self._require_entity("decisions", target_id)
        elif data.action == "classify_plan":
            target_type = "plan"
            target_id = data.target_entity_id
        elif data.action == "classify_author_intent":
            target_type = "author_intent"
            target_id = data.target_entity_id
        await self._transition(
            row,
            data,
            status="resolved",
            disposition=disposition,
            target_type=target_type,
            target_id=target_id,
        )

    async def _promote(self, row: dict, data: InterpretationTriage) -> None:
        if row["source_type"] != "journal":
            raise ValueError(
                "M1 promotion requires a journal-backed candidate; preserve "
                "literature/artifact candidates until generalized grounding is available"
            )
        if not row.get("proposed_claim_type"):
            raise ValueError("promotion requires proposed_claim_type")
        active = await self.db.fetchone(
            """SELECT id FROM interpretation_promotions
               WHERE candidate_id = ? AND project_id = ? AND status = 'active'""",
            [row["id"], self.project_id],
        )
        if active:
            raise InterpretationConflictError("candidate already has an active promotion")

        claim_service = ClaimService(
            self.db,
            embeddings=self.embeddings,
            project_id=self.project_id,
        )
        claim = await claim_service.create(
            ClaimCreate(
                source_entry_id=row["source_id"],
                claim_type=row["proposed_claim_type"],
                content=row["statement"],
                confidence=data.claim_confidence,
                verified=True,
                evidence_status="unassessed",
                source_offset_start=(
                    row["locator_start"] if row["locator_kind"] == "text_offset" else None
                ),
                source_offset_end=(
                    row["locator_end"] if row["locator_kind"] == "text_offset" else None
                ),
            ),
            actor=data.actor,
        )
        source_conditions = json.loads(row.get("scope_conditions") or "[]")
        await claim_service.append_scope(
            claim.id,
            ClaimScopeWrite(
                expected_revision=0,
                actor=data.actor,
                reason=(
                    f"Transferred source-bounded fields from {row['id']} during "
                    f"explicit promotion: {data.reason}"
                ),
                conditions=[
                    ClaimScopeCondition(
                        kind="other",
                        key="source_condition",
                        operator="described_by",
                        value=condition,
                    )
                    for condition in source_conditions
                    if isinstance(condition, str) and condition.strip()
                ],
                uncertainty=row.get("uncertainty") or "unknown",
                uncertainty_note=row.get("uncertainty_note"),
                falsifier_status=("applicable" if row.get("falsifier") else "unknown"),
                falsifier=row.get("falsifier"),
                review_status="draft",
                source_candidate_id=row["id"],
            ),
        )
        promotion_id = generate_id("interpretation_promotion")
        await self.db.execute(
            """INSERT INTO interpretation_promotions (
                   id, project_id, candidate_id, claim_id, promoted_by,
                   promotion_reason
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            [
                promotion_id,
                self.project_id,
                row["id"],
                claim.id,
                data.actor,
                data.reason,
            ],
        )
        await self.add_link(
            "claim",
            claim.id,
            "derived_from",
            "interpretation_candidate",
            row["id"],
            created_by=data.actor,
        )
        await self._transition(
            row,
            data,
            status="resolved",
            disposition="promoted",
            target_type="claim",
            target_id=claim.id,
        )

    async def _revoke_promotion(self, row: dict, data: InterpretationTriage) -> None:
        promotion = await self.db.fetchone(
            """SELECT * FROM interpretation_promotions
               WHERE candidate_id = ? AND project_id = ? AND status = 'active'""",
            [row["id"], self.project_id],
        )
        if promotion is None:
            raise InterpretationConflictError("candidate has no active promotion to revoke")
        now = _precise_now()
        await self.db.execute(
            """UPDATE interpretation_promotions
               SET status = 'revoked', revoked_by = ?, revocation_reason = ?,
                   revoked_at = ?
               WHERE id = ? AND project_id = ? AND status = 'active'""",
            [data.actor, data.reason, now, promotion["id"], self.project_id],
        )
        await self.db.execute(
            """UPDATE claims SET stale = 1, updated_at = ?
               WHERE id = ? AND project_id = ?""",
            [now, promotion["claim_id"], self.project_id],
        )
        await self._transition(
            row,
            data,
            status="pending",
            disposition=None,
            target_type="claim",
            target_id=promotion["claim_id"],
        )

    async def _classify_evidence(
        self,
        row: dict,
        data: InterpretationTriage,
    ) -> None:
        """Resolve one observation interpretation as a reviewed claim relation."""
        if row["source_type"] != "experiment_observation":
            raise ValueError(
                "classify_evidence requires an experiment_observation source"
            )
        claim_id = data.target_entity_id or ""
        await self._require_entity("claims", claim_id)
        active = await self.db.fetchone(
            """SELECT id FROM claim_evidence_relations
               WHERE candidate_id = ? AND project_id = ?""",
            [row["id"], self.project_id],
        )
        if active is not None:
            raise InterpretationConflictError(
                "candidate already has a claim evidence relation"
            )

        relation_id = generate_id("claim_evidence_relation")
        await self.db.execute(
            """INSERT INTO claim_evidence_relations (
                   id, project_id, claim_id, observation_id, candidate_id,
                   role, reviewed_by, review_reason
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                relation_id,
                self.project_id,
                claim_id,
                row["source_id"],
                row["id"],
                data.evidence_role,
                data.actor,
                data.reason,
            ],
        )
        await self._transition(
            row,
            data,
            status="resolved",
            disposition="classified_evidence",
            target_type="claim",
            target_id=claim_id,
        )
        await self.audit(
            "create",
            "claim_evidence_relation",
            relation_id,
            data.actor,
            {
                "candidate_id": row["id"],
                "observation_id": row["source_id"],
                "claim_id": claim_id,
                "role": data.evidence_role,
            },
        )

    async def _revoke_evidence(
        self,
        row: dict,
        data: InterpretationTriage,
    ) -> None:
        relation = await self.db.fetchone(
            """SELECT * FROM claim_evidence_relations
               WHERE candidate_id = ? AND project_id = ? AND status = 'active'""",
            [row["id"], self.project_id],
        )
        if relation is None:
            raise InterpretationConflictError(
                "candidate has no active claim evidence relation to revoke"
            )
        now = _precise_now()
        await self.db.execute(
            """UPDATE claim_evidence_relations
               SET status = 'revoked', revoked_by = ?, revocation_reason = ?,
                   revoked_at = ?
               WHERE id = ? AND project_id = ? AND status = 'active'""",
            [data.actor, data.reason, now, relation["id"], self.project_id],
        )
        await self._transition(
            row,
            data,
            status="pending",
            disposition=None,
            target_type="claim",
            target_id=relation["claim_id"],
        )
        await self.audit(
            "update",
            "claim_evidence_relation",
            relation["id"],
            data.actor,
            {"operation": "revoke", "reason": data.reason},
        )

    async def _transition(
        self,
        row: dict,
        data: InterpretationTriage,
        *,
        status: str,
        disposition: str | None,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> None:
        new_revision = int(row["revision"]) + 1
        now = _precise_now()
        reviewed = status == "resolved"
        cursor = await self.db.execute(
            """UPDATE interpretation_candidates
               SET review_status = ?, disposition = ?, disposition_reason = ?,
                   disposition_target_type = ?, disposition_target_id = ?,
                   reviewed_by = ?, reviewed_at = ?, revision = ?, updated_at = ?
               WHERE id = ? AND project_id = ? AND revision = ?""",
            [
                status,
                disposition,
                data.reason if reviewed else None,
                target_type,
                target_id,
                data.actor if reviewed else None,
                now if reviewed else None,
                new_revision,
                now,
                row["id"],
                self.project_id,
                data.expected_revision,
            ],
        )
        if cursor.rowcount != 1:
            raise InterpretationConflictError(
                "candidate revision changed; reload before applying review"
            )
        await self._append_event(
            row["id"],
            action=data.action,
            from_status=row["review_status"],
            to_status=status,
            disposition=disposition,
            actor=data.actor,
            reason=data.reason,
            target_type=target_type,
            target_id=target_id,
            candidate_revision=new_revision,
        )
        await self.audit(
            "update",
            "interpretation_candidate",
            row["id"],
            data.actor,
            {
                "operation": data.action,
                "from_status": row["review_status"],
                "to_status": status,
                "disposition": disposition,
                "target_type": target_type,
                "target_id": target_id,
                "revision": new_revision,
            },
        )

    async def _candidate_row(self, candidate_id: str) -> dict | None:
        return await self.db.fetchone(
            f"""{self._candidate_select()}
                WHERE c.id = ? AND c.project_id = ?""",
            [candidate_id, self.project_id],
        )

    @staticmethod
    def _candidate_select() -> str:
        return """SELECT c.*,
                   (SELECT COUNT(*) FROM interpretation_candidate_hints h
                    WHERE h.project_id = c.project_id
                      AND h.candidate_id = c.id AND h.kind = 'duplicate')
                       AS duplicate_hint_count,
                   (SELECT COUNT(*) FROM interpretation_candidate_hints h
                    WHERE h.project_id = c.project_id
                      AND h.candidate_id = c.id AND h.kind = 'conflict')
                       AS conflict_hint_count,
                   (SELECT p.claim_id FROM interpretation_promotions p
                    WHERE p.project_id = c.project_id
                      AND p.candidate_id = c.id AND p.status = 'active'
                    LIMIT 1) AS active_claim_id
                FROM interpretation_candidates c"""

    async def _require_source(self, source_type: str, source_id: str) -> None:
        table = self._SOURCE_TABLES[source_type]
        await self._require_entity(table, source_id)

    async def _validate_locator_grounding(self, data: InterpretationCandidateCreate) -> None:
        """Reject journal offsets that cannot identify a real source span."""
        if data.source_type == "experiment_observation":
            if data.locator_kind != "record" or data.locator_value != "full_record":
                raise ValueError(
                    "experiment_observation candidates require record: full_record"
                )
            return
        if data.source_type != "journal" or data.locator_kind != "text_offset":
            return
        row = await self.db.fetchone(
            "SELECT content FROM journal WHERE id = ? AND project_id = ?",
            [data.source_id, self.project_id],
        )
        content = (row or {}).get("content") or ""
        start = data.locator_start
        end = data.locator_end
        if start is None or start >= len(content):
            raise ValueError("text_offset locator_start is outside the journal content")
        if end is not None and (end <= start or end > len(content)):
            raise ValueError(
                "text_offset locator_end must be after locator_start and within journal content"
            )

    async def _require_entity(self, table: str, entity_id: str) -> None:
        row = await self.db.fetchone(
            f"SELECT 1 FROM {table} WHERE id = ? AND project_id = ?",
            [entity_id, self.project_id],
        )
        if row is None:
            raise InterpretationNotFoundError(
                f"{table} source/target is not available in this project"
            )

    async def _require_candidate_revision(self, candidate_id: str, revision: int) -> dict:
        row = await self._candidate_row(candidate_id)
        if row is None:
            raise InterpretationNotFoundError(
                f"interpretation candidate {candidate_id!r} not found"
            )
        if int(row["revision"]) != revision:
            raise InterpretationConflictError(
                f"candidate revision is {row['revision']}, not expected {revision}"
            )
        return row

    @staticmethod
    def _require_status(row: dict, allowed: set[str], action: str) -> None:
        if row["review_status"] not in allowed:
            expected = " or ".join(sorted(allowed))
            raise InterpretationConflictError(
                f"{action} requires candidate status {expected}; "
                f"current status is {row['review_status']}"
            )

    async def _update_candidate_revision_only(
        self, candidate_id: str, expected_revision: int, new_revision: int
    ) -> None:
        cursor = await self.db.execute(
            """UPDATE interpretation_candidates
               SET revision = ?, updated_at = ?
               WHERE id = ? AND project_id = ? AND revision = ?""",
            [
                new_revision,
                _precise_now(),
                candidate_id,
                self.project_id,
                expected_revision,
            ],
        )
        if cursor.rowcount != 1:
            raise InterpretationConflictError(
                "candidate revision changed; reload before adding hint"
            )

    async def _append_event(
        self,
        candidate_id: str,
        *,
        action: str,
        from_status: str | None,
        to_status: str,
        actor: str,
        candidate_revision: int,
        disposition: str | None = None,
        reason: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> None:
        await self.db.execute(
            """INSERT INTO interpretation_review_events (
                   id, project_id, candidate_id, action, from_status, to_status,
                   disposition, actor, reason, target_type, target_id,
                   candidate_revision
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                generate_id("interpretation_review"),
                self.project_id,
                candidate_id,
                action,
                from_status,
                to_status,
                disposition,
                actor,
                reason,
                target_type,
                target_id,
                candidate_revision,
            ],
        )

    @staticmethod
    def _audit_actor(actor: str) -> str:
        return "system" if actor == "import" else actor

    @staticmethod
    def _row_to_candidate(row: dict) -> InterpretationCandidate:
        raw_scope = row.get("scope_conditions") or "[]"
        try:
            scope = json.loads(raw_scope) if isinstance(raw_scope, str) else raw_scope
        except json.JSONDecodeError:
            scope = []
        return InterpretationCandidate(
            **{key: value for key, value in dict(row).items() if key != "scope_conditions"},
            scope_conditions=scope if isinstance(scope, list) else [],
        )
