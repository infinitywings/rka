"""Mission lifecycle service."""

from __future__ import annotations

import json

from rka.infra.ids import generate_id
from rka.models.mission import (
    Mission, MissionCreate, MissionUpdate, MissionTask,
    MissionReport, MissionReportCreate,
)
from rka.models.journal import JournalEntryCreate
from rka.services.base import BaseService, _now


class MissionService(BaseService):
    """Manages mission lifecycle."""

    async def create(self, data: MissionCreate, actor: str = "brain") -> Mission:
        """Create a new mission."""
        mis_id = generate_id("mission")

        tasks_json = None
        if data.tasks:
            tasks_json = json.dumps([t.model_dump() for t in data.tasks])

        await self.db.execute(
            """INSERT INTO missions
               (id, phase, objective, tasks, context, acceptance_criteria,
                scope_boundaries, checkpoint_triggers, depends_on)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                mis_id, data.phase, data.objective, tasks_json,
                data.context, data.acceptance_criteria,
                data.scope_boundaries, data.checkpoint_triggers,
                data.depends_on,
            ],
        )
        await self.db.commit()

        # Save tags (user-provided or auto-generated)
        tags = data.tags
        if not tags:
            auto_tags = await self._auto_enrich_tags(data.objective, [])
            if auto_tags:
                tags = auto_tags
        if tags:
            await self._set_tags("mission", mis_id, tags)

        # Sync FTS5 + embedding indexes
        await self._sync_indexes("mission", mis_id, {
            "objective": data.objective, "context": data.context,
        })

        await self.emit_event(
            event_type="mission_created",
            entity_type="mission",
            entity_id=mis_id,
            actor=actor,
            summary=f"Mission: {data.objective[:100]}",
            phase=data.phase,
        )
        await self.audit("create", "mission", mis_id, actor)
        return await self.get(mis_id)

    async def get(self, mis_id: str | None = None) -> Mission | None:
        """Get a mission. If no ID, return the currently active mission."""
        if mis_id:
            row = await self.db.fetchone("SELECT * FROM missions WHERE id = ?", [mis_id])
        else:
            row = await self.db.fetchone(
                "SELECT * FROM missions WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
            )
        if row is None:
            return None
        return await self._row_to_model(row)

    async def list(
        self,
        phase: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Mission]:
        """List missions with filters."""
        conditions = []
        params = []

        if phase:
            conditions.append("phase = ?")
            params.append(phase)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        rows = await self.db.fetchall(
            f"SELECT * FROM missions WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        return [await self._row_to_model(row) for row in rows]

    async def update(self, mis_id: str, data: MissionUpdate, actor: str = "executor") -> Mission:
        """Update a mission (status, tasks)."""
        updates = {}

        if data.status is not None:
            updates["status"] = data.status
            if data.status in ("complete", "partial"):
                updates["completed_at"] = _now()

        if data.tasks is not None:
            updates["tasks"] = json.dumps([t.model_dump() for t in data.tasks])

        if data.objective is not None:
            updates["objective"] = data.objective

        if not updates:
            return await self.get(mis_id)

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [mis_id]

        await self.db.execute(f"UPDATE missions SET {set_clause} WHERE id = ?", values)
        await self.db.commit()

        # Emit events for status changes
        if data.status:
            event_type_map = {
                "complete": "mission_completed",
                "blocked": "mission_blocked",
            }
            event_type = event_type_map.get(data.status, "status_updated")
            await self.emit_event(
                event_type=event_type,
                entity_type="mission",
                entity_id=mis_id,
                actor=actor,
                summary=f"Mission status → {data.status}",
            )

        # Re-sync FTS5 + embedding on content changes
        if "objective" in updates:
            row = await self.db.fetchone("SELECT objective, context FROM missions WHERE id = ?", [mis_id])
            if row:
                await self._sync_indexes("mission", mis_id, dict(row))

        await self.audit("update", "mission", mis_id, actor, {"fields": list(updates.keys())})
        return await self.get(mis_id)

    async def submit_report(
        self, mis_id: str, data: MissionReportCreate, actor: str = "executor"
    ) -> Mission:
        """Submit an execution report for a mission."""
        report = MissionReport(
            mission_id=mis_id,
            tasks_completed=data.tasks_completed,
            findings=data.findings,
            anomalies=data.anomalies,
            questions=data.questions,
            codebase_state=data.codebase_state,
            recommended_next=data.recommended_next,
            submitted_at=_now(),
        )

        await self.db.execute(
            "UPDATE missions SET report = ?, status = 'complete', completed_at = ? WHERE id = ?",
            [report.model_dump_json(), _now(), mis_id],
        )
        await self.db.commit()

        await self.emit_event(
            event_type="mission_completed",
            entity_type="mission",
            entity_id=mis_id,
            actor=actor,
            summary=f"Report submitted with {len(data.findings or [])} findings",
        )
        await self.audit("update", "mission", mis_id, actor, {"action": "submit_report"})

        # Auto-materialize report sections as first-class journal entries
        # so outcomes are searchable, indexable, and visible in the research map.
        mission = await self.get(mis_id)
        phase = mission.phase if mission else None
        await self._materialize_report(mis_id, phase, data, actor)

        return await self.get(mis_id)

    async def _materialize_report(
        self,
        mis_id: str,
        phase: str | None,
        data: MissionReportCreate,
        actor: str,
    ) -> None:
        """Create journal entries from each section of a mission report.

        Uses NoteService so entries get auto-tags, auto-links, FTS indexing,
        and events — exactly as if the Executor had called rka_add_note manually.
        Deduplication: skips creation if an identical content+mission entry exists.
        """
        # Lazy import to avoid circular dependency
        from rka.services.notes import NoteService

        note_svc = NoteService(self.db, llm=self.llm, embeddings=self.embeddings)

        async def _create(note_type: str, text: str, confidence: str = "hypothesis") -> None:
            text = text.strip()
            if not text:
                return
            # Deduplicate: skip if identical content already linked to this mission
            existing = await self.db.fetchone(
                "SELECT id FROM journal WHERE related_mission = ? AND content = ?",
                [mis_id, text],
            )
            if existing:
                return
            note_in = JournalEntryCreate(
                type=note_type,
                content=text,
                source=actor,
                phase=phase,
                related_mission=mis_id,
                confidence=confidence,
            )
            await note_svc.create(note_in, actor=actor)

        for finding in data.findings or []:
            await _create("finding", finding, confidence="tested")

        for anomaly in data.anomalies or []:
            await _create("observation", anomaly, confidence="hypothesis")

        for question in data.questions or []:
            await _create("pi_instruction", question, confidence="hypothesis")

        if data.recommended_next:
            await _create("idea", data.recommended_next, confidence="hypothesis")

    async def get_report(self, mis_id: str | None = None) -> MissionReport | None:
        """Get report for a mission. Defaults to latest complete mission."""
        if mis_id:
            row = await self.db.fetchone(
                "SELECT report FROM missions WHERE id = ?", [mis_id]
            )
        else:
            row = await self.db.fetchone(
                "SELECT report FROM missions WHERE status = 'complete' ORDER BY completed_at DESC LIMIT 1"
            )
        if not row or not row.get("report"):
            return None
        return MissionReport.model_validate_json(row["report"])

    async def _row_to_model(self, row: dict) -> Mission:
        tags = await self._get_tags("mission", row["id"])

        tasks = None
        if row.get("tasks"):
            raw = self._json_loads(row["tasks"], [])
            tasks = [MissionTask(**t) for t in raw]

        report = None
        if row.get("report"):
            try:
                report = MissionReport.model_validate_json(row["report"])
            except Exception:
                pass

        return Mission(
            id=row["id"],
            phase=row["phase"],
            objective=row["objective"],
            tasks=tasks,
            context=row.get("context"),
            acceptance_criteria=row.get("acceptance_criteria"),
            scope_boundaries=row.get("scope_boundaries"),
            checkpoint_triggers=row.get("checkpoint_triggers"),
            status=row["status"],
            depends_on=row.get("depends_on"),
            report=report,
            tags=tags,
            created_at=row.get("created_at"),
            completed_at=row.get("completed_at"),
        )
