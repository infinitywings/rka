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
from rka.services.jobs import JobQueue


class MissionService(BaseService):
    """Manages mission lifecycle."""

    def _job_dedupe_key(self, mis_id: str, operation: str) -> str:
        return f"{self.project_id}:mission:{mis_id}:{operation}"

    async def _enqueue_enrichment_jobs(
        self,
        mis_id: str,
        *,
        include_auto_tags: bool,
        include_embedding: bool,
    ) -> None:
        queue = JobQueue(self.db)
        if include_auto_tags:
            await queue.enqueue(
                "mission_auto_tag",
                project_id=self.project_id,
                entity_type="mission",
                entity_id=mis_id,
                dedupe_key=self._job_dedupe_key(mis_id, "auto_tag"),
            )
        if include_embedding:
            await queue.enqueue(
                "mission_embed",
                project_id=self.project_id,
                entity_type="mission",
                entity_id=mis_id,
                dedupe_key=self._job_dedupe_key(mis_id, "embed"),
            )

    async def create(self, data: MissionCreate, actor: str = "brain") -> Mission:
        """Create a new mission."""
        mis_id = generate_id("mission")

        tasks_json = None
        if data.tasks:
            tasks_json = json.dumps([t.model_dump() for t in data.tasks])

        await self.db.execute(
            """INSERT INTO missions
               (id, phase, objective, tasks, context, acceptance_criteria,
                scope_boundaries, checkpoint_triggers, depends_on,
                motivated_by_decision, role_id, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                mis_id, data.phase, data.objective, tasks_json,
                data.context, data.acceptance_criteria,
                data.scope_boundaries, data.checkpoint_triggers,
                data.depends_on, data.motivated_by_decision,
                data.role_id, self.project_id,
            ],
        )
        await self.db.commit()

        # Write entity_link for motivated_by_decision
        if data.motivated_by_decision:
            await self.add_link(
                "decision", data.motivated_by_decision,
                "motivated", "mission", mis_id,
                created_by=actor,
            )

        # Save user-provided tags immediately. Derived tags are eventual.
        tags = data.tags
        if tags:
            await self._set_tags("mission", mis_id, tags)

        # Keep cheap deterministic FTS updates synchronous; derived enrichment is queued.
        await self._sync_fts(
            "mission",
            mis_id,
            {"objective": data.objective, "context": data.context},
        )
        await self._enqueue_enrichment_jobs(
            mis_id,
            include_auto_tags=bool(self.llm) and not tags,
            include_embedding=bool(self.embeddings),
        )

        await self.emit_event(
            event_type="mission_created",
            entity_type="mission",
            entity_id=mis_id,
            actor=actor,
            summary=f"Mission: {data.objective[:100]}",
            phase=data.phase,
        )
        # v2.1: fan-out routed role event
        await self._fanout_role_event(
            "mission.created",
            "mission", mis_id,
            source_role_id=data.role_id,
            payload={"objective": data.objective[:200]},
        )
        await self.audit("create", "mission", mis_id, actor)
        return await self.get(mis_id)

    async def get(self, mis_id: str | None = None) -> Mission | None:
        """Get a mission. If no ID, return the currently active mission."""
        if mis_id:
            row = await self.db.fetchone(
                "SELECT * FROM missions WHERE id = ? AND project_id = ?",
                [mis_id, self.project_id],
            )
        else:
            row = await self.db.fetchone(
                "SELECT * FROM missions WHERE project_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
                [self.project_id],
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
        params = [self.project_id]

        conditions.append("project_id = ?")

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

        await self.db.execute(
            f"UPDATE missions SET {set_clause} WHERE id = ? AND project_id = ?",
            values + [self.project_id],
        )
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

        # Re-sync cheap FTS now; defer embeddings and optional tag enrichment.
        if "objective" in updates:
            row = await self.db.fetchone(
                "SELECT objective, context FROM missions WHERE id = ? AND project_id = ?",
                [mis_id, self.project_id],
            )
            if row:
                await self._sync_fts("mission", mis_id, dict(row))
                await self._enqueue_enrichment_jobs(
                    mis_id,
                    include_auto_tags=bool(self.llm),
                    include_embedding=bool(self.embeddings),
                )

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
            "UPDATE missions SET report = ?, status = 'complete', completed_at = ? WHERE id = ? AND project_id = ?",
            [report.model_dump_json(), _now(), mis_id, self.project_id],
        )
        await self.db.commit()

        await self.emit_event(
            event_type="mission_completed",
            entity_type="mission",
            entity_id=mis_id,
            actor=actor,
            summary=f"Report submitted with {len(data.findings or [])} findings",
        )
        # v2.1: fan-out routed role event
        await self._fanout_role_event(
            "report.submitted",
            "mission", mis_id,
            payload={"findings_count": len(data.findings or [])},
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

        note_svc = NoteService(
            self.db,
            llm=self.llm,
            embeddings=self.embeddings,
            project_id=self.project_id,
        )

        async def _create(note_type: str, text: str, confidence: str = "hypothesis") -> None:
            text = text.strip()
            if not text:
                return
            # Deduplicate: skip if identical content already linked to this mission
            existing = await self.db.fetchone(
                "SELECT id FROM journal WHERE related_mission = ? AND content = ? AND project_id = ?",
                [mis_id, text, self.project_id],
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
            await _create("note", finding, confidence="tested")

        for anomaly in data.anomalies or []:
            await _create("note", anomaly, confidence="hypothesis")

        for question in data.questions or []:
            await _create("directive", question, confidence="hypothesis")

        if data.recommended_next:
            await _create("note", data.recommended_next, confidence="hypothesis")

    async def get_report(self, mis_id: str | None = None) -> MissionReport | None:
        """Get report for a mission. Defaults to latest complete mission."""
        if mis_id:
            row = await self.db.fetchone(
                "SELECT report FROM missions WHERE id = ? AND project_id = ?",
                [mis_id, self.project_id],
            )
        else:
            row = await self.db.fetchone(
                "SELECT report FROM missions WHERE project_id = ? AND status = 'complete' ORDER BY completed_at DESC LIMIT 1",
                [self.project_id],
            )
        if not row or not row.get("report"):
            return None
        return MissionReport.model_validate_json(row["report"])

    async def _row_to_model(self, row: dict) -> Mission:
        tags = await self._get_tags("mission", row["id"])
        enrichment_status = await self._get_enrichment_status("mission", row["id"])

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
            iteration=row.get("iteration", 1),
            parent_mission_id=row.get("parent_mission_id"),
            motivated_by_decision=row.get("motivated_by_decision"),
            tags=tags,
            enrichment_status=enrichment_status,
            role_id=row.get("role_id"),
            created_at=row.get("created_at"),
            completed_at=row.get("completed_at"),
        )

    async def process_auto_tag_job(self, mis_id: str) -> dict[str, str | int]:
        """Generate tags for an existing mission when none are present."""
        row = await self.db.fetchone(
            "SELECT objective FROM missions WHERE id = ? AND project_id = ?",
            [mis_id, self.project_id],
        )
        if row is None:
            return {"outcome": "missing"}
        if not self.llm:
            return {"outcome": "skipped", "reason": "llm_disabled"}

        existing_tags = await self._get_tags("mission", mis_id)
        if existing_tags:
            return {"outcome": "skipped", "reason": "tags_present"}

        auto_tags = await self._auto_enrich_tags(row["objective"], existing_tags)
        if not auto_tags:
            return {"outcome": "noop"}

        await self._set_tags("mission", mis_id, auto_tags)
        return {"outcome": "updated", "tag_count": len(auto_tags)}

    async def process_embedding_job(self, mis_id: str) -> dict[str, str | int]:
        """Generate or refresh the mission embedding."""
        row = await self.db.fetchone(
            "SELECT objective, context FROM missions WHERE id = ? AND project_id = ?",
            [mis_id, self.project_id],
        )
        if row is None:
            return {"outcome": "missing"}
        if not self.embeddings:
            return {"outcome": "skipped", "reason": "embeddings_disabled"}

        parts = [str(row.get("objective") or "").strip(), str(row.get("context") or "").strip()]
        text = " ".join(part for part in parts if part).strip()
        if not text:
            return {"outcome": "skipped", "reason": "empty"}

        await self.embeddings.embed_and_store("mission", mis_id, text, project_id=self.project_id)
        return {"outcome": "updated", "char_count": len(text)}
