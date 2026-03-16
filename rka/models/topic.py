"""Topic and entity-topic models (v2.0)."""

from __future__ import annotations

from pydantic import BaseModel


class TopicCreate(BaseModel):
    """Create a new topic."""

    name: str
    parent_id: str | None = None
    description: str | None = None


class TopicUpdate(BaseModel):
    """Partial update for a topic."""

    name: str | None = None
    parent_id: str | None = None
    description: str | None = None


class Topic(BaseModel):
    """Full topic record from database."""

    id: str
    name: str
    parent_id: str | None = None
    description: str | None = None
    project_id: str = "proj_default"
    created_at: str | None = None
    children: list[Topic] | None = None


class EntityTopicAssignment(BaseModel):
    """Assign an entity to a topic."""

    topic_id: str
    entity_type: str
    entity_id: str
    assigned_by: str = "llm"
