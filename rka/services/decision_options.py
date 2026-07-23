"""DecisionOptionsService — CRUD + pareto filter + PI-selection recording on
the v2.2 decision_options table (migration 017).

Scope: data-layer only. Pareto *filtering* is a SQL query
(``WHERE dominated_by IS NULL``); the actual dominance *computation* is
Brain-side logic that lives in Phase 1B-ii. This service just reads/writes
the column.
"""

from __future__ import annotations

import json
from typing import Iterable

from rka.infra.ids import generate_id
from rka.models.decision_option import (
    DecisionOption,
    DecisionOptionCreate,
    EvidenceRef,
)
from rka.services.base import BaseService, _now


def _row_to_model(row: dict) -> DecisionOption:
    """Deserialize a SQLite row dict into a DecisionOption domain model."""
    return DecisionOption(
        id=row["id"],
        decision_id=row["decision_id"],
        project_id=row["project_id"],
        label=row["label"],
        summary=row["summary"],
        justification=row["justification"],
        expert_archetype=row["expert_archetype"],
        explanation=row["explanation"],
        pros=json.loads(row["pros"]),
        cons=json.loads(row["cons"]),
        evidence=[EvidenceRef(**e) for e in json.loads(row["evidence"])],
        confidence_verbal=row["confidence_verbal"],
        confidence_numeric=row["confidence_numeric"],
        confidence_evidence_strength=row["confidence_evidence_strength"],
        confidence_known_unknowns=json.loads(row["confidence_known_unknowns"]),
        effort_time=row["effort_time"],
        effort_cost=row["effort_cost"],
        effort_reversibility=row["effort_reversibility"],
        dominated_by=row["dominated_by"],
        presentation_order_seed=row["presentation_order_seed"],
        is_recommended=bool(row["is_recommended"]),
        created_at=row["created_at"],
    )


class DecisionOptionsService(BaseService):
    """CRUD + pareto filter + PI-selection recording on decision_options."""

    async def _require_owned_decision(self, decision_id: str) -> dict:
        """Return a decision only when it belongs to the active project."""
        decision = await self.db.fetchone(
            """SELECT id FROM decisions
               WHERE id = ? AND project_id = ?""",
            [decision_id, self.project_id],
        )
        if decision is None:
            raise ValueError(
                f"decision {decision_id!r} not found in project "
                f"{self.project_id}"
            )
        return decision

    async def _require_owned_option(self, option_id: str) -> dict:
        """Return an option only when it belongs to the active project."""
        option = await self.db.fetchone(
            """SELECT id, decision_id FROM decision_options
               WHERE id = ? AND project_id = ?""",
            [option_id, self.project_id],
        )
        if option is None:
            raise ValueError(
                f"decision_option {option_id!r} not found in project "
                f"{self.project_id}"
            )
        return option

    # ------------------------------------------------------------------ create

    async def create(
        self,
        decision_id: str,
        option: DecisionOptionCreate,
    ) -> DecisionOption:
        """Insert one decision_options row and return the created model."""
        opt_id = generate_id("decision_option")
        async with self.db.transaction():
            await self._require_owned_decision(decision_id)
            await self.db.execute(
                """INSERT INTO decision_options
                   (id, decision_id, project_id, label, summary, justification,
                    expert_archetype, explanation, pros, cons, evidence,
                    confidence_verbal, confidence_numeric,
                    confidence_evidence_strength,
                    confidence_known_unknowns, effort_time, effort_cost,
                    effort_reversibility, presentation_order_seed,
                    is_recommended)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                [
                    opt_id,
                    decision_id,
                    self.project_id,
                    option.label,
                    option.summary,
                    option.justification,
                    option.expert_archetype,
                    option.explanation,
                    json.dumps(option.pros),
                    json.dumps(option.cons),
                    json.dumps([e.model_dump() for e in option.evidence]),
                    option.confidence_verbal,
                    option.confidence_numeric,
                    option.confidence_evidence_strength,
                    json.dumps(option.confidence_known_unknowns),
                    option.effort_time,
                    option.effort_cost,
                    option.effort_reversibility,
                    option.presentation_order_seed,
                ],
            )
            created = await self.get(opt_id)
            if created is None:  # pragma: no cover - guards impossible DB drift
                raise RuntimeError("created decision option was not readable")
            return created

    async def create_bulk(
        self,
        decision_id: str,
        options: list[DecisionOptionCreate],
    ) -> list[DecisionOption]:
        """Insert multiple options transactionally (typical: 3 at presentation)."""
        created_ids: list[str] = []
        async with self.db.transaction():
            await self._require_owned_decision(decision_id)
            for option in options:
                opt_id = generate_id("decision_option")
                await self.db.execute(
                    """INSERT INTO decision_options
                       (id, decision_id, project_id, label, summary, justification,
                        expert_archetype, explanation, pros, cons, evidence,
                        confidence_verbal, confidence_numeric,
                        confidence_evidence_strength,
                        confidence_known_unknowns, effort_time, effort_cost,
                        effort_reversibility, presentation_order_seed,
                        is_recommended)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                    [
                        opt_id,
                        decision_id,
                        self.project_id,
                        option.label,
                        option.summary,
                        option.justification,
                        option.expert_archetype,
                        option.explanation,
                        json.dumps(option.pros),
                        json.dumps(option.cons),
                        json.dumps([e.model_dump() for e in option.evidence]),
                        option.confidence_verbal,
                        option.confidence_numeric,
                        option.confidence_evidence_strength,
                        json.dumps(option.confidence_known_unknowns),
                        option.effort_time,
                        option.effort_cost,
                        option.effort_reversibility,
                        option.presentation_order_seed,
                    ],
                )
                created_ids.append(opt_id)
            created: list[DecisionOption] = []
            for option_id in created_ids:
                option = await self.get(option_id)
                if option is None:  # pragma: no cover - impossible after insert
                    raise RuntimeError(
                        "created decision option was not readable"
                    )
                created.append(option)
            return created

    # ------------------------------------------------------------------- read

    async def list_for_decision(self, decision_id: str) -> list[DecisionOption]:
        """Return all options for a decision ordered by presentation_order_seed."""
        rows = await self.db.fetchall(
            """SELECT * FROM decision_options
               WHERE decision_id = ? AND project_id = ?
               ORDER BY presentation_order_seed ASC, created_at ASC""",
            [decision_id, self.project_id],
        )
        return [_row_to_model(r) for r in rows]

    async def get(self, option_id: str) -> DecisionOption | None:
        """Fetch a single option by ID (scoped to the service's project)."""
        row = await self.db.fetchone(
            "SELECT * FROM decision_options WHERE id = ? AND project_id = ?",
            [option_id, self.project_id],
        )
        return _row_to_model(row) if row else None

    # --------------------------------------------------------- dominated_by

    async def set_dominated_by(
        self,
        option_id: str,
        dominator_id: str | None,
    ) -> None:
        """Set or clear decision_options.dominated_by.

        Raises ValueError on self-reference.
        """
        if dominator_id is not None and dominator_id == option_id:
            raise ValueError(
                f"decision_option {option_id} cannot dominate itself"
            )
        async with self.db.transaction():
            target = await self._require_owned_option(option_id)
            if dominator_id is not None:
                dominator = await self._require_owned_option(dominator_id)
                if dominator["decision_id"] != target["decision_id"]:
                    raise ValueError(
                        f"decision_option {dominator_id!r} cannot dominate "
                        f"{option_id!r}: options belong to different decisions"
                    )
            cursor = await self.db.execute(
                """UPDATE decision_options SET dominated_by = ?
                   WHERE id = ? AND project_id = ?""",
                [dominator_id, option_id, self.project_id],
            )
            if cursor.rowcount != 1:  # pragma: no cover - protected by write lock
                raise ValueError(
                    f"decision_option {option_id!r} not found in project "
                    f"{self.project_id}"
                )

    # --------------------------------------------------------- pareto filter

    async def pareto_filter(
        self,
        options: Iterable[DecisionOption],
    ) -> list[DecisionOption]:
        """Return only options with dominated_by IS NULL.

        NOTE: this is a filter, not a computation. The dominance assignment
        (which option dominates which) is Brain-side logic that lives in
        Phase 1B-ii. This method exists so callers that have the options
        already in hand can prune without another DB round-trip.
        """
        return [opt for opt in options if opt.dominated_by is None]

    # ------------------------------------------------------ mark_recommended

    async def mark_recommended(self, option_id: str) -> None:
        """Atomically mark an option as recommended.

        Clears any other is_recommended=1 row on the same decision in the
        same transaction, and updates decisions.recommended_option_id to
        point at the new recommendation.
        """
        async with self.db.transaction():
            target = await self._require_owned_option(option_id)
            await self._require_owned_decision(target["decision_id"])
            # Clear previous recommendations for this decision.
            await self.db.execute(
                """UPDATE decision_options
                   SET is_recommended = 0
                   WHERE decision_id = ? AND project_id = ?
                     AND is_recommended = 1""",
                [target["decision_id"], self.project_id],
            )
            # Mark target.
            target_cursor = await self.db.execute(
                """UPDATE decision_options SET is_recommended = 1
                   WHERE id = ? AND decision_id = ? AND project_id = ?""",
                [option_id, target["decision_id"], self.project_id],
            )
            if target_cursor.rowcount != 1:
                raise ValueError(
                    f"decision_option {option_id!r} not found in project "
                    f"{self.project_id}"
                )
            # Mirror onto the decisions row. Advance updated_at so downstream
            # readers see the recommendation change. See
            # mis_01KQMWG5DADXY6TB3CKYKJZ583.
            decision_cursor = await self.db.execute(
                "UPDATE decisions SET recommended_option_id = ?, updated_at = ? "
                "WHERE id = ? AND project_id = ?",
                [
                    option_id,
                    _now(),
                    target["decision_id"],
                    self.project_id,
                ],
            )
            if decision_cursor.rowcount != 1:
                raise ValueError(
                    f"decision {target['decision_id']!r} not found in project "
                    f"{self.project_id}"
                )

    # --------------------------------------------------- record_pi_selection

    async def record_pi_selection(
        self,
        decision_id: str,
        selected_option_id: str | None,
        override_rationale: str | None,
    ) -> None:
        """Persist the PI's selection on the decisions row.

        At least one of ``selected_option_id`` or ``override_rationale`` must
        be set. Both may be set together when the PI selects an option AND
        provides a rationale (typical override-of-recommendation case).
        Neither set raises ``ValueError`` — that's the decision still being
        open, which is the pre-selection default and doesn't need a write.
        """
        has_selected = selected_option_id is not None and selected_option_id != ""
        has_override = override_rationale is not None and override_rationale.strip() != ""
        if not has_selected and not has_override:
            raise ValueError(
                "record_pi_selection: at least one of selected_option_id or "
                "override_rationale must be set"
            )
        async with self.db.transaction():
            await self._require_owned_decision(decision_id)
            if has_selected:
                # Verify the referenced option exists within this project and
                # belongs to the decision being ratified.
                opt = await self._require_owned_option(
                    selected_option_id  # type: ignore[arg-type]
                )
                if opt["decision_id"] != decision_id:
                    raise ValueError(
                        f"selected_option_id {selected_option_id!r} not found "
                        f"on decision {decision_id}"
                    )
            # Advance updated_at so downstream readers (change feeds,
            # staleness propagation) see the PI ratification.
            # See mis_01KQMWG5DADXY6TB3CKYKJZ583.
            cursor = await self.db.execute(
                """UPDATE decisions
                   SET pi_selected_option_id = ?,
                       pi_override_rationale = ?,
                       updated_at = ?
                   WHERE id = ? AND project_id = ?""",
                [
                    selected_option_id if has_selected else None,
                    override_rationale if has_override else None,
                    _now(),
                    decision_id,
                    self.project_id,
                ],
            )
            if cursor.rowcount != 1:  # pragma: no cover - protected by write lock
                raise ValueError(
                    f"decision {decision_id!r} not found in project "
                    f"{self.project_id}"
                )
