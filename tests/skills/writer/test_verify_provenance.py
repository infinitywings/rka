"""Tests for the Writer provenance verifier (P0/P1/P6).

The audit logic takes an injected resolver (entity_id -> dict|None), so these
run fully offline with no RKA server.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest


def _resolver(entities):
    def resolve(eid):
        return entities.get(eid)
    return resolve


JID = "jrn_01AAAAAAAAAAAAAAAAAAAAAAAA"
DID = "dec_01BBBBBBBBBBBBBBBBBBBBBBBB"
RID = "jrn_01CCCCCCCCCCCCCCCCCCCCCCCC"
SID = "dec_01DDDDDDDDDDDDDDDDDDDDDDDD"
MISSING = "lit_01ZZZZZZZZZZZZZZZZZZZZZZZZ"


def test_current_entity_with_support_passes(verify_provenance):
    tex = (
        f"% provenance: {JID} supports the claim below\n"
        "Per-fragment message integrity codes reduce malicious fragment acceptance to zero.\n"
    )
    ents = {JID: {"type": "journal", "status": "verified",
                  "content": "per-fragment message integrity code reduces malicious "
                             "fragment acceptance from baseline to zero percent"}}
    rep = verify_provenance.audit_text(tex, _resolver(ents))
    assert rep.verdict == "PASS"
    assert rep.citations[0].verdict == "OK"


def test_missing_entity_blocks(verify_provenance):
    tex = f"% provenance: {MISSING} supports the claim\nThe system sustains 500 updates per second.\n"
    rep = verify_provenance.audit_text(tex, _resolver({}))
    assert rep.verdict == "BLOCK"
    assert rep.citations[0].verdict == "MISSING"


def test_substantive_prose_without_provenance_blocks(verify_provenance):
    tex = "The system sustains 500 authenticated updates per second.\n"
    rep = verify_provenance.audit_text(tex, _resolver({}))
    assert rep.verdict == "BLOCK"
    assert rep.substantive_blocks == 1
    assert rep.uncovered_blocks == 1
    assert rep.citations[0].verdict == "UNCOVERED"


def test_malformed_provenance_marker_blocks(verify_provenance):
    tex = "% provenance: supports the claim below\nThe result improves recall.\n"
    rep = verify_provenance.audit_text(tex, _resolver({}))
    assert rep.verdict == "BLOCK"
    assert "MALFORMED" in rep.counts
    assert "UNCOVERED" in rep.counts


def test_empty_provenance_marker_is_malformed(verify_provenance):
    rep = verify_provenance.audit_text(
        "% provenance:\nThe result improves recall.\n", _resolver({})
    )
    assert rep.verdict == "BLOCK"
    assert "MALFORMED" in rep.counts


def test_orphan_provenance_marker_blocks(verify_provenance):
    tex = f"% provenance: {JID} supports the claim below\n"
    rep = verify_provenance.audit_text(tex, _resolver({JID: {"status": "tested"}}))
    assert rep.verdict == "BLOCK"
    assert rep.citations[0].verdict == "ORPHAN"


def test_latex_skeleton_without_prose_passes(verify_provenance):
    tex = "\\documentclass{article}\n\\begin{document}\n\\section{Results}\n\\end{document}\n"
    rep = verify_provenance.audit_text(tex, _resolver({}))
    assert rep.verdict == "PASS"
    assert rep.substantive_blocks == 0


def test_contiguous_markers_can_govern_one_prose_block(verify_provenance):
    tex = (
        f"% provenance: {JID} primary support\n"
        f"% provenance: {DID} PI boundary\n"
        "The measured result remains within the ratified boundary.\n"
    )
    entities = {
        JID: {"status": "tested", "content": "measured result remains within ratified boundary"},
        DID: {"status": "active", "content": "ratified boundary for measured result"},
    }
    rep = verify_provenance.audit_text(tex, _resolver(entities))
    assert rep.verdict == "PASS"
    assert rep.uncovered_blocks == 0


def test_superseded_entity_blocks(verify_provenance):
    tex = f"% provenance: {SID} supports the signature choice\nWe adopt Ed25519.\n"
    ents = {SID: {"type": "decision", "status": "superseded", "content": "use Ed25519"}}
    rep = verify_provenance.audit_text(tex, _resolver(ents))
    assert rep.verdict == "BLOCK"
    assert rep.citations[0].verdict == "STALE"


def test_superseded_with_ack_passes(verify_provenance):
    tex = (f"% provenance: {SID} superseded-ack: discussing the design evolution\n"
           "We initially adopted Ed25519 before revising to a post-quantum scheme.\n")
    ents = {SID: {"type": "decision", "status": "superseded", "content": "use Ed25519"}}
    rep = verify_provenance.audit_text(tex, _resolver(ents))
    assert rep.verdict == "PASS"
    assert rep.citations[0].verdict == "OK"
    assert rep.citations[0].acknowledged is True


def test_retracted_entity_blocks(verify_provenance):
    tex = f"% provenance: {RID} supports the replay claim\nThe MAC provides replay protection.\n"
    ents = {RID: {"type": "journal", "status": "retracted", "content": "MAC provides replay protection"}}
    rep = verify_provenance.audit_text(tex, _resolver(ents))
    assert rep.verdict == "BLOCK"
    assert rep.citations[0].verdict == "RETRACTED"


def test_contradicted_entity_warns_when_not_surfaced(verify_provenance):
    tex = (f"% provenance: {JID} supports the rekey cost\n"
           "Fleet key rotation costs roughly eight minutes of airtime.\n")
    ents = {JID: {"type": "journal", "status": "tested", "contradicted": True,
                  "content": "rotating the fleet multicast key costs roughly eight minutes airtime"}}
    # surfaced_terms with no disagreement vocab -> WARN
    rep = verify_provenance.audit_text(tex, _resolver(ents), surfaced_terms={"fleet", "rotation"})
    assert rep.verdict == "WARN"
    assert rep.citations[0].verdict == "CONTRADICTED"


def test_contradicted_entity_ok_when_disagreement_surfaced(verify_provenance):
    tex = (f"% provenance: {JID} supports the rekey cost\n"
           "An earlier estimate of six hours assumed a unicast rekey; that assumption does not hold.\n")
    ents = {JID: {"type": "journal", "status": "tested", "contradicted": True,
                  "content": "rotating the fleet multicast key costs roughly eight minutes airtime"}}
    rep = verify_provenance.audit_text(
        tex, _resolver(ents),
        surfaced_terms={"earlier", "estimate", "assumption", "revised"})
    assert rep.citations[0].verdict == "OK"


def test_thin_entity_content_is_not_flagged(verify_provenance):
    # Literature with no abstract: too thin to score -> OK, support unscored.
    tex = f"% provenance: {MISSING} supports the related-work claim\nPrior work studied FUOTA security.\n"
    ents = {MISSING: {"type": "literature", "status": "read", "content": "FUOTA"}}
    rep = verify_provenance.audit_text(tex, _resolver(ents))
    assert rep.citations[0].verdict == "OK"
    assert rep.citations[0].support is None


def test_clearly_unrelated_citation_low_support(verify_provenance):
    tex = (f"% provenance: {JID} supports the claim below\n"
           "Quantum error correction thresholds depend on surface code distance.\n")
    ents = {JID: {"type": "journal", "status": "verified",
                  "content": "battery exhaustion drains the meter cell over forty one days "
                             "under hourly forced firmware redownload across the fleet"}}
    rep = verify_provenance.audit_text(tex, _resolver(ents))
    assert rep.citations[0].verdict == "LOW_SUPPORT"
    assert rep.verdict == "WARN"


def test_rest_resolver_requires_server_project_attestation(
    verify_provenance, monkeypatch
):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: io.BytesIO(
            json.dumps({"id": JID, "content": "result", "status": "active"}).encode()
        ),
    )
    resolver = verify_provenance.make_rest_resolver(
        "http://localhost:9712", "prj_01PPPPPPPPPPPPPPPPPPPPPPPP"
    )
    with pytest.raises(RuntimeError, match="did not attest"):
        resolver(JID)


def test_rest_resolver_fails_closed_when_graph_is_unavailable(
    verify_provenance, monkeypatch
):
    def fake_urlopen(request, **_kwargs):
        if "/api/graph/ego/" in request.full_url:
            raise urllib.error.URLError("graph offline")
        return io.BytesIO(
            json.dumps({
                "id": JID,
                "project_id": "prj_01PPPPPPPPPPPPPPPPPPPPPPPP",
                "content": "result",
                "status": "active",
            }).encode()
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    resolver = verify_provenance.make_rest_resolver(
        "http://localhost:9712", "prj_01PPPPPPPPPPPPPPPPPPPPPPPP"
    )
    with pytest.raises(urllib.error.URLError, match="graph offline"):
        resolver(JID)


class TestEntailmentJudge:
    """Phase-2 support backend: injectable judge tightens the gate."""

    def test_judge_unsupported_overrides_lexical_pass(self, verify_provenance):
        # High lexical overlap, but the judge says the evidence does NOT
        # support the claim (e.g. negation): judge verdict wins.
        tex = (f"% provenance: {JID} supports the claim below\n"
               "Per-fragment integrity codes reduce malicious fragment acceptance to zero.\n")
        ents = {JID: {"type": "journal", "status": "verified",
                      "content": "per-fragment integrity codes did NOT reduce malicious "
                                 "fragment acceptance to zero in the follow-up replication run"}}
        rep = verify_provenance.audit_text(
            tex, _resolver(ents), judge=lambda c, e: False)
        assert rep.citations[0].verdict == "LOW_SUPPORT"
        assert "entailment judge" in rep.citations[0].detail

    def test_judge_supported_overrides_lexical_low(self, verify_provenance):
        # Paraphrase with near-zero token overlap: lexical would warn; the
        # judge recognizes the entailment.
        tex = (f"% provenance: {JID} supports the claim below\n"
               "Energy depletion attacks are mitigated by capping refetch frequency.\n")
        ents = {JID: {"type": "journal", "status": "verified",
                      "content": "battery exhaustion drains the meter cell over forty one "
                                 "days under hourly forced firmware redownload across fleet"}}
        rep = verify_provenance.audit_text(
            tex, _resolver(ents), judge=lambda c, e: True)
        assert rep.citations[0].verdict == "OK"

    def test_judge_abstain_falls_back_to_lexical(self, verify_provenance):
        tex = (f"% provenance: {JID} supports the claim below\n"
               "Quantum error correction thresholds depend on surface code distance.\n")
        ents = {JID: {"type": "journal", "status": "verified",
                      "content": "battery exhaustion drains the meter cell over forty one "
                                 "days under hourly forced firmware redownload across fleet"}}
        rep = verify_provenance.audit_text(
            tex, _resolver(ents), judge=lambda c, e: None)
        assert rep.citations[0].verdict == "LOW_SUPPORT"  # lexical floor holds

    def test_judge_not_consulted_for_stale_entities(self, verify_provenance):
        calls = []
        tex = f"% provenance: {SID} supports the claim\nWe adopt Ed25519.\n"
        ents = {SID: {"type": "decision", "status": "superseded", "content": "use Ed25519"}}
        rep = verify_provenance.audit_text(
            tex, _resolver(ents), judge=lambda c, e: calls.append(1) or True)
        assert rep.citations[0].verdict == "STALE" and not calls

    def test_make_llm_judge_none_without_model(self, verify_provenance, monkeypatch):
        monkeypatch.delenv("RKA_WRITER_JUDGE_MODEL", raising=False)
        monkeypatch.delenv("RKA_LLM_MODEL", raising=False)
        assert verify_provenance.make_llm_judge() is None
