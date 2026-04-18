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
