"""Tests for DecisionOptionsService (migration 017 substrate)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from pydantic import ValidationError

from rka.infra.database import Database
from rka.models.decision_option import DecisionOptionCreate, EvidenceRef
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
        evidence=[EvidenceRef(claim_id="clm_test", strength_tier="moderate")],
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
    async def test_fk_rejects_unknown_decision(self, svc_and_decision):
        svc, _ = svc_and_decision
        with pytest.raises(Exception):
            await svc.create("dec_missing", _make_option())

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


# ------------------------------------------------------------------- pareto_filter


class TestParetoFilter:
    @pytest.mark.asyncio
    async def test_filter_returns_only_non_dominated(self, svc_and_decision):
        svc, dec_id = svc_and_decision
        a = await svc.create(dec_id, _make_option(label="A", seed=1))
        b = await svc.create(dec_id, _make_option(label="B", seed=2))
        c = await svc.create(dec_id, _make_option(label="C", seed=3))
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
    async def test_both_set_rejected(self, svc_and_decision):
        svc, dec_id = svc_and_decision
        a = await svc.create(dec_id, _make_option(label="A"))
        with pytest.raises(ValueError):
            await svc.record_pi_selection(dec_id, a.id, "also override")

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
