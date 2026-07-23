"""Tests for DecisionOptionsService (migration 017 substrate)."""

from __future__ import annotations

import sqlite3

import pytest
import pytest_asyncio
from pydantic import ValidationError

from rka.infra.database import Database
from rka.models.decision_option import DecisionOptionCreate, EvidenceRef
from rka.services import decision_options as decision_options_module
from rka.services.decision_options import DecisionOptionsService


def _make_option(
    *,
    label: str = "Option A",
    seed: int = 1,
    confidence: float = 0.7,
    known_unknowns: list[str] | None = None,
) -> DecisionOptionCreate:
    """Minimal valid option payload for tests. Varies seed + label per call."""
    return DecisionOptionCreate(
        label=label,
        summary=f"{label} short summary",
        justification=f"{label} is on the slate because …",
        expert_archetype="the pragmatic incrementalist",
        explanation=f"{label} full reasoning.",
        pros=["Pro one", "Pro two", "Pro three"],
        cons=["Con one", "Con two", "Con three (steelman)"],
        evidence=[EvidenceRef(claim_id="clm_test", strength_tier="direct")],
        confidence_verbal="moderate",
        confidence_numeric=confidence,
        confidence_evidence_strength="moderate",
        confidence_known_unknowns=known_unknowns or ["unknown-one"],
        effort_time="M",
        effort_cost=None,
        effort_reversibility="reversible",
        presentation_order_seed=seed,
    )


@pytest_asyncio.fixture
async def svc_and_decision(db: Database):
    """Create a DecisionOptionsService with a backing decision row present."""
    await db.execute(
        """INSERT INTO decisions (id, phase, question, decided_by, status, project_id)
           VALUES ('dec_t', 'p1', 'Q?', 'brain', 'active', 'proj_default')""",
    )
    await db.commit()
    svc = DecisionOptionsService(db, project_id="proj_default")
    return svc, "dec_t"


# -------------------------------------------------------------------- pydantic


class TestPydanticValidators:
    def test_pros_of_length_two_rejected(self):
        with pytest.raises(ValidationError):
            DecisionOptionCreate(
                label="L", summary="S", justification="J", explanation="E",
                pros=["p1", "p2"],
                cons=["c1", "c2", "c3"],
                evidence=[],
                confidence_verbal="high", confidence_numeric=0.8,
                confidence_evidence_strength="moderate",
                confidence_known_unknowns=["u"],
                effort_time="M", effort_reversibility="reversible",
                presentation_order_seed=1,
            )

    def test_pros_of_length_four_rejected(self):
        with pytest.raises(ValidationError):
            _ = _make_option()
            DecisionOptionCreate(
                label="L", summary="S", justification="J", explanation="E",
                pros=["p1", "p2", "p3", "p4"],
                cons=["c1", "c2", "c3"],
                evidence=[],
                confidence_verbal="high", confidence_numeric=0.8,
                confidence_evidence_strength="moderate",
                confidence_known_unknowns=["u"],
                effort_time="M", effort_reversibility="reversible",
                presentation_order_seed=1,
            )

    def test_known_unknowns_of_length_three_rejected(self):
        with pytest.raises(ValidationError):
            DecisionOptionCreate(
                label="L", summary="S", justification="J", explanation="E",
                pros=["p1", "p2", "p3"],
                cons=["c1", "c2", "c3"],
                evidence=[],
                confidence_verbal="high", confidence_numeric=0.8,
                confidence_evidence_strength="moderate",
                confidence_known_unknowns=["u1", "u2", "u3"],
                effort_time="M", effort_reversibility="reversible",
                presentation_order_seed=1,
            )

    def test_confidence_numeric_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            DecisionOptionCreate(
                label="L", summary="S", justification="J", explanation="E",
                pros=["p1", "p2", "p3"],
                cons=["c1", "c2", "c3"],
                evidence=[],
                confidence_verbal="high", confidence_numeric=1.5,
                confidence_evidence_strength="moderate",
                confidence_known_unknowns=["u"],
                effort_time="M", effort_reversibility="reversible",
                presentation_order_seed=1,
            )


# ----------------------------------------------------------------- service CRUD


class TestCreateAndList:
    @pytest.mark.asyncio
    async def test_create_single_returns_option_with_dop_id(self, svc_and_decision):
        svc, dec_id = svc_and_decision
        opt = await svc.create(dec_id, _make_option(label="A", seed=1))
        assert opt.id.startswith("dop_")
        assert opt.decision_id == dec_id
        assert opt.is_recommended is False
        assert opt.dominated_by is None
        assert opt.pros == ["Pro one", "Pro two", "Pro three"]
        assert opt.evidence[0].claim_id == "clm_test"

    @pytest.mark.asyncio
    async def test_create_bulk_and_list_order(self, svc_and_decision):
        svc, dec_id = svc_and_decision
        created = await svc.create_bulk(
            dec_id,
            [
                _make_option(label="C", seed=30),
                _make_option(label="A", seed=10),
                _make_option(label="B", seed=20),
            ],
        )
        assert len(created) == 3
        listed = await svc.list_for_decision(dec_id)
        assert [o.label for o in listed] == ["A", "B", "C"]  # by seed

    @pytest.mark.asyncio
    async def test_create_bulk_failure_rolls_back_all_options(
        self,
        svc_and_decision,
        monkeypatch: pytest.MonkeyPatch,
    ):
        svc, dec_id = svc_and_decision
        monkeypatch.setattr(
            decision_options_module,
            "generate_id",
            lambda _entity_type: "dop_duplicate",
        )

        with pytest.raises(sqlite3.IntegrityError):
            await svc.create_bulk(
                dec_id,
                [
                    _make_option(label="first", seed=1),
                    _make_option(label="second", seed=2),
                ],
            )

        assert await svc.list_for_decision(dec_id) == []

    @pytest.mark.asyncio
    async def test_fk_rejects_unknown_decision(self, svc_and_decision):
        svc, _ = svc_and_decision
        with pytest.raises(ValueError, match="not found in project"):
            await svc.create("dec_missing", _make_option())

    @pytest.mark.asyncio
    async def test_create_and_bulk_reject_foreign_decision(
        self,
        svc_and_decision,
    ):
        svc, _ = svc_and_decision
        await svc.db.execute(
            """INSERT INTO decisions
               (id, phase, question, decided_by, status, project_id)
               VALUES ('dec_foreign_create', 'p1', 'Foreign Q?', 'brain',
                       'active', 'proj_foreign')"""
        )
        await svc.db.commit()

        with pytest.raises(ValueError, match="not found in project proj_default"):
            await svc.create(
                "dec_foreign_create",
                _make_option(label="Foreign single"),
            )
        with pytest.raises(ValueError, match="not found in project proj_default"):
            await svc.create_bulk(
                "dec_foreign_create",
                [_make_option(label="Foreign bulk")],
            )
        # An empty bulk call must still enforce decision ownership.
        with pytest.raises(ValueError, match="not found in project proj_default"):
            await svc.create_bulk("dec_missing_bulk", [])

        assert await svc.db.fetchall(
            """SELECT id FROM decision_options
               WHERE decision_id IN ('dec_foreign_create',
                                     'dec_missing_bulk')"""
        ) == []

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, svc_and_decision):
        svc, _ = svc_and_decision
        assert await svc.get("dop_missing") is None


# -------------------------------------------------------------------- dominated_by


class TestDominatedBy:
    @pytest.mark.asyncio
    async def test_self_reference_rejected(self, svc_and_decision):
        svc, dec_id = svc_and_decision
        a = await svc.create(dec_id, _make_option(label="A"))
        with pytest.raises(ValueError):
            await svc.set_dominated_by(a.id, a.id)

    @pytest.mark.asyncio
    async def test_set_and_clear(self, svc_and_decision):
        svc, dec_id = svc_and_decision
        a = await svc.create(dec_id, _make_option(label="A", seed=1))
        b = await svc.create(dec_id, _make_option(label="B", seed=2))
        await svc.set_dominated_by(a.id, b.id)
        a_refetched = await svc.get(a.id)
        assert a_refetched.dominated_by == b.id
        # Clear it.
        await svc.set_dominated_by(a.id, None)
        a_refetched = await svc.get(a.id)
        assert a_refetched.dominated_by is None

    @pytest.mark.asyncio
    async def test_missing_and_foreign_target_rejected(
        self,
        svc_and_decision,
    ):
        svc, _ = svc_and_decision
        with pytest.raises(ValueError, match="not found in project"):
            await svc.set_dominated_by("dop_missing_target", None)

        await svc.db.execute(
            """INSERT INTO decisions
               (id, phase, question, decided_by, status, project_id)
               VALUES ('dec_foreign_dom_target', 'p1', 'Foreign Q?', 'brain',
                       'active', 'proj_foreign')"""
        )
        await svc.db.commit()
        foreign_svc = DecisionOptionsService(
            svc.db,
            project_id="proj_foreign",
        )
        foreign_target = await foreign_svc.create(
            "dec_foreign_dom_target",
            _make_option(label="Foreign target"),
        )

        with pytest.raises(ValueError, match="not found in project proj_default"):
            await svc.set_dominated_by(foreign_target.id, None)
        assert (await foreign_svc.get(foreign_target.id)).dominated_by is None

    @pytest.mark.asyncio
    async def test_cross_decision_and_foreign_dominator_rejected(
        self,
        svc_and_decision,
    ):
        svc, dec_id = svc_and_decision
        target = await svc.create(
            dec_id,
            _make_option(label="Target", seed=1),
        )
        await svc.db.execute(
            """INSERT INTO decisions
               (id, phase, question, decided_by, status, project_id)
               VALUES ('dec_other_dominator', 'p1', 'Other Q?', 'brain',
                       'active', 'proj_default')"""
        )
        await svc.db.execute(
            """INSERT INTO decisions
               (id, phase, question, decided_by, status, project_id)
               VALUES ('dec_foreign_dominator', 'p1', 'Foreign Q?', 'brain',
                       'active', 'proj_foreign')"""
        )
        await svc.db.commit()
        cross_decision = await svc.create(
            "dec_other_dominator",
            _make_option(label="Cross-decision dominator", seed=2),
        )
        foreign_svc = DecisionOptionsService(
            svc.db,
            project_id="proj_foreign",
        )
        foreign = await foreign_svc.create(
            "dec_foreign_dominator",
            _make_option(label="Foreign dominator", seed=3),
        )

        with pytest.raises(ValueError, match="different decisions"):
            await svc.set_dominated_by(target.id, cross_decision.id)
        with pytest.raises(ValueError, match="not found in project proj_default"):
            await svc.set_dominated_by(target.id, foreign.id)
        assert (await svc.get(target.id)).dominated_by is None


# ------------------------------------------------------------------- pareto_filter


class TestParetoFilter:
    @pytest.mark.asyncio
    async def test_filter_returns_only_non_dominated(self, svc_and_decision):
        svc, dec_id = svc_and_decision
        a = await svc.create(dec_id, _make_option(label="A", seed=1))
        b = await svc.create(dec_id, _make_option(label="B", seed=2))
        await svc.create(dec_id, _make_option(label="C", seed=3))
        await svc.set_dominated_by(b.id, a.id)  # B dominated by A
        options = await svc.list_for_decision(dec_id)
        filtered = await svc.pareto_filter(options)
        assert {o.label for o in filtered} == {"A", "C"}


# ------------------------------------------------------------------- recommendation


class TestMarkRecommended:
    @pytest.mark.asyncio
    async def test_atomic_switch(self, svc_and_decision):
        svc, dec_id = svc_and_decision
        a = await svc.create(dec_id, _make_option(label="A", seed=1))
        b = await svc.create(dec_id, _make_option(label="B", seed=2))
        await svc.mark_recommended(a.id)
        assert (await svc.get(a.id)).is_recommended is True
        assert (await svc.get(b.id)).is_recommended is False
        # Switching to B clears A.
        await svc.mark_recommended(b.id)
        assert (await svc.get(a.id)).is_recommended is False
        assert (await svc.get(b.id)).is_recommended is True
        # Decisions row mirrors the latest recommendation.
        row = await svc.db.fetchone(
            "SELECT recommended_option_id FROM decisions WHERE id = ?",
            [dec_id],
        )
        assert row["recommended_option_id"] == b.id

    @pytest.mark.asyncio
    async def test_mark_nonexistent_raises(self, svc_and_decision):
        svc, _ = svc_and_decision
        with pytest.raises(ValueError):
            await svc.mark_recommended("dop_missing")

    @pytest.mark.asyncio
    async def test_switch_failure_restores_previous_recommendation(
        self,
        svc_and_decision,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """All three recommendation writes roll back when the switch fails."""
        svc, dec_id = svc_and_decision
        previous = await svc.create(
            dec_id,
            _make_option(label="Previous", seed=1),
        )
        replacement = await svc.create(
            dec_id,
            _make_option(label="Replacement", seed=2),
        )
        await svc.mark_recommended(previous.id)

        real_execute = svc.db.execute

        async def fail_before_marking_target(sql, params=None):
            if (
                "UPDATE decision_options SET is_recommended = 1" in sql
                and params == [replacement.id, dec_id, "proj_default"]
            ):
                raise RuntimeError("injected recommendation switch failure")
            return await real_execute(sql, params)

        monkeypatch.setattr(svc.db, "execute", fail_before_marking_target)
        with pytest.raises(
            RuntimeError,
            match="injected recommendation switch failure",
        ):
            await svc.mark_recommended(replacement.id)

        assert (await svc.get(previous.id)).is_recommended is True
        assert (await svc.get(replacement.id)).is_recommended is False
        decision = await svc.db.fetchone(
            "SELECT recommended_option_id FROM decisions WHERE id = ?",
            [dec_id],
        )
        assert decision["recommended_option_id"] == previous.id

    @pytest.mark.asyncio
    async def test_corrupt_option_attached_to_foreign_decision_is_rejected(
        self,
        svc_and_decision,
    ):
        svc, dec_id = svc_and_decision
        previous = await svc.create(
            dec_id,
            _make_option(label="Previous", seed=1),
        )
        corrupt = await svc.create(
            dec_id,
            _make_option(label="Corrupt foreign attachment", seed=2),
        )
        await svc.mark_recommended(previous.id)
        await svc.db.execute(
            """INSERT INTO decisions
               (id, phase, question, decided_by, status, project_id)
               VALUES ('dec_foreign_recommendation', 'p1', 'Foreign Q?',
                       'brain', 'active', 'proj_foreign')"""
        )
        # Simulate a legacy/imported row whose option project and parent
        # decision project disagree.
        await svc.db.execute(
            """UPDATE decision_options SET decision_id = ?
               WHERE id = ?""",
            ["dec_foreign_recommendation", corrupt.id],
        )
        await svc.db.commit()

        with pytest.raises(ValueError, match="not found in project proj_default"):
            await svc.mark_recommended(corrupt.id)

        assert (await svc.get(previous.id)).is_recommended is True
        assert (await svc.get(corrupt.id)).is_recommended is False
        assert await svc.db.fetchone(
            """SELECT recommended_option_id FROM decisions
               WHERE id = ?""",
            [dec_id],
        ) == {"recommended_option_id": previous.id}
        assert await svc.db.fetchone(
            """SELECT recommended_option_id FROM decisions
               WHERE id = 'dec_foreign_recommendation'"""
        ) == {"recommended_option_id": None}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("zero_row_at", ["target", "decision"])
    async def test_zero_row_switch_restores_previous_recommendation(
        self,
        svc_and_decision,
        monkeypatch: pytest.MonkeyPatch,
        zero_row_at: str,
    ):
        svc, dec_id = svc_and_decision
        previous = await svc.create(
            dec_id,
            _make_option(label="Previous", seed=1),
        )
        replacement = await svc.create(
            dec_id,
            _make_option(label="Replacement", seed=2),
        )
        await svc.mark_recommended(previous.id)
        real_execute = svc.db.execute

        class ZeroRowCursor:
            rowcount = 0

        async def zero_row_switch(sql, params=None):
            target_write = (
                "UPDATE decision_options SET is_recommended = 1" in sql
                and params
                == [replacement.id, dec_id, "proj_default"]
            )
            decision_write = (
                "UPDATE decisions SET recommended_option_id = ?" in sql
                and params
                and params[0] == replacement.id
            )
            if (
                zero_row_at == "target" and target_write
            ) or (
                zero_row_at == "decision" and decision_write
            ):
                return ZeroRowCursor()
            return await real_execute(sql, params)

        monkeypatch.setattr(svc.db, "execute", zero_row_switch)
        with pytest.raises(ValueError, match="not found in project"):
            await svc.mark_recommended(replacement.id)

        assert (await svc.get(previous.id)).is_recommended is True
        assert (await svc.get(replacement.id)).is_recommended is False
        assert await svc.db.fetchone(
            """SELECT recommended_option_id FROM decisions
               WHERE id = ?""",
            [dec_id],
        ) == {"recommended_option_id": previous.id}


# ---------------------------------------------------------- record_pi_selection


class TestRecordPiSelection:
    @pytest.mark.asyncio
    async def test_selected_only_ok(self, svc_and_decision):
        svc, dec_id = svc_and_decision
        a = await svc.create(dec_id, _make_option(label="A"))
        await svc.record_pi_selection(dec_id, a.id, None)
        row = await svc.db.fetchone(
            "SELECT pi_selected_option_id, pi_override_rationale FROM decisions WHERE id = ?",
            [dec_id],
        )
        assert row["pi_selected_option_id"] == a.id
        assert row["pi_override_rationale"] is None

    @pytest.mark.asyncio
    async def test_override_only_ok(self, svc_and_decision):
        svc, dec_id = svc_and_decision
        await svc.record_pi_selection(dec_id, None, "reframe — none of these fit")
        row = await svc.db.fetchone(
            "SELECT pi_selected_option_id, pi_override_rationale FROM decisions WHERE id = ?",
            [dec_id],
        )
        assert row["pi_selected_option_id"] is None
        assert row["pi_override_rationale"] == "reframe — none of these fit"

    @pytest.mark.asyncio
    async def test_both_set_ok(self, svc_and_decision):
        """Per Defect 6 (Mission A / mis_01KR1Z28QW9WYXG4VV8PGYWD8G): both
        fields together is the override-of-recommendation case — PI chose an
        option AND recorded a rationale for choosing it over the recommended
        one. Earlier XOR rejection contradicted PI semantic intent and was
        removed in v2.3.4.
        """
        svc, dec_id = svc_and_decision
        a = await svc.create(dec_id, _make_option(label="A"))
        await svc.record_pi_selection(dec_id, a.id, "chose A over recommended B because …")
        row = await svc.db.fetchone(
            "SELECT pi_selected_option_id, pi_override_rationale FROM decisions WHERE id = ?",
            [dec_id],
        )
        assert row["pi_selected_option_id"] == a.id
        assert row["pi_override_rationale"] == "chose A over recommended B because …"

    @pytest.mark.asyncio
    async def test_neither_set_rejected(self, svc_and_decision):
        svc, dec_id = svc_and_decision
        with pytest.raises(ValueError):
            await svc.record_pi_selection(dec_id, None, None)

    @pytest.mark.asyncio
    async def test_selected_option_mismatched_decision_rejected(self, svc_and_decision):
        svc, dec_id = svc_and_decision
        await svc.db.execute(
            """INSERT INTO decisions (id, phase, question, decided_by, status, project_id)
               VALUES ('dec_other', 'p1', 'Q?', 'brain', 'active', 'proj_default')""",
        )
        await svc.db.commit()
        other_opt = await svc.create("dec_other", _make_option(label="X"))
        with pytest.raises(ValueError):
            await svc.record_pi_selection(dec_id, other_opt.id, None)

    @pytest.mark.asyncio
    async def test_override_only_rejects_missing_and_foreign_decision(
        self,
        svc_and_decision,
    ):
        svc, _ = svc_and_decision
        with pytest.raises(ValueError, match="not found in project proj_default"):
            await svc.record_pi_selection(
                "dec_missing_override",
                None,
                "override must not disappear",
            )

        await svc.db.execute(
            """INSERT INTO decisions
               (id, phase, question, decided_by, status, project_id)
               VALUES ('dec_foreign_override', 'p1', 'Foreign Q?', 'brain',
                       'active', 'proj_foreign')"""
        )
        await svc.db.commit()
        with pytest.raises(ValueError, match="not found in project proj_default"):
            await svc.record_pi_selection(
                "dec_foreign_override",
                None,
                "cross-project override",
            )
        assert await svc.db.fetchone(
            """SELECT pi_selected_option_id, pi_override_rationale
               FROM decisions WHERE id = 'dec_foreign_override'"""
        ) == {
            "pi_selected_option_id": None,
            "pi_override_rationale": None,
        }

    @pytest.mark.asyncio
    async def test_selected_foreign_option_rejected(
        self,
        svc_and_decision,
    ):
        svc, dec_id = svc_and_decision
        await svc.db.execute(
            """INSERT INTO decisions
               (id, phase, question, decided_by, status, project_id)
               VALUES ('dec_foreign_selection', 'p1', 'Foreign Q?', 'brain',
                       'active', 'proj_foreign')"""
        )
        await svc.db.commit()
        foreign_svc = DecisionOptionsService(
            svc.db,
            project_id="proj_foreign",
        )
        foreign_option = await foreign_svc.create(
            "dec_foreign_selection",
            _make_option(label="Foreign selection"),
        )

        with pytest.raises(ValueError, match="not found in project proj_default"):
            await svc.record_pi_selection(dec_id, foreign_option.id, None)

    @pytest.mark.asyncio
    async def test_override_only_zero_row_update_is_rejected(
        self,
        svc_and_decision,
        monkeypatch: pytest.MonkeyPatch,
    ):
        svc, dec_id = svc_and_decision
        real_execute = svc.db.execute

        class ZeroRowCursor:
            rowcount = 0

        async def zero_row_selection(sql, params=None):
            if "SET pi_selected_option_id = ?" in sql:
                return ZeroRowCursor()
            return await real_execute(sql, params)

        monkeypatch.setattr(svc.db, "execute", zero_row_selection)
        with pytest.raises(ValueError, match="not found in project proj_default"):
            await svc.record_pi_selection(
                dec_id,
                None,
                "override that matched no row",
            )

        assert await svc.db.fetchone(
            """SELECT pi_selected_option_id, pi_override_rationale
               FROM decisions WHERE id = ?""",
            [dec_id],
        ) == {
            "pi_selected_option_id": None,
            "pi_override_rationale": None,
        }
