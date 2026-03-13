"""Decision tree service."""

from __future__ import annotations

import json
from collections import defaultdict

from rka.infra.ids import generate_id
from rka.models.decision import (
    Decision, DecisionCreate, DecisionUpdate, DecisionOption, DecisionTreeNode,
)
from rka.services.base import BaseService, _now


class DecisionService(BaseService):
    """Manages the decision tree."""

    async def create(self, data: DecisionCreate, actor: str | None = None) -> Decision:
        """Create a new decision node."""
        dec_id = generate_id("decision")
        actor_val = actor or data.decided_by

        options_json = None
        if data.options:
            options_json = json.dumps([o.model_dump() for o in data.options])

        await self.db.execute(
            """INSERT INTO decisions
               (id, parent_id, phase, question, options, chosen, rationale,
                decided_by, status, related_missions, related_literature, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                dec_id, data.parent_id, data.phase, data.question,
                options_json, data.chosen, data.rationale,
                data.decided_by, data.status,
                self._json_dumps(data.related_missions),
                self._json_dumps(data.related_literature),
                self.project_id,
            ],
        )
        await self.db.commit()

        # Save tags (user-provided or auto-generated)
        tags = data.tags
        if not tags:
            auto_tags = await self._auto_enrich_tags(data.question, [])
            if auto_tags:
                tags = auto_tags
        if tags:
            await self._set_tags("decision", dec_id, tags)

        # Sync FTS5 + embedding indexes
        await self._sync_indexes("decision", dec_id, {
            "question": data.question, "rationale": data.rationale,
        })

        await self.emit_event(
            event_type="decision_created",
            entity_type="decision",
            entity_id=dec_id,
            actor=actor_val,
            summary=f"Decision: {data.question[:100]}",
            phase=data.phase,
        )
        await self.audit("create", "decision", dec_id, actor_val)
        return await self.get(dec_id)

    async def get(self, dec_id: str) -> Decision | None:
        """Get a single decision by ID."""
        row = await self.db.fetchone(
            "SELECT * FROM decisions WHERE id = ? AND project_id = ?",
            [dec_id, self.project_id],
        )
        if row is None:
            return None
        return await self._row_to_model(row)

    async def list(
        self,
        phase: str | None = None,
        status: str | None = None,
        parent_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Decision]:
        """List decisions with filters."""
        conditions = []
        params = [self.project_id]

        conditions.append("project_id = ?")

        if phase:
            conditions.append("phase = ?")
            params.append(phase)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if parent_id is not None:
            if parent_id == "":
                conditions.append("parent_id IS NULL")
            else:
                conditions.append("parent_id = ?")
                params.append(parent_id)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        rows = await self.db.fetchall(
            f"SELECT * FROM decisions WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        return [await self._row_to_model(row) for row in rows]

    async def update(self, dec_id: str, data: DecisionUpdate, actor: str = "system") -> Decision:
        """Update a decision."""
        dump = data.model_dump(exclude_none=True)
        tags = dump.pop("tags", None)

        updates = {}
        for field, value in dump.items():
            if field == "options":
                updates[field] = json.dumps([o.model_dump() for o in value])
            elif field in ("related_missions", "related_literature"):
                updates[field] = self._json_dumps(value)
            else:
                updates[field] = value

        if tags is not None:
            await self._set_tags("decision", dec_id, tags)

        if not updates:
            return await self.get(dec_id)

        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [dec_id]

        await self.db.execute(
            f"UPDATE decisions SET {set_clause} WHERE id = ? AND project_id = ?",
            values + [self.project_id],
        )
        await self.db.commit()

        # Emit event for status changes
        if data.status:
            event_type = {
                "abandoned": "decision_abandoned",
            }.get(data.status, "decision_updated")
            await self.emit_event(
                event_type=event_type,
                entity_type="decision",
                entity_id=dec_id,
                actor=actor,
                summary=f"Decision updated: status → {data.status}",
            )

        # Re-sync FTS5 + embedding on content changes
        if "question" in updates or "rationale" in updates:
            row = await self.db.fetchone(
                "SELECT question, rationale FROM decisions WHERE id = ? AND project_id = ?",
                [dec_id, self.project_id],
            )
            if row:
                await self._sync_indexes("decision", dec_id, dict(row))

        await self.audit("update", "decision", dec_id, actor, {"fields": list(updates.keys())})
        return await self.get(dec_id)

    async def get_tree(self, phase: str | None = None, active_only: bool = False) -> list[DecisionTreeNode]:
        """Build the decision tree as nested nodes."""
        conditions = ["project_id = ?"]
        params = [self.project_id]
        if phase:
            conditions.append("phase = ?")
            params.append(phase)
        if active_only:
            conditions.append("status = 'active'")

        where = " AND ".join(conditions) if conditions else "1=1"
        rows = await self.db.fetchall(
            f"SELECT id, parent_id, question, status, chosen, phase FROM decisions WHERE {where} ORDER BY created_at",
            params,
        )

        # Build tree from flat list
        nodes_by_id = {}
        children_map = defaultdict(list)

        for row in rows:
            node = DecisionTreeNode(
                id=row["id"],
                question=row["question"],
                status=row["status"],
                chosen=row.get("chosen"),
                phase=row["phase"],
            )
            nodes_by_id[row["id"]] = node
            parent = row.get("parent_id")
            if parent:
                children_map[parent].append(row["id"])

        # Attach children
        for parent_id, child_ids in children_map.items():
            if parent_id in nodes_by_id:
                nodes_by_id[parent_id].children = [
                    nodes_by_id[cid] for cid in child_ids if cid in nodes_by_id
                ]

        # Return root nodes (no parent)
        roots = [
            nodes_by_id[row["id"]]
            for row in rows
            if not row.get("parent_id") or row["parent_id"] not in nodes_by_id
        ]
        return roots

    async def _row_to_model(self, row: dict) -> Decision:
        tags = await self._get_tags("decision", row["id"])
        options = None
        if row.get("options"):
            raw = self._json_loads(row["options"], [])
            options = [DecisionOption(**o) for o in raw]

        return Decision(
            id=row["id"],
            parent_id=row.get("parent_id"),
            phase=row["phase"],
            question=row["question"],
            options=options,
            chosen=row.get("chosen"),
            rationale=row.get("rationale"),
            decided_by=row["decided_by"],
            status=row["status"],
            abandonment_reason=row.get("abandonment_reason"),
            related_missions=self._json_loads(row.get("related_missions")),
            related_literature=self._json_loads(row.get("related_literature")),
            tags=tags,
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
