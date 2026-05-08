"""Topic and entity-topic models (v2.0)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TopicCreate(BaseModel):
    """Create a new topic.

    extra="forbid" defense-in-depth — see Mission C
    (mis_01KR43RX9KY11GAPTPPGK9XSDE) for context.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    parent_id: str | None = None
    description: str | None = None


class TopicUpdate(BaseModel):
    """Partial update for a topic.

    extra="forbid": undeclared fields raise 422 instead of silently stripping.
    See mis_01KQJH9MB65AR0GSVPQBT8707X (silent-write-failure fix) for context.
    """

    model_config = ConfigDict(extra="forbid")

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
