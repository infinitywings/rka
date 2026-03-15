"""Topic API routes (v2.0)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from rka.models.topic import Topic, TopicCreate, TopicUpdate
from rka.services.topics import TopicService
from rka.api.deps import get_scoped_topic_service

router = APIRouter()


@router.post("/topics", response_model=Topic, status_code=201)
async def create_topic(
    data: TopicCreate,
    svc: TopicService = Depends(get_scoped_topic_service),
):
    return await svc.create(data)


@router.get("/topics", response_model=list[Topic])
async def list_topics(
    parent_id: str | None = Query(default="__unset__"),
    limit: int = Query(100, le=500),
    offset: int = 0,
    svc: TopicService = Depends(get_scoped_topic_service),
):
    return await svc.list(parent_id=parent_id, limit=limit, offset=offset)


@router.get("/topics/tree")
async def get_topic_tree(
    svc: TopicService = Depends(get_scoped_topic_service),
):
    return await svc.get_topic_tree()


@router.get("/topics/{topic_id}", response_model=Topic)
async def get_topic(
    topic_id: str,
    svc: TopicService = Depends(get_scoped_topic_service),
):
    topic = await svc.get(topic_id)
    if topic is None:
        raise HTTPException(404, f"Topic {topic_id} not found")
    return topic


@router.put("/topics/{topic_id}", response_model=Topic)
async def update_topic(
    topic_id: str,
    data: TopicUpdate,
    svc: TopicService = Depends(get_scoped_topic_service),
):
    topic = await svc.get(topic_id)
    if topic is None:
        raise HTTPException(404, f"Topic {topic_id} not found")
    return await svc.update(topic_id, data)


@router.delete("/topics/{topic_id}")
async def delete_topic(
    topic_id: str,
    svc: TopicService = Depends(get_scoped_topic_service),
):
    topic = await svc.get(topic_id)
    if topic is None:
        raise HTTPException(404, f"Topic {topic_id} not found")
    await svc.delete(topic_id)
    return {"deleted": True}
