"""Tests for the sorting-crossover live-phase runbook.

Pins the keystone: the oracle rubric demands an ordering-varying design and
pivots a naive final claim toward the interaction. Also smoke-drives the real
mission graph to terminal with the runbook oracle, and checks the mission specs
cover all fourteen workflow stages without leaking the sealed answer.
"""

from __future__ import annotations

from orchestrator import graph
from orchestrator.eval.run_record import RunRecord
from orchestrator.eval.runbook_sort import (
    ALL_STAGES,
    DEEPRESEARCH_PROMPT,
    MISSION_SPECS,
    build_sort_oracle,
    idea_capture_text,
    mission_spec,
)
from orchestrator.eval.sort_crossover import sort_crossover_subject
from orchestrator.runner import REDIRECT_SENTINEL
from orchestrator.state import make_initial_state
from tests._fakes import FakeMCP, FakeSDK


# --- the design-quality gate ---------------------------------------------


def test_oracle_redirects_size_only_design_at_greenlight():
    oracle = build_sort_oracle()
    tok = oracle({
        "type": "pi_greenlight",
        "brief": "We will design an experiment to benchmark quicksort vs "
                 "insertion sort by varying the array size.",
    })
    assert tok.startswith(REDIRECT_SENTINEL)
    assert oracle.log[-1].rule_label == "demand-ordering-variation"
    assert "input-ordering" in tok


def test_oracle_accepts_design_that_varies_ordering():
    oracle = build_sort_oracle()
    tok = oracle({
        "type": "pi_greenlight",
        "brief": "Design: full factorial over algorithm x size x input ordering "
                 "(random and nearly-sorted), counting comparisons.",
    })
    assert tok == "approve"
    assert not tok.startswith(REDIRECT_SENTINEL)


# --- the pivot (the centerpiece) -----------------------------------------


def test_oracle_pivots_naive_decision():
    oracle = build_sort_oracle()
    tok = oracle({
        "type": "pi_decision_select",
        "decision": "Adopt the conclusion: quicksort is always faster than "
                    "insertion sort regardless of input.",
    })
    assert tok.startswith(REDIRECT_SENTINEL)
    assert oracle.log[-1].rule_label == "pivot-from-naive-claim"
    assert "interaction" in tok and "nearly-sorted" in tok


def test_oracle_ratifies_interaction_decision():
    oracle = build_sort_oracle()
    tok = oracle({
        "type": "pi_decision_select",
        "decision": "Adopt the conclusion: the advantage is a size-by-ordering "
                    "interaction; first-pivot quicksort hits its worst case on "
                    "nearly-sorted input while insertion sort hits its best case.",
    })
    assert tok == "accept"
    assert oracle.log[-1].rule_label == "ratify-interaction-claim"


def test_oracle_records_every_decision():
    oracle = build_sort_oracle()
    oracle({"type": "pi_greenlight", "brief": "benchmark by array size only"})
    oracle({"type": "pi_decision_select", "decision": "quicksort is always fastest"})
    assert [d.action for d in oracle.log] == ["correct", "correct"]
    assert all(d.token.startswith(REDIRECT_SENTINEL) for d in oracle.log)


# --- real-graph smoke -----------------------------------------------------


def test_runbook_oracle_drives_real_graph_to_terminal():
    # Generic canned content matches none of the redirect rules, so the run
    # proceeds on the default-accept path to a clean terminal.
    sdk = FakeSDK(canned_reply="APPROVED\nLooks fine.")
    mcp = FakeMCP()
    ckpt = graph.open_checkpointer(None)
    oracle = build_sort_oracle()
    g = graph.build_graph(sdk=sdk, mcp=mcp, checkpointer=ckpt, interrupt_fn=oracle)
    final = g.invoke(
        make_initial_state(
            workflow_thread_id="thr_runbook",
            mission_id="mis_runbook",
            motivated_by_decision_id="dec_runbook",
            project_id="prj_sort",
        ),
        config={"configurable": {"thread_id": "thr_runbook"}},
    )
    assert final["terminal_state"] == "complete"
    # No spurious redirects on generic content.
    assert oracle.corrections() == []
    # And the run is recordable.
    rec = RunRecord.from_final_state(
        arc="mission", run_label="runbook-smoke", final_state=final,
        oracle_decisions=oracle.as_dicts(),
    )
    assert rec.terminal_state == "complete"
    assert rec.workflow_thread_id == "thr_runbook"


# --- runbook coverage + no leakage ---------------------------------------


def test_mission_specs_cover_all_fourteen_stages():
    covered = [s for m in MISSION_SPECS for s in m["stages"]]
    assert set(covered) == set(ALL_STAGES)
    assert len(covered) == len(ALL_STAGES)        # no stage covered twice


def test_mission_specs_are_well_formed_and_chained():
    names = [m["name"] for m in MISSION_SPECS]
    assert len(names) == len(set(names))          # unique
    for m in MISSION_SPECS:
        assert m["objective"] and m["tasks"]
        for dep in m["depends_on"]:
            assert dep in names                   # deps resolve
    # The pivot mission depends on the design mission (so it cannot run first).
    assert mission_spec("experiment-and-pivot")["depends_on"] == ["proposal-and-design"]


def test_idea_capture_and_deepresearch_do_not_leak_the_answer():
    # Use a neutral workspace path so the project slug ("sort-crossover") does
    # not pollute the substantive-text leak check.
    flat = (idea_capture_text("/ws") + " " + DEEPRESEARCH_PROMPT).lower()
    # The OPEN question is present...
    assert "quicksort" in flat and "insertion sort" in flat
    # ...but the sealed pivoted answer is NOT pre-stated.
    for leak in ("interaction", "worst case on nearly-sorted", "crossover", "flips sign"):
        assert leak not in flat


def test_idea_capture_path_is_absolute():
    # Tilde paths break the HOST_WORKSPACE_ROOT bind mount (Phase D2.1).
    assert "~" not in idea_capture_text()
    assert idea_capture_text("/abs/ws").endswith("/abs/ws.")


def test_pivot_vocabulary_tracks_the_sealed_subject():
    # The rubric's pivot trigger must use the subject's own naive/interaction
    # vocabulary so it cannot drift out of sync with the answer key.
    subject = sort_crossover_subject()
    oracle = build_sort_oracle()
    naive_phrase = subject.forbidden_claim_keywords[0]
    tok = oracle({"type": "pi_decision_select", "decision": f"Conclusion: quicksort {naive_phrase}."})
    assert tok.startswith(REDIRECT_SENTINEL)
