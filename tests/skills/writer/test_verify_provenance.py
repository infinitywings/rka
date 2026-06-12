"""Tests for the Writer provenance verifier (P0/P1/P6).

The audit logic takes an injected resolver (entity_id -> dict|None), so these
run fully offline with no RKA server.
"""

from __future__ import annotations


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
