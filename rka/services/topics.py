"""Hierarchical topic management service (v2.0)."""

from __future__ import annotations

from rka.infra.ids import generate_id
from rka.models.topic import Topic, TopicCreate, TopicUpdate, EntityTopicAssignment
from rka.services.base import BaseService, _now


class TopicService(BaseService):
    """Manages hierarchical topics and entity-to-topic assignments."""

    # ── CRUD ─────────────────────────────────────────────────

    async def create(self, data: TopicCreate) -> Topic:
        topic_id = generate_id("topic")
        await self.db.execute(
            """INSERT INTO topics (id, name, parent_id, description, project_id)
               VALUES (?, ?, ?, ?, ?)""",
            [topic_id, data.name, data.parent_id, data.description, self.project_id],
        )
        await self.db.commit()
        await self.audit("create", "topic", topic_id, "system")
        return await self.get(topic_id)

    async def get(self, topic_id: str) -> Topic | None:
        row = await self.db.fetchone(
            "SELECT * FROM topics WHERE id = ? AND project_id = ?",
            [topic_id, self.project_id],
        )
        if row is None:
            return None
        return Topic(
            id=row["id"],
            name=row["name"],
            parent_id=row.get("parent_id"),
            description=row.get("description"),
            project_id=row.get("project_id", "proj_default"),
            created_at=row.get("created_at"),
        )

    async def list(self, parent_id: str | None = "__unset__", limit: int = 100, offset: int = 0) -> list[Topic]:
        conditions = ["project_id = ?"]
        params: list = [self.project_id]

        if parent_id != "__unset__":
            if parent_id is None:
                conditions.append("parent_id IS NULL")
            else:
                conditions.append("parent_id = ?")
                params.append(parent_id)

        where = " AND ".join(conditions)
        params.extend([limit, offset])

        rows = await self.db.fetchall(
            f"SELECT * FROM topics WHERE {where} ORDER BY name LIMIT ? OFFSET ?",
            params,
        )
        return [
            Topic(
                id=r["id"], name=r["name"], parent_id=r.get("parent_id"),
                description=r.get("description"), project_id=r.get("project_id", "proj_default"),
                created_at=r.get("created_at"),
            )
            for r in rows
        ]

    async def update(self, topic_id: str, data: TopicUpdate) -> Topic:
        dump = data.model_dump(exclude_none=True)
        if not dump:
            return await self.get(topic_id)

        set_clause = ", ".join(f"{k} = ?" for k in dump)
        values = list(dump.values()) + [topic_id, self.project_id]

        await self.db.execute(
            f"UPDATE topics SET {set_clause} WHERE id = ? AND project_id = ?",
            values,
        )
        await self.db.commit()
        return await self.get(topic_id)

    async def delete(self, topic_id: str) -> bool:
        await self.db.execute(
            "DELETE FROM entity_topics WHERE topic_id = ?", [topic_id],
        )
        await self.db.execute(
            "DELETE FROM topics WHERE id = ? AND project_id = ?",
            [topic_id, self.project_id],
        )
        await self.db.commit()
        return True

    # ── Assignments ──────────────────────────────────────────

    async def assign_entity(self, topic_id: str, entity_type: str, entity_id: str, assigned_by: str = "llm") -> None:
        await self.db.execute(
            """INSERT OR IGNORE INTO entity_topics (topic_id, entity_type, entity_id, assigned_by)
               VALUES (?, ?, ?, ?)""",
            [topic_id, entity_type, entity_id, assigned_by],
        )
        await self.db.commit()

    async def get_entity_topics(self, entity_type: str, entity_id: str) -> list[Topic]:
        rows = await self.db.fetchall(
            """SELECT t.* FROM topics t
               JOIN entity_topics et ON et.topic_id = t.id
               WHERE et.entity_type = ? AND et.entity_id = ? AND t.project_id = ?""",
            [entity_type, entity_id, self.project_id],
        )
        return [
            Topic(
                id=r["id"], name=r["name"], parent_id=r.get("parent_id"),
                description=r.get("description"), project_id=r.get("project_id", "proj_default"),
                created_at=r.get("created_at"),
            )
            for r in rows
        ]

    async def get_topic_tree(self) -> list[dict]:
        """Get full topic tree as nested dicts."""
        topics = await self.list(parent_id="__unset__", limit=500)
        by_parent: dict[str | None, list[Topic]] = {}
        for t in topics:
            by_parent.setdefault(t.parent_id, []).append(t)

        def _build(parent_id: str | None) -> list[dict]:
            children = by_parent.get(parent_id, [])
            return [
                {
                    "id": t.id, "name": t.name, "description": t.description,
                    "children": _build(t.id),
                }
                for t in children
            ]

        return _build(None)
