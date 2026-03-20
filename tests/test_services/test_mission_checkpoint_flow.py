"""Tests for mission task-status consistency and checkpoint ↔ mission flow."""

from __future__ import annotations

import pytest

from rka.infra.database import Database
from rka.models.checkpoint import CheckpointCreate, CheckpointResolve
from rka.models.mission import MissionCreate, MissionReportCreate, MissionTask
from rka.services.checkpoints import CheckpointService
from rka.services.missions import MissionService


async def _ensure_project(db: Database, project_id: str = "proj_default") -> None:
    await db.execute(
        "INSERT OR IGNORE INTO projects (id, name, description, created_by) VALUES (?, ?, ?, ?)",
        [project_id, "Test", "Test project", "system"],
    )
    await db.execute(
        """INSERT OR IGNORE INTO project_states
           (project_id, project_name, project_description, phases_config, created_at, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))""",
        [project_id, "Test", "Test project", "[]"],
    )
    await db.commit()


async def _create_mission_with_tasks(svc: MissionService) -> str:
    m = await svc.create(
        MissionCreate(
            phase="phase_1",
            objective="Test mission",
            tasks=[
                MissionTask(description="Task A"),
                MissionTask(description="Task B"),
                MissionTask(description="Task C", status="skipped"),
            ],
        ),
        actor="brain",
    )
    # Activate it
    from rka.models.mission import MissionUpdate

    await svc.update(m.id, MissionUpdate(status="active"), actor="executor")
    return m.id


# ---------------------------------------------------------------------------
# Task status consistency on report submission
# ---------------------------------------------------------------------------


class TestTaskStatusConsistency:
    @pytest.mark.asyncio
    async def test_submit_report_completes_pending_tasks(self, db: Database):
        """Submitting a report must mark non-terminal tasks as complete."""
        await _ensure_project(db)
        svc = MissionService(db, project_id="proj_default")
        mis_id = await _create_mission_with_tasks(svc)

        mission = await svc.get(mis_id)
        assert mission is not None
        assert mission.tasks[0].status == "pending"
        assert mission.tasks[1].status == "pending"
        assert mission.tasks[2].status == "skipped"

        # Submit report
        await svc.submit_report(
            mis_id,
            MissionReportCreate(
                findings=["Found something"],
            ),
            actor="executor",
        )

        mission = await svc.get(mis_id)
        assert mission.status == "complete"
        assert mission.tasks[0].status == "complete"
        assert mission.tasks[0].completed_at is not None
        assert mission.tasks[1].status == "complete"
        assert mission.tasks[1].completed_at is not None
        # Skipped task should remain skipped
        assert mission.tasks[2].status == "skipped"

    @pytest.mark.asyncio
    async def test_submit_report_preserves_already_complete_tasks(self, db: Database):
        """Tasks already marked complete should keep their original completed_at."""
        await _ensure_project(db)
        svc = MissionService(db, project_id="proj_default")
        mis_id = await _create_mission_with_tasks(svc)

        # Mark task A as complete first
        from rka.models.mission import MissionUpdate

        await svc.update(
            mis_id,
            MissionUpdate(
                tasks=[
                    MissionTask(description="Task A", status="complete", completed_at="2026-01-01T00:00:00Z"),
                    MissionTask(description="Task B"),
                    MissionTask(description="Task C", status="skipped"),
                ]
            ),
        )

        await svc.submit_report(
            mis_id,
            MissionReportCreate(findings=["Done"]),
        )

        mission = await svc.get(mis_id)
        # Task A was already complete — timestamp preserved
        assert mission.tasks[0].status == "complete"
        assert mission.tasks[0].completed_at == "2026-01-01T00:00:00Z"
        # Task B was pending — now complete
        assert mission.tasks[1].status == "complete"
        assert mission.tasks[1].completed_at is not None

    @pytest.mark.asyncio
    async def test_submit_report_no_tasks(self, db: Database):
        """Submitting a report for a mission with no tasks should still work."""
        await _ensure_project(db)
        svc = MissionService(db, project_id="proj_default")
        m = await svc.create(
            MissionCreate(phase="phase_1", objective="No tasks mission"),
            actor="brain",
        )

        await svc.submit_report(
            m.id,
            MissionReportCreate(findings=["All good"]),
        )

        mission = await svc.get(m.id)
        assert mission.status == "complete"
        assert mission.tasks is None


# ---------------------------------------------------------------------------
# Checkpoint ↔ mission status flow
# ---------------------------------------------------------------------------


class TestCheckpointMissionFlow:
    @pytest.mark.asyncio
    async def test_blocking_checkpoint_blocks_mission(self, db: Database):
        """Creating a blocking checkpoint should set the mission to 'blocked'."""
        await _ensure_project(db)
        mis_svc = MissionService(db, project_id="proj_default")
        chk_svc = CheckpointService(db, project_id="proj_default")

        mis_id = await _create_mission_with_tasks(mis_svc)
        mission = await mis_svc.get(mis_id)
        assert mission.status == "active"

        # Submit a blocking checkpoint
        chk = await chk_svc.create(
            CheckpointCreate(
                mission_id=mis_id,
                type="decision",
                description="Need guidance on approach",
                blocking=True,
            ),
            actor="executor",
        )

        mission = await mis_svc.get(mis_id)
        assert mission.status == "blocked"

    @pytest.mark.asyncio
    async def test_non_blocking_checkpoint_does_not_block_mission(self, db: Database):
        """A non-blocking checkpoint should leave mission status unchanged."""
        await _ensure_project(db)
        mis_svc = MissionService(db, project_id="proj_default")
        chk_svc = CheckpointService(db, project_id="proj_default")

        mis_id = await _create_mission_with_tasks(mis_svc)

        await chk_svc.create(
            CheckpointCreate(
                mission_id=mis_id,
                type="clarification",
                description="FYI question",
                blocking=False,
            ),
            actor="executor",
        )

        mission = await mis_svc.get(mis_id)
        assert mission.status == "active"

    @pytest.mark.asyncio
    async def test_resolve_checkpoint_unblocks_mission(self, db: Database):
        """Resolving the last blocking checkpoint should set mission back to 'active'."""
        await _ensure_project(db)
        mis_svc = MissionService(db, project_id="proj_default")
        chk_svc = CheckpointService(db, project_id="proj_default")

        mis_id = await _create_mission_with_tasks(mis_svc)

        chk = await chk_svc.create(
            CheckpointCreate(
                mission_id=mis_id,
                type="decision",
                description="Blocked on approach",
                blocking=True,
            ),
        )
        assert (await mis_svc.get(mis_id)).status == "blocked"

        # Resolve the checkpoint
        await chk_svc.resolve(
            chk.id,
            CheckpointResolve(
                resolution="Use approach A",
                resolved_by="brain",
                rationale="Better fit",
            ),
        )

        mission = await mis_svc.get(mis_id)
        assert mission.status == "active"

    @pytest.mark.asyncio
    async def test_resolve_one_of_two_blocking_keeps_blocked(self, db: Database):
        """Mission stays blocked if another open blocking checkpoint remains."""
        await _ensure_project(db)
        mis_svc = MissionService(db, project_id="proj_default")
        chk_svc = CheckpointService(db, project_id="proj_default")

        mis_id = await _create_mission_with_tasks(mis_svc)

        chk1 = await chk_svc.create(
            CheckpointCreate(
                mission_id=mis_id, type="decision",
                description="Blocker 1", blocking=True,
            ),
        )
        chk2 = await chk_svc.create(
            CheckpointCreate(
                mission_id=mis_id, type="decision",
                description="Blocker 2", blocking=True,
            ),
        )

        assert (await mis_svc.get(mis_id)).status == "blocked"

        # Resolve only the first
        await chk_svc.resolve(
            chk1.id,
            CheckpointResolve(resolution="OK", resolved_by="brain"),
        )
        assert (await mis_svc.get(mis_id)).status == "blocked"

        # Resolve the second — now unblocked
        await chk_svc.resolve(
            chk2.id,
            CheckpointResolve(resolution="OK too", resolved_by="pi"),
        )
        assert (await mis_svc.get(mis_id)).status == "active"

    @pytest.mark.asyncio
    async def test_full_checkpoint_lifecycle(self, db: Database):
        """End-to-end: create mission → block → resolve → complete with report."""
        await _ensure_project(db)
        mis_svc = MissionService(db, project_id="proj_default")
        chk_svc = CheckpointService(db, project_id="proj_default")

        mis_id = await _create_mission_with_tasks(mis_svc)

        # 1. Mission is active
        assert (await mis_svc.get(mis_id)).status == "active"

        # 2. Hit a blocker
        chk = await chk_svc.create(
            CheckpointCreate(
                mission_id=mis_id, type="decision",
                description="Need PI sign-off", blocking=True,
            ),
        )
        assert (await mis_svc.get(mis_id)).status == "blocked"

        # 3. Brain resolves
        resolved = await chk_svc.resolve(
            chk.id,
            CheckpointResolve(
                resolution="Approved", resolved_by="brain",
                rationale="Looks good",
            ),
        )
        assert resolved.status == "resolved"
        assert (await mis_svc.get(mis_id)).status == "active"

        # 4. Executor completes with report
        await svc_submit_report_with_tasks(mis_svc, mis_id)

        mission = await mis_svc.get(mis_id)
        assert mission.status == "complete"
        assert all(
            t.status in ("complete", "skipped") for t in mission.tasks
        )


async def svc_submit_report_with_tasks(svc: MissionService, mis_id: str) -> None:
    await svc.submit_report(
        mis_id,
        MissionReportCreate(
            findings=["Implementation done"],
            recommended_next="Run integration tests",
        ),
    )
