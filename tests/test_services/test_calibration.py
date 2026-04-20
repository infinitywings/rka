"""Tests for CalibrationService — record, list, compute_metrics, Brier, ECE."""

from __future__ import annotations

import pytest
import pytest_asyncio

from rka.infra.database import Database
from rka.models.calibration import CalibrationOutcomeCreate
from rka.services.calibration import (
    CalibrationService,
    MIN_SAMPLES_FOR_METRICS,
    brier_score,
    ece,
)


# -------------------------------------------------------------------- pure fns


class TestBrierScore:
    def test_perfect_predictor_scores_zero(self):
        # Forecasts equal outcomes → squared error 0 everywhere.
        assert brier_score([1.0, 0.0, 1.0, 0.0], [1.0, 0.0, 1.0, 0.0]) == 0.0

    def test_known_value_5_decisions_4_succeeded(self):
        # Mission acceptance #7 worked example. Forecast = 0.8 for all 5;
        # 4 succeeded (o=1) + 1 failed (o=0). Per-element squared errors:
        # (0.8-1)^2 = 0.04 four times → 0.16 sum
        # (0.8-0)^2 = 0.64 once
        # Total 0.80, mean = 0.16.
        forecasts = [0.8] * 5
        outcomes = [1.0, 1.0, 1.0, 1.0, 0.0]
        assert brier_score(forecasts, outcomes) == pytest.approx(0.16)

    def test_mixed_outcome_at_half(self):
        # f=0.5 with mixed (o=0.5) → squared error 0 → Brier = 0.
        assert brier_score([0.5, 0.5], [0.5, 0.5]) == pytest.approx(0.0)

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            brier_score([0.5, 0.6], [1.0])

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            brier_score([], [])


class TestECE:
    def test_perfect_calibration_zero_ece(self):
        # All forecasts in their right bins; accuracy matches confidence.
        # 10 forecasts at 0.95, all succeeded: bin [0.9, 1.0], accuracy=1.0,
        # mean_confidence=0.95 → gap 0.05. Single populated bin.
        # ECE = (10/10) * 0.05 = 0.05 — not zero, but predictable.
        e, _ = ece([0.95] * 10, [1.0] * 10)
        assert e == pytest.approx(0.05)

    def test_known_value_two_bins(self):
        # Bin [0.0, 0.1): 4 forecasts at 0.05 with 1 succeeded.
        #   accuracy = 0.25, mean_conf = 0.05, gap = 0.2
        # Bin [0.7, 0.8): 6 forecasts at 0.75 with 5 succeeded.
        #   accuracy = 5/6 ≈ 0.833, mean_conf = 0.75, gap ≈ 0.0833
        # ECE = (4/10) * 0.2 + (6/10) * 0.0833 = 0.08 + 0.05 = 0.13
        forecasts = [0.05, 0.05, 0.05, 0.05, 0.75, 0.75, 0.75, 0.75, 0.75, 0.75]
        outcomes = [1.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0]
        e, breakdown = ece(forecasts, outcomes)
        assert len(breakdown) == 2
        assert e == pytest.approx(0.4 * 0.2 + 0.6 * (5/6 - 0.75))

    def test_empty_bins_excluded(self):
        # All 8 forecasts cluster at 0.55 → only one populated bin.
        forecasts = [0.55] * 8
        outcomes = [1.0] * 8
        _, breakdown = ece(forecasts, outcomes)
        assert len(breakdown) == 1
        assert breakdown[0].n == 8
        assert breakdown[0].bin_range == (0.5, 0.6)

    def test_forecast_at_exactly_one_lands_in_top_bin(self):
        # Last bin's upper edge is inclusive so forecast=1.0 isn't dropped.
        _, breakdown = ece([1.0] * 3, [1.0] * 3)
        assert len(breakdown) == 1
        assert breakdown[0].bin_range[1] == pytest.approx(1.0)
        assert breakdown[0].n == 3


# -------------------------------------------------------- service integration


@pytest_asyncio.fixture
async def cal_svc_with_decision(db: Database):
    """CalibrationService + a backing decision row that has pi_selected_option_id set."""
    # Seed decision + recommended option so the calibration eligibility query has a hit.
    await db.execute(
        """INSERT INTO journal (id, type, content, source, confidence, importance, status, pinned, project_id)
           VALUES ('jrn_cal', 'note', 'src', 'brain', 'hypothesis', 'normal', 'active', 0, 'proj_default')""",
    )
    await db.execute(
        """INSERT INTO decisions (id, phase, question, decided_by, status, project_id)
           VALUES ('dec_cal', 'design', 'Q?', 'brain', 'active', 'proj_default')""",
    )
    await db.commit()
    svc = CalibrationService(db, project_id="proj_default")
    return svc, "dec_cal"


async def _seed_recommended_option(db: Database, decision_id: str, opt_id: str, confidence: float) -> None:
    """Insert a decision_options row + flip decisions.recommended_option_id."""
    await db.execute(
        """INSERT INTO decision_options
           (id, decision_id, project_id, label, summary, justification, explanation,
            pros, cons, evidence, confidence_verbal, confidence_numeric,
            confidence_evidence_strength, confidence_known_unknowns,
            effort_time, effort_reversibility, presentation_order_seed, is_recommended)
           VALUES (?, ?, 'proj_default', 'L', 'S', 'J', 'E',
                   '["p1","p2","p3"]', '["c1","c2","c3"]', '[]',
                   'moderate', ?, 'moderate', '["u1"]', 'M', 'reversible', 1, 1)""",
        [opt_id, decision_id, confidence],
    )
    await db.execute(
        "UPDATE decisions SET recommended_option_id = ?, pi_selected_option_id = ? WHERE id = ?",
        [opt_id, opt_id, decision_id],
    )
    await db.commit()


class TestRecordAndList:
    @pytest.mark.asyncio
    async def test_record_returns_outcome_with_cao_id(self, cal_svc_with_decision):
        svc, dec_id = cal_svc_with_decision
        out = await svc.record(dec_id, CalibrationOutcomeCreate(outcome="succeeded"))
        assert out.id.startswith("cao_")
        assert out.decision_id == dec_id
        assert out.outcome == "succeeded"
        assert out.recorded_by == "pi"

    @pytest.mark.asyncio
    async def test_list_for_decision_returns_both_outcomes(self, cal_svc_with_decision):
        svc, dec_id = cal_svc_with_decision
        await svc.record(dec_id, CalibrationOutcomeCreate(outcome="succeeded"))
        await svc.record(dec_id, CalibrationOutcomeCreate(outcome="failed", outcome_details="reverted"))
        rows = await svc.list_for_decision(dec_id)
        assert len(rows) == 2
        # Tied recorded_at within sub-millisecond inserts can flip the
        # tie-broken ORDER BY result. Assert membership instead of position.
        assert {r.outcome for r in rows} == {"succeeded", "failed"}

    @pytest.mark.asyncio
    async def test_list_all_filters_by_outcome(self, cal_svc_with_decision):
        svc, dec_id = cal_svc_with_decision
        await svc.record(dec_id, CalibrationOutcomeCreate(outcome="succeeded"))
        await svc.record(dec_id, CalibrationOutcomeCreate(outcome="failed"))
        await svc.record(dec_id, CalibrationOutcomeCreate(outcome="mixed"))
        succeeded = await svc.list_all(outcome_filter="succeeded")
        assert len(succeeded) == 1
        assert succeeded[0].outcome == "succeeded"


class TestComputeMetrics:
    @pytest.mark.asyncio
    async def test_metrics_below_threshold_returns_warning(self, cal_svc_with_decision):
        svc, dec_id = cal_svc_with_decision
        # No outcomes recorded yet — N=0.
        metrics = await svc.compute_metrics()
        assert metrics.n == 0
        assert metrics.metrics_available is False
        assert "Need" in (metrics.warning or "")
        assert metrics.brier_score is None
        assert metrics.ece is None

    @pytest.mark.asyncio
    async def test_metrics_unresolved_outcomes_excluded(self, cal_svc_with_decision):
        svc, dec_id = cal_svc_with_decision
        await _seed_recommended_option(svc.db, dec_id, "dop_one", 0.8)
        await svc.record(dec_id, CalibrationOutcomeCreate(outcome="unresolved"))
        metrics = await svc.compute_metrics()
        # Unresolved should be excluded; N=0 for eligibility.
        assert metrics.n == 0

    @pytest.mark.asyncio
    async def test_metrics_full_path_five_decisions(self, db: Database):
        """Seed 5 decisions, each with a recommended option + a recorded outcome."""
        svc = CalibrationService(db, project_id="proj_default")
        await db.execute(
            """INSERT INTO journal (id, type, content, source, confidence, importance, status, pinned, project_id)
               VALUES ('jrn_5', 'note', 'src', 'brain', 'hypothesis', 'normal', 'active', 0, 'proj_default')""",
        )
        cases = [
            ("dec_a", "dop_a", 0.8, "succeeded"),
            ("dec_b", "dop_b", 0.8, "succeeded"),
            ("dec_c", "dop_c", 0.8, "succeeded"),
            ("dec_d", "dop_d", 0.8, "succeeded"),
            ("dec_e", "dop_e", 0.8, "failed"),
        ]
        for dec_id, opt_id, conf, _ in cases:
            await db.execute(
                """INSERT INTO decisions (id, phase, question, decided_by, status, project_id)
                   VALUES (?, 'design', 'Q?', 'brain', 'active', 'proj_default')""",
                [dec_id],
            )
        await db.commit()
        for dec_id, opt_id, conf, outcome in cases:
            await _seed_recommended_option(db, dec_id, opt_id, conf)
            await svc.record(dec_id, CalibrationOutcomeCreate(outcome=outcome))

        metrics = await svc.compute_metrics()
        assert metrics.n == 5
        assert metrics.metrics_available is True
        # Brier per mission acceptance #7: f=0.8, 4 succeeded + 1 failed → 0.16.
        assert metrics.brier_score == pytest.approx(0.16)
        # ECE: only one populated bin [0.8, 0.9). accuracy=4/5=0.8, conf=0.8, gap=0.
        assert metrics.ece == pytest.approx(0.0)
        assert len(metrics.decisions_covered) == 5

    @pytest.mark.asyncio
    async def test_metrics_uses_most_recent_outcome_per_decision(self, cal_svc_with_decision):
        svc, dec_id = cal_svc_with_decision
        await _seed_recommended_option(svc.db, dec_id, "dop_recent", 0.6)
        # Two outcomes for the same decision; later supersedes.
        await svc.record(dec_id, CalibrationOutcomeCreate(outcome="failed"))
        await svc.record(dec_id, CalibrationOutcomeCreate(outcome="succeeded"))
        # Only 1 eligible decision so still below MIN_SAMPLES_FOR_METRICS.
        metrics = await svc.compute_metrics()
        assert metrics.n == 1
        assert metrics.metrics_available is False
        # The eligible decision shows up in coverage (proves the 'most recent'
        # query included it — succeeded, not failed, since failed was earlier).
        assert dec_id in metrics.decisions_covered
        assert metrics.n == len(metrics.decisions_covered)


# ============================================================
# Override-rate tracking (Mission 2 — v2.2.x)
# ============================================================
#
# Every test seeds a full slate so the single-SQL query exercises the
# real join across decisions + decision_options. _seed_slate creates N
# options per decision; one is recommended. Then the caller records the
# PI selection (or escape hatch). No outcomes needed — selection metrics
# run on a different denominator.


async def _seed_decision_with_options(
    db,
    decision_id: str,
    option_specs: list[dict],
    recommended_idx: int,
) -> list[str]:
    """Create a decision + options, mark one recommended. Returns list of option IDs.

    Each option spec is ``{"confidence": float, "dominated": bool}``. The
    recommended option is NEVER marked dominated.
    """
    await db.execute(
        """INSERT INTO decisions (id, phase, question, decided_by, status, project_id)
           VALUES (?, 'design', 'Q?', 'brain', 'active', 'proj_default')""",
        [decision_id],
    )
    option_ids: list[str] = []
    for i, spec in enumerate(option_specs):
        opt_id = f"dop_{decision_id}_{i}"
        option_ids.append(opt_id)
        is_recommended = 1 if i == recommended_idx else 0
        dominator = None
        if spec.get("dominated") and i != recommended_idx:
            # dominated_by points at the recommended option (any non-null value
            # meaning "Pareto-dominated" is enough; test doesn't care about
            # specific dominator).
            dominator = option_ids[recommended_idx] if option_ids else None
        await db.execute(
            """INSERT INTO decision_options
               (id, decision_id, project_id, label, summary, justification, explanation,
                pros, cons, evidence, confidence_verbal, confidence_numeric,
                confidence_evidence_strength, confidence_known_unknowns,
                effort_time, effort_reversibility, presentation_order_seed,
                is_recommended, dominated_by)
               VALUES (?, ?, 'proj_default', ?, 'S', 'J', 'E',
                       '["p1","p2","p3"]', '["c1","c2","c3"]', '[]',
                       'moderate', ?, 'moderate', '["u1"]', 'M', 'reversible',
                       ?, ?, ?)""",
            [opt_id, decision_id, f"opt_{i}", float(spec["confidence"]),
             i, is_recommended, dominator],
        )
    await db.execute(
        "UPDATE decisions SET recommended_option_id = ? WHERE id = ?",
        [option_ids[recommended_idx], decision_id],
    )
    await db.commit()
    return option_ids


async def _record_pi_selection(db, decision_id: str,
                               selected_option_id: str | None,
                               override_rationale: str | None) -> None:
    await db.execute(
        """UPDATE decisions
           SET pi_selected_option_id = ?, pi_override_rationale = ?
           WHERE id = ?""",
        [selected_option_id, override_rationale, decision_id],
    )
    await db.commit()


class TestOverrideRateMetrics:
    @pytest.mark.asyncio
    async def test_exact_match_contributes_zero(self, db):
        svc = CalibrationService(db, project_id="proj_default")
        option_ids = await _seed_decision_with_options(
            db, "dec_exact",
            [{"confidence": 0.8, "dominated": False},
             {"confidence": 0.6, "dominated": False}],
            recommended_idx=0,
        )
        await _record_pi_selection(db, "dec_exact", option_ids[0], None)
        result = await svc._compute_override_metrics()
        assert result["qualifying_decisions"] == 1
        assert result["override_rate"] == pytest.approx(0.0)
        assert result["escape_hatch_rate"] == pytest.approx(0.0)
        assert result["near_miss_rate"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_different_survivor_counts_override_and_near_miss(self, db):
        svc = CalibrationService(db, project_id="proj_default")
        option_ids = await _seed_decision_with_options(
            db, "dec_alt",
            [{"confidence": 0.8, "dominated": False},
             {"confidence": 0.7, "dominated": False}],  # other survivor
            recommended_idx=0,
        )
        await _record_pi_selection(db, "dec_alt", option_ids[1], None)
        result = await svc._compute_override_metrics()
        assert result["qualifying_decisions"] == 1
        assert result["override_rate"] == pytest.approx(1.0)
        assert result["escape_hatch_rate"] == pytest.approx(0.0)
        assert result["near_miss_rate"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_escape_hatch_defer_counts_override_not_near_miss(self, db):
        svc = CalibrationService(db, project_id="proj_default")
        await _seed_decision_with_options(
            db, "dec_defer",
            [{"confidence": 0.8, "dominated": False}],
            recommended_idx=0,
        )
        await _record_pi_selection(db, "dec_defer", None, "defer")
        result = await svc._compute_override_metrics()
        assert result["qualifying_decisions"] == 1
        assert result["override_rate"] == pytest.approx(1.0)
        assert result["escape_hatch_rate"] == pytest.approx(1.0)
        assert result["near_miss_rate"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_escape_hatch_all_four_rationale_forms(self, db):
        svc = CalibrationService(db, project_id="proj_default")
        for idx, rationale in enumerate(["defer", "reframe", "reject_all", "custom:not-a-real-option"]):
            dec_id = f"dec_esc_{idx}"
            await _seed_decision_with_options(
                db, dec_id,
                [{"confidence": 0.7, "dominated": False}],
                recommended_idx=0,
            )
            await _record_pi_selection(db, dec_id, None, rationale)
        result = await svc._compute_override_metrics()
        assert result["qualifying_decisions"] == 4
        assert result["override_rate"] == pytest.approx(1.0)
        assert result["escape_hatch_rate"] == pytest.approx(1.0)
        assert result["near_miss_rate"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_legacy_decisions_without_recommended_excluded(self, db):
        """Pre-v2.2 decisions (no recommended_option_id) never count."""
        svc = CalibrationService(db, project_id="proj_default")
        # Seed a legacy decision with NO recommended option + no PI selection columns populated.
        await db.execute(
            """INSERT INTO decisions (id, phase, question, decided_by, status, project_id)
               VALUES ('dec_legacy_pre_v22', 'design', 'legacy', 'brain', 'active', 'proj_default')""",
        )
        # Pretend PI also 'chose' something — shouldn't matter because recommended is NULL.
        await db.execute(
            "UPDATE decisions SET pi_override_rationale = 'defer' WHERE id = 'dec_legacy_pre_v22'",
        )
        await db.commit()
        result = await svc._compute_override_metrics()
        assert result["qualifying_decisions"] == 0
        assert result["override_rate"] is None
        assert result["escape_hatch_rate"] is None
        assert result["near_miss_rate"] is None

    @pytest.mark.asyncio
    async def test_selected_dominated_option_counts_override_not_near_miss(self, db):
        """Edge case: the UI should prevent this, but if a dominated option is
        somehow selected, it counts in override_rate but NOT near_miss_rate."""
        svc = CalibrationService(db, project_id="proj_default")
        option_ids = await _seed_decision_with_options(
            db, "dec_dom",
            [{"confidence": 0.8, "dominated": False},
             {"confidence": 0.5, "dominated": True}],  # dominated survivor
            recommended_idx=0,
        )
        await _record_pi_selection(db, "dec_dom", option_ids[1], None)
        result = await svc._compute_override_metrics()
        assert result["qualifying_decisions"] == 1
        assert result["override_rate"] == pytest.approx(1.0)
        assert result["near_miss_rate"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_presented_but_no_selection_excluded(self, db):
        """Decision has recommended option but PI hasn't selected yet — out of denominator."""
        svc = CalibrationService(db, project_id="proj_default")
        await _seed_decision_with_options(
            db, "dec_pending",
            [{"confidence": 0.7, "dominated": False}],
            recommended_idx=0,
        )
        # No _record_pi_selection call — both pi_selected_option_id and pi_override_rationale NULL.
        result = await svc._compute_override_metrics()
        assert result["qualifying_decisions"] == 0

    @pytest.mark.asyncio
    async def test_ten_decision_mixed_slate(self, db):
        """Acceptance #1 fixture: 10 decisions covering every scenario."""
        svc = CalibrationService(db, project_id="proj_default")
        # (a) exact match × 2
        for i in range(2):
            dec_id = f"dec_ex_{i}"
            opts = await _seed_decision_with_options(
                db, dec_id,
                [{"confidence": 0.8, "dominated": False},
                 {"confidence": 0.6, "dominated": False}],
                recommended_idx=0,
            )
            await _record_pi_selection(db, dec_id, opts[0], None)
        # (b) different survivor × 2
        for i in range(2):
            dec_id = f"dec_alt_{i}"
            opts = await _seed_decision_with_options(
                db, dec_id,
                [{"confidence": 0.8, "dominated": False},
                 {"confidence": 0.7, "dominated": False}],
                recommended_idx=0,
            )
            await _record_pi_selection(db, dec_id, opts[1], None)
        # (c) four escape hatches
        for idx, rat in enumerate(["defer", "reframe", "reject_all", "custom:foo"]):
            dec_id = f"dec_esc_{idx}"
            await _seed_decision_with_options(
                db, dec_id, [{"confidence": 0.7, "dominated": False}],
                recommended_idx=0,
            )
            await _record_pi_selection(db, dec_id, None, rat)
        # (g) two legacy decisions (no recommended)
        for i in range(2):
            await db.execute(
                """INSERT INTO decisions (id, phase, question, decided_by, status, project_id)
                   VALUES (?, 'setup', 'legacy Q', 'pi', 'active', 'proj_default')""",
                [f"dec_leg_{i}"],
            )
            await db.execute(
                "UPDATE decisions SET pi_override_rationale = 'defer' WHERE id = ?",
                [f"dec_leg_{i}"],
            )
        await db.commit()

        result = await svc._compute_override_metrics()
        # Denominator = 8 qualifying (2 exact + 2 alt + 4 escape, excluding 2 legacy).
        assert result["qualifying_decisions"] == 8
        # override_rate: 2 exact (0) + 2 alt (1) + 4 escape (1) → 6/8 = 0.75.
        assert result["override_rate"] == pytest.approx(6 / 8)
        # escape_hatch_rate: 4/8 = 0.5.
        assert result["escape_hatch_rate"] == pytest.approx(4 / 8)
        # near_miss_rate: 2/8 = 0.25 (only the 2 different-survivor picks qualify).
        assert result["near_miss_rate"] == pytest.approx(2 / 8)

    @pytest.mark.asyncio
    async def test_compute_metrics_integrates_override_fields(self, db):
        """compute_metrics (the public method) exposes the four new fields."""
        svc = CalibrationService(db, project_id="proj_default")
        opts = await _seed_decision_with_options(
            db, "dec_integrated",
            [{"confidence": 0.9, "dominated": False},
             {"confidence": 0.6, "dominated": False}],
            recommended_idx=0,
        )
        await _record_pi_selection(db, "dec_integrated", opts[1], None)
        metrics = await svc.compute_metrics()
        assert metrics.qualifying_decisions == 1
        assert metrics.override_metrics_available is False  # N<5
        assert metrics.override_rate == pytest.approx(1.0)
        assert metrics.near_miss_rate == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_override_metrics_available_flips_true_at_five(self, db):
        """Flag turns True once qualifying_decisions ≥ 5."""
        svc = CalibrationService(db, project_id="proj_default")
        for i in range(5):
            dec_id = f"dec_many_{i}"
            opts = await _seed_decision_with_options(
                db, dec_id,
                [{"confidence": 0.8, "dominated": False}],
                recommended_idx=0,
            )
            await _record_pi_selection(db, dec_id, opts[0], None)
        metrics = await svc.compute_metrics()
        assert metrics.qualifying_decisions == 5
        assert metrics.override_metrics_available is True

    @pytest.mark.asyncio
    async def test_zero_qualifying_returns_none_rates(self, db):
        """Empty project → rates are None, not 0.0."""
        svc = CalibrationService(db, project_id="proj_default")
        metrics = await svc.compute_metrics()
        assert metrics.qualifying_decisions == 0
        assert metrics.override_rate is None
        assert metrics.escape_hatch_rate is None
        assert metrics.near_miss_rate is None
        assert metrics.override_metrics_available is False
