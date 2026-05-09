"""Test for Affordance A (Mission B / mis_01KR209WY4M6WQFEXRH79KC2ZF):
MaintenanceService._missions_without_upstream_gate().

Walks each mission's motivated_by_decision parent chain via
decisions.parent_id; flags missions with no 'gate'-tagged ancestor.
Replaces the rejected first-class gate schema recommendation with a
manifest advisory query at a fraction of the cost.
"""

from __future__ import annotations

import pytest_asyncio

from rka.infra.database import Database
from rka.services.maintenance import MaintenanceService

PROJECT_ID = "proj_test_gate_audit"


async def _seed_decision(db: Database, dec_id: str, parent_id: str | None = None,
                          tag_as_gate: bool = False) -> None:
    await db.execute(
        """INSERT INTO decisions (id, parent_id, phase, question, decided_by, project_id)
           VALUES (?, ?, 'design', ?, 'executor', ?)""",
        [dec_id, parent_id, f"q for {dec_id}", PROJECT_ID],
    )
    if tag_as_gate:
        await db.execute(
            """INSERT INTO tags (entity_type, entity_id, tag, project_id)
               VALUES ('decision', ?, 'gate', ?)""",
            [dec_id, PROJECT_ID],
        )


async def _seed_mission(db: Database, mis_id: str, motivated_by: str | None) -> None:
    await db.execute(
        """INSERT INTO missions (id, phase, objective, status, project_id, motivated_by_decision)
           VALUES (?, 'design', ?, 'pending', ?, ?)""",
        [mis_id, f"obj for {mis_id}", PROJECT_ID, motivated_by],
    )


@pytest_asyncio.fixture
async def gate_db(db: Database) -> Database:
    """Build a small graph exercising every gate-audit branch.

      dec_root_gate  [gate]                dec_alone        dec_lone_gate  [gate]
        |
      dec_mid_a
        |
      dec_leaf_a   ←→ mis_a  (chain has gate at root)
                   ←→ mis_a_dup (same chain — both flagged-or-not symmetrically)

      dec_chain_b → ... → dec_leaf_b ←→ mis_b  (chain has NO gate)
      mis_no_motivation: motivated_by_decision = NULL → not a candidate
      mis_cancelled: status='cancelled' → not a candidate

    Plus a cycle: dec_cycle_a.parent_id = dec_cycle_b; dec_cycle_b.parent_id = dec_cycle_a.
    Mission mis_cycle motivated by dec_cycle_a — must NOT loop forever.
    """
    await db.execute(
        "INSERT INTO projects (id, name) VALUES (?, ?)",
        [PROJECT_ID, "Gate Audit Test"],
    )
    # Chain A: gate at root.
    await _seed_decision(db, "dec_root_gate", parent_id=None, tag_as_gate=True)
    await _seed_decision(db, "dec_mid_a", parent_id="dec_root_gate")
    await _seed_decision(db, "dec_leaf_a", parent_id="dec_mid_a")
    # Chain B: no gate anywhere.
    await _seed_decision(db, "dec_root_b", parent_id=None)
    await _seed_decision(db, "dec_leaf_b", parent_id="dec_root_b")
    # Standalone gate-tagged decision (testing depth-1 hit).
    await _seed_decision(db, "dec_lone_gate", parent_id=None, tag_as_gate=True)
    # Cycle pair.
    await _seed_decision(db, "dec_cycle_a", parent_id=None)
    await _seed_decision(db, "dec_cycle_b", parent_id="dec_cycle_a")
    # After both rows exist, point a back at b to form the cycle.
    await db.execute(
        "UPDATE decisions SET parent_id = ? WHERE id = ?",
        ["dec_cycle_b", "dec_cycle_a"],
    )
    await db.commit()

    # Missions.
    await _seed_mission(db, "mis_a", motivated_by="dec_leaf_a")          # has gate (chain A)
    await _seed_mission(db, "mis_a_dup", motivated_by="dec_leaf_a")      # same — has gate
    await _seed_mission(db, "mis_b", motivated_by="dec_leaf_b")          # NO gate (chain B)
    await _seed_mission(db, "mis_lone_hit", motivated_by="dec_lone_gate")  # depth-1 hit
    await _seed_mission(db, "mis_no_motivation", motivated_by=None)      # excluded (no FK)
    await _seed_mission(db, "mis_cycle", motivated_by="dec_cycle_a")     # cycle path; no gate
    await db.execute(
        "UPDATE missions SET status = 'cancelled' WHERE id = ?",
        ["mis_no_motivation"],
    )  # repurpose as cancelled-without-motivation, double-excluded
    await _seed_mission(db, "mis_cancelled_with_motivation", motivated_by="dec_leaf_b")
    await db.execute(
        "UPDATE missions SET status = 'cancelled' WHERE id = ?",
        ["mis_cancelled_with_motivation"],
    )
    await db.commit()
    return db


class TestGateAudit:
    async def test_chain_a_passes_gate_at_root(self, gate_db: Database):
        """Mission whose chain has a gate-tagged ancestor at any depth is NOT flagged."""
        svc = MaintenanceService(gate_db, project_id=PROJECT_ID)
        result = await svc._missions_without_upstream_gate(PROJECT_ID)
        assert "mis_a" not in result["ids"]
        assert "mis_a_dup" not in result["ids"]

    async def test_chain_b_no_gate_flagged(self, gate_db: Database):
        """Mission whose chain has NO gate-tagged ancestor IS flagged."""
        svc = MaintenanceService(gate_db, project_id=PROJECT_ID)
        result = await svc._missions_without_upstream_gate(PROJECT_ID)
        assert "mis_b" in result["ids"]

    async def test_depth_1_hit(self, gate_db: Database):
        """Mission whose motivated_by_decision IS itself the gate-tagged decision is NOT flagged."""
        svc = MaintenanceService(gate_db, project_id=PROJECT_ID)
        result = await svc._missions_without_upstream_gate(PROJECT_ID)
        assert "mis_lone_hit" not in result["ids"]

    async def test_no_motivation_excluded(self, gate_db: Database):
        """Missions without motivated_by_decision are NOT candidates here —
        they're covered by the separate _missions_without_motivated_by query."""
        svc = MaintenanceService(gate_db, project_id=PROJECT_ID)
        result = await svc._missions_without_upstream_gate(PROJECT_ID)
        assert "mis_no_motivation" not in result["ids"]

    async def test_cancelled_excluded(self, gate_db: Database):
        """Cancelled missions don't carry maintenance debt."""
        svc = MaintenanceService(gate_db, project_id=PROJECT_ID)
        result = await svc._missions_without_upstream_gate(PROJECT_ID)
        assert "mis_cancelled_with_motivation" not in result["ids"]

    async def test_cycle_protected(self, gate_db: Database):
        """Cycle in parent_id chain must not loop forever; mission still
        flagged because no gate is found within the cycle."""
        svc = MaintenanceService(gate_db, project_id=PROJECT_ID)
        result = await svc._missions_without_upstream_gate(PROJECT_ID)
        assert "mis_cycle" in result["ids"]

    async def test_manifest_cap(self, db: Database):
        """The audit caps at _GATE_AUDIT_LIMIT (default 10)."""
        cap_project = "proj_test_gate_audit_cap"
        await db.execute(
            "INSERT INTO projects (id, name) VALUES (?, ?)",
            [cap_project, "Cap Test"],
        )
        # No gate-tagged decisions; insert 15 ungated chains so all 15 missions
        # would flag without the cap.
        for i in range(15):
            await db.execute(
                """INSERT INTO decisions (id, phase, question, decided_by, project_id)
                   VALUES (?, 'design', ?, 'executor', ?)""",
                [f"dec_cap_{i}", f"q{i}", cap_project],
            )
            await db.execute(
                """INSERT INTO missions (id, phase, objective, status, project_id, motivated_by_decision)
                   VALUES (?, 'design', ?, 'pending', ?, ?)""",
                [f"mis_cap_{i}", f"obj{i}", cap_project, f"dec_cap_{i}"],
            )
        await db.commit()

        svc = MaintenanceService(db, project_id=cap_project)
        result = await svc._missions_without_upstream_gate(cap_project)
        # The cap is _GATE_AUDIT_LIMIT (10).
        assert result["count"] <= MaintenanceService._GATE_AUDIT_LIMIT
        assert len(result["ids"]) <= MaintenanceService._GATE_AUDIT_LIMIT

    async def test_get_pending_maintenance_includes_category(self, gate_db: Database):
        """The new category surfaces in the full manifest response."""
        svc = MaintenanceService(gate_db, project_id=PROJECT_ID)
        manifest = await svc.get_pending_maintenance()
        assert "missions_without_upstream_gate" in manifest["categories"]
        gate_cat = manifest["categories"]["missions_without_upstream_gate"]
        assert "ids" in gate_cat
        assert "description" in gate_cat
        assert "fix_action" in gate_cat
        # Chain B's mission should be flagged in the manifest output too.
        assert "mis_b" in gate_cat["ids"]

    async def test_get_backlog_summary_includes_category(self, gate_db: Database):
        """The new category contributes to the lightweight summary counts."""
        svc = MaintenanceService(gate_db, project_id=PROJECT_ID)
        summary = await svc.get_backlog_summary()
        # Total items must include the gate-audit count.
        assert summary["total_items"] >= 1  # at least mis_b + mis_cycle flagged
