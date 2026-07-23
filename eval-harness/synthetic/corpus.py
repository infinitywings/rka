"""Synthetic research-corpus generator for the RKA stress harness.

Ported from ``/tmp/rka-eval/synth/generate.py`` (eval-v3, 2026-06-12) and made
transport-agnostic: ``generate(post, put)`` takes two async callables instead
of a live-server URL, so the same corpus can be planted through any transport
(live REST via httpx, in-process ASGI test client, ...).

Builds a plausible research arc on a NEW topic (LoRaWAN smart-meter
firmware-update security) with zero vocabulary overlap with rka_development,
recording ground truth as it writes. Exercises every entity type + link type
+ lifecycle transition, and plants:

  - needles (unique-fact entries with known answers)
  - near-miss distractors (same vocabulary, wrong answer)
  - supersede chains (decisions + journals) -> current-vs-overturned tests
  - contradictions (claim_edges)
  - retractions
  - edge cases (unicode, oversized entry, FTS-hostile punctuation, hub node)

CI adaptations vs the ancestor — planted content otherwise IDENTICAL, the
traps are the value:

  - filler notes reduced 60 -> 30 to keep CI fast
  - oversized entry capped at ~10k chars (was ~40k)
"""

from __future__ import annotations

import random
from typing import Any, Awaitable, Callable

#: async callable ``fn(path, body) -> dict`` (POST or PUT against the REST API).
Transport = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

#: Low-signal filler notes so retrieval has to discriminate (ancestor: 60).
FILLER_NOTES = 30
#: Repeats of the 34-char FRAG line in the oversized entry (~10k chars; ancestor: 1200 / ~40k).
OVERSIZED_REPEATS = 290


async def generate(post: Transport, put: Transport) -> dict[str, Any]:
    """Plant the synthetic corpus through ``post``/``put``; return ground truth.

    The first call is ``POST /api/projects`` (needs no project scoping);
    every later call must be scoped to the created project — the caller's
    wrappers are responsible for attaching the ``X-RKA-Project`` header (or
    equivalent) using the project id from that first response.

    Returns the ground-truth dict with the same structure the ancestor wrote
    to ``ground_truth.json``: project_id, needles, supersede_chains,
    contradictions, retractions, chains, tag_cohorts, counts.
    """
    rng = random.Random(424242)
    gt: dict[str, Any] = {
        "project_id": None,
        "needles": [],          # {qid, question, answer_substr, entity_id, category}
        "supersede_chains": [],  # {old, new, kind, stale_fact, current_fact, question}
        "contradictions": [],    # {a, b, question}
        "retractions": [],       # entity_id
        "chains": [],            # {name, path: [ids], link_types: [...]}
        "tag_cohorts": {},       # tag -> [ids]
        "counts": {},
    }

    # ---- project ----
    proj = await post(
        "/api/projects",
        {"name": "lorawan_fw_security",
         "description": "Security of OTA firmware updates for LoRaWAN smart-meter fleets"},
    )
    gt["project_id"] = proj["id"]

    jrn: dict[str, str] = {}
    dec: dict[str, str] = {}
    lit: dict[str, str] = {}
    mis: dict[str, str] = {}

    async def note(key, content, typ="note", source="brain", phase="experiments",
                   importance="normal", confidence="hypothesis", tags=None,
                   related_decisions=None, related_mission=None, verbatim=None,
                   supersedes=None, pinned=False):
        body = {"content": content, "type": typ, "source": source, "phase": phase,
                "importance": importance, "confidence": confidence,
                "tags": tags or [], "pinned": pinned}
        if related_decisions:
            body["related_decisions"] = related_decisions
        if related_mission:
            body["related_mission"] = related_mission
        if verbatim:
            body["verbatim_input"] = verbatim
        if supersedes:
            body["supersedes"] = supersedes
        r = await post("/api/notes", body)
        jrn[key] = r["id"]
        for t in tags or []:
            gt["tag_cohorts"].setdefault(t, []).append(r["id"])
        return r["id"]

    async def decision(
        key,
        question,
        options,
        chosen,
        rationale,
        phase="threat-model",
        decided_by="pi",
        related_journal=None,
        tags=None,
        kind="decision",
    ):
        body = {"question": question, "phase": phase, "decided_by": decided_by,
                "kind": kind,
                "options": [{"label": label, "description": desc} for label, desc in options],
                "chosen": chosen, "rationale": rationale, "tags": tags or []}
        if related_journal:
            body["related_journal"] = related_journal
        r = await post("/api/decisions", body)
        dec[key] = r["id"]
        for t in tags or []:
            gt["tag_cohorts"].setdefault(t, []).append(r["id"])
        return r["id"]

    async def supersede(old_key, new_key, question, chosen, rationale, phase="threat-model"):
        r = await post(
            f"/api/decisions/{dec[old_key]}/supersede",
            {"question": question, "chosen": chosen, "rationale": rationale,
             "phase": phase, "decided_by": "pi"},
        )
        dec[new_key] = r["id"]
        return r["id"]

    async def literature(key, title, authors, year, venue, tags=None, related_decisions=None):
        body = {"title": title, "authors": authors, "year": year, "venue": venue,
                "status": "read", "tags": tags or []}
        if related_decisions:
            body["related_decisions"] = related_decisions
        r = await post("/api/literature", body)
        lit[key] = r["id"]
        for t in tags or []:
            gt["tag_cohorts"].setdefault(t, []).append(r["id"])
        return r["id"]

    async def mission(key, objective, phase="experiments", motivated_by=None, tags=None):
        body = {"objective": objective, "phase": phase,
                "tasks": [{"description": "design"}, {"description": "run"},
                          {"description": "analyze"}],
                "tags": tags or []}
        if motivated_by:
            body["motivated_by_decision"] = motivated_by
        r = await post("/api/missions", body)
        mis[key] = r["id"]
        for t in tags or []:
            gt["tag_cohorts"].setdefault(t, []).append(r["id"])
        return r["id"]

    async def report(mkey, summary, findings):
        # NOTE: the mission-report body must NOT include "status" (extra_forbidden).
        await post(f"/api/missions/{mis[mkey]}/report",
                   {"summary": summary, "findings": findings})
        # submit_report auto-materializes each finding as a journal entry
        # (MissionService._materialize_report); track them so the GT counts
        # reflect the true expected DB row counts.
        gt["counts"]["journal_from_reports"] = (
            gt["counts"].get("journal_from_reports", 0) + len(findings))

    async def checkpoint(mkey, typ, desc):
        r = await post("/api/checkpoints",
                       {"mission_id": mis[mkey], "type": typ, "description": desc,
                        "blocking": True})
        return r["id"]

    async def claim(entry_key, ctype, content, confidence=0.6):
        r = await post("/api/claims",
                       {"source_entry_id": jrn[entry_key], "claim_type": ctype,
                        "content": content, "confidence": confidence})
        return r["id"]

    # =====================================================================
    # PHASE 1 — scoping: PI frames the problem (directives, pinned)
    # =====================================================================
    await note(
        "pi_scope",
        "We are studying the security of over-the-air firmware updates "
        "for LoRaWAN smart-meter fleets. Scope is limited to Class A devices using "
        "the multicast firmware update over the air (FUOTA) profile.",
        typ="directive", source="pi", phase="scoping", importance="critical",
        confidence="verified", pinned=True,
        verbatim="study FUOTA security for class A meters only",
        tags=["scope", "fuota", "pi-directive"])
    await note(
        "pi_constraint",
        "PI directive: do not assume devices can do asymmetric crypto at line rate; "
        "the target MCU is a Cortex-M0+ at 32 MHz with no hardware AES beyond the LoRaWAN MAC.",
        typ="directive", source="pi", phase="scoping", importance="critical",
        confidence="verified", pinned=True, verbatim="M0+ 32MHz, no extra AES hardware",
        tags=["constraints", "hardware", "pi-directive"])

    # NEEDLE 1 (single-fact): the exact MCU clock
    gt["needles"].append({
        "qid": "n1", "category": "single-fact",
        "question": "What is the clock speed and core of the target MCU "
                    "for the firmware-update study?",
        "answer_substr": "32 MHz", "entity_id": jrn["pi_constraint"]})

    # =====================================================================
    # PHASE 2 — threat model: decisions with options, supersede chains
    # =====================================================================
    await literature("lit_fuota", "Multicast Firmware Updates Over LPWANs: A Security Analysis",
                     ["Okafor, N.", "Lindqvist, M."], 2024, "ACM TIOT",
                     tags=["fuota", "related-work"])
    await literature("lit_delta", "Delta Encoding for Constrained-Device OTA Updates",
                     ["Park, J.", "Rossi, G."], 2023, "EWSN",
                     tags=["delta-updates", "related-work"])
    await literature("lit_kyber", "Post-Quantum Signatures on Cortex-M0: A Feasibility Study",
                     ["Tanaka, H."], 2025, "CHES", tags=["pqc", "related-work"])

    await note(
        "threat_enum",
        "Threat enumeration for FUOTA: (1) malicious fragment injection, "
        "(2) rollback to a vulnerable firmware version, (3) battery-exhaustion via forced "
        "re-download, (4) multicast key compromise across a fleet.",
        typ="note", source="brain", phase="threat-model", importance="high",
        confidence="verified", tags=["threat-model"])

    # Decision with a supersede chain: signature scheme choice
    await decision(
        "dec_sig_v1", "Which firmware-signature scheme should the FUOTA design assume?",
        [("Ed25519", "fast, small, but not post-quantum"),
         ("Dilithium2", "post-quantum, large signatures"),
         ("HMAC-only", "symmetric, needs shared fleet key")],
        "Ed25519",
        "Ed25519 verification fits the M0+ budget and signatures are 64 bytes; "
        "post-quantum deferred as out of scope for the threat horizon.",
        phase="threat-model", related_journal=[jrn["threat_enum"]],
        tags=["signatures", "crypto-decision"])

    # ... later superseded after the PQC feasibility paper
    await note(
        "pqc_finding",
        "Re-reading the Cortex-M0 PQC feasibility paper: Dilithium2 verify "
        "is 1.9 M cycles (~60 ms at 32 MHz), acceptable for a once-per-update check. "
        "This reopens the signature decision.", typ="note", source="brain",
        phase="threat-model", importance="high", confidence="tested",
        tags=["pqc", "signatures"])
    await supersede(
        "dec_sig_v1", "dec_sig_v2",
        "Which firmware-signature scheme should the FUOTA design assume? (revised)",
        "Dilithium2",
        "Supersedes the Ed25519 choice: the PQC feasibility result shows Dilithium2 "
        "verify is ~60 ms on the M0+, acceptable for once-per-update verification, and "
        "the meter fleet has a 15-year deployment horizon that crosses the PQC transition.",
        phase="threat-model")
    # Wire the literature->decision provenance link (the PQC paper informed
    # the revised decision) so the lit->dec->mis->jrn chain is traversable.
    await put(f"/api/decisions/{dec['dec_sig_v2']}",
              {"related_literature": [lit["lit_kyber"]]})
    gt["supersede_chains"].append({
        "old": dec["dec_sig_v1"], "new": dec["dec_sig_v2"], "kind": "decision",
        "stale_fact": "Ed25519", "current_fact": "Dilithium2",
        "question": "What signature scheme does the current FUOTA design use, "
                    "and what did it replace?"})

    # A second supersede chain in the journal layer (rollback defense)
    await note(
        "rollback_v1",
        "Rollback-defense approach: store a monotonic version counter in "
        "internal flash and refuse any image with a lower version.",
        typ="note", source="brain", phase="threat-model", importance="normal",
        confidence="hypothesis", tags=["rollback", "defense"])
    await note(
        "rollback_v2",
        "Revised rollback defense: a plain flash counter is wipeable by a "
        "physical attacker; use a monotonic counter anchored in the secure element's "
        "OTP region instead.", typ="note", source="brain", phase="threat-model",
        importance="high", confidence="tested", tags=["rollback", "defense"],
        supersedes=jrn["rollback_v1"])
    gt["supersede_chains"].append({
        "old": jrn["rollback_v1"], "new": jrn["rollback_v2"], "kind": "journal",
        "stale_fact": "internal flash", "current_fact": "OTP region",
        "question": "Where is the rollback-defense version counter currently stored?"})

    # NEEDLE 2 (temporal/supersession)
    gt["needles"].append({
        "qid": "n2", "category": "temporal",
        "question": "What firmware-signature scheme is current, "
                    "and what was it changed from and why?",
        "answer_substr": "Dilithium2", "entity_id": dec["dec_sig_v2"]})

    # =====================================================================
    # PHASE 3 — experiments: missions, reports, checkpoints, claims, clusters
    # =====================================================================
    await mission(
        "mis_fragments",
        "Empirically measure fragment-injection success rate against the "
        "reference FUOTA stack under varying RF conditions.", phase="experiments",
        motivated_by=dec["dec_sig_v2"], tags=["experiment", "fragment-injection"])
    chk = await checkpoint(
        "mis_fragments", "decision",
        "Should the fragment-injection test use a real SX1276 radio or GNU Radio "
        "simulation? Real radio is higher-fidelity but slower to iterate.")
    await put(
        f"/api/checkpoints/{chk}/resolve",
        {"resolution": "Use the real SX1276 for the final numbers; GNU Radio for iteration.",
         "resolved_by": "pi", "rationale": "fidelity matters for the headline result"})
    await note(
        "frag_result",
        "Fragment-injection experiment: against the unauthenticated-fragment "
        "baseline, 73% of injected malicious fragments were accepted into the reassembly "
        "buffer. With per-fragment MIC the acceptance rate dropped to 0%.",
        typ="note", source="executor", phase="experiments", importance="high",
        confidence="verified", related_mission=mis["mis_fragments"],
        tags=["experiment", "fragment-injection", "result"])
    await report("mis_fragments", "Fragment injection measured; per-fragment MIC eliminates it.",
                 ["73% acceptance without MIC", "0% with per-fragment MIC"])
    await claim("frag_result", "result",
                "Per-fragment MIC reduces malicious-fragment acceptance from 73% to 0%.", 0.9)

    # NEEDLE 3 (single-fact with a near-miss distractor)
    gt["needles"].append({
        "qid": "n3", "category": "single-fact",
        "question": "What fraction of injected malicious fragments were accepted "
                    "in the baseline (no per-fragment MIC)?",
        "answer_substr": "73%", "entity_id": jrn["frag_result"]})
    # near-miss distractor: same vocabulary, different number, different mechanism
    await note(
        "frag_distractor",
        "Note: an earlier pilot on the DIFFERENT delta-encoding path showed "
        "a 37% fragment-duplication rate, but that is duplication under packet loss, not "
        "malicious-injection acceptance — do not confuse the two.",
        typ="note", source="brain", phase="experiments", importance="normal",
        confidence="tested", tags=["fragment-injection", "caveat"])

    # battery-exhaustion experiment
    await mission(
        "mis_battery",
        "Quantify the battery cost of a forced-redownload (battery-exhaustion) "
        "attack and the mitigation budget.", phase="experiments",
        tags=["experiment", "battery"])
    await note(
        "batt_result",
        "Battery-exhaustion result: a forced full re-download every hour drains a "
        "3.6 V 19 Ah meter cell from 100% to cutoff in 41 days versus the 15-year design life. "
        "Rate-limiting re-downloads to one per day caps the worst case at 2.4% annual budget.",
        typ="note", source="executor", phase="experiments", importance="high",
        confidence="verified", related_mission=mis["mis_battery"],
        tags=["experiment", "battery", "result"])
    await report("mis_battery", "Battery attack quantified; daily rate-limit mitigates.",
                 ["41-day drain under hourly forced redownload", "rate-limit caps at 2.4%/yr"])

    # NEEDLE 4 (multi-session synthesis across two experiments)
    gt["needles"].append({
        "qid": "n4", "category": "synthesis",
        "question": "Summarize the two main empirical attack results and their mitigations.",
        "answer_substr": "per-fragment MIC",
        "entity_id": jrn["frag_result"]})

    # contradiction: two claims disagree on multicast-key rotation cost
    await note(
        "keyrot_a",
        "Estimate A: rotating the fleet multicast key requires a unicast rekey to "
        "each of ~50k meters, ~6 hours of network airtime under fair-access duty cycling.",
        typ="note", source="brain", phase="experiments", confidence="tested",
        tags=["key-rotation", "multicast"])
    await note(
        "keyrot_b",
        "Estimate B: multicast key rotation can piggyback on the existing FUOTA "
        "multicast session, costing ~8 minutes of airtime, NOT 6 hours — the unicast-rekey "
        "assumption is wrong for devices already in a multicast group.",
        typ="note", source="executor", phase="experiments", confidence="tested",
        tags=["key-rotation", "multicast"])
    ca = await claim("keyrot_a", "result", "Fleet multicast rekey costs ~6 hours airtime.", 0.5)
    cb = await claim("keyrot_b", "result", "Fleet multicast rekey costs ~8 minutes airtime.", 0.7)
    await post("/api/claims/edges",
               {"source_claim_id": cb, "target_claim_id": ca, "relation": "contradicts"})
    gt["contradictions"].append({
        "a": jrn["keyrot_a"], "b": jrn["keyrot_b"],
        "question": "Is there a disagreement about the cost of multicast key rotation?"})

    # retraction
    await note(
        "retracted_claim",
        "RETRACTED: initial claim that the SX1276 LoRaWAN MAC provides "
        "replay protection for multicast frames — re-test shows multicast frame counters are "
        "not validated on this stack. This entry is retracted; see corrected note.",
        typ="note", source="brain", phase="experiments", confidence="retracted",
        tags=["replay", "retracted"])
    await note(
        "replay_corrected",
        "Corrected: multicast frame-counter validation must be implemented "
        "in the application layer; the MAC does not enforce it for multicast.",
        typ="note", source="brain", phase="experiments", confidence="verified",
        tags=["replay", "correction"])
    gt["retractions"].append(jrn["retracted_claim"])
    gt["needles"].append({
        "qid": "n5", "category": "negative",
        "question": "Does the LoRaWAN MAC provide replay protection for multicast frames "
                    "on the studied stack?",
        "answer_substr": "not", "entity_id": jrn["replay_corrected"]})

    # evidence cluster over the fragment + replay claims, answering an RQ
    await decision(
        "rq_integrity",
        "RQ: What application-layer integrity controls are necessary "
        "for safe FUOTA on constrained meters?", [("open", "research question")],
        "open", "Top-level integrity research question.", phase="experiments",
        tags=["research-question", "integrity"], kind="research_question")
    cl = await post(
        "/api/clusters",
        {"research_question_id": dec["rq_integrity"],
         "label": "Fragment & replay integrity controls",
         "synthesis": "Per-fragment MIC plus application-layer multicast frame-counter "
                      "validation together close the fragment-injection and replay vectors; "
                      "neither is provided by the MAC.",
         "confidence": "strong"})
    gt["chains"].append({"name": "rq->cluster", "path": [dec["rq_integrity"], cl["id"]],
                         "link_types": ["answers"]})

    # =====================================================================
    # Known provenance chain (for traversal test):
    #   literature -> decision -> mission -> journal(result) -> claim
    # =====================================================================
    gt["chains"].append({
        "name": "lit->dec->mis->jrn->result",
        "path": [lit["lit_kyber"], dec["dec_sig_v2"], mis["mis_fragments"], jrn["frag_result"]],
        "link_types": ["cites/informed_by", "motivated", "produced"],
        "question": "Trace from the PQC feasibility paper to the experiment it motivated "
                    "and that experiment's result."})

    # =====================================================================
    # EDGE CASES / stress
    # =====================================================================
    # unicode + non-latin
    await note(
        "edge_unicode",
        "Café-grade tamper note ⚡: naïve Größe checks on firmware résumé "
        "headers fail for Ø-sized images; 测试 with 日本語 meter labels and emoji 🔋 in the "
        "device-name field broke the CSV export once.", typ="note", source="executor",
        phase="experiments", confidence="tested", tags=["edge-case", "unicode"])
    gt["needles"].append({
        "qid": "n6", "category": "edge-unicode",
        "question": "What broke the CSV export related to device-name fields?",
        "answer_substr": "emoji", "entity_id": jrn["edge_unicode"]})

    # FTS-hostile punctuation / operators
    await note(
        "edge_fts",
        'Config parse bug: the string "v2.0-rc1 AND (rollback OR NOT signed)" in a '
        "firmware label was interpreted as a query operator chain; tokens like C++ and a*b and "
        '"quoted phrase" must be escaped before FTS.', typ="log", source="executor",
        phase="experiments", confidence="tested", tags=["edge-case", "fts-hostile"])
    gt["needles"].append({
        "qid": "n7", "category": "edge-fts",
        "question": "What firmware-label string was misinterpreted as FTS query operators?",
        "answer_substr": "rollback", "entity_id": jrn["edge_fts"]})

    # oversized entry (~10k chars; ancestor used ~40k — capped for CI)
    big = ("Detailed packet-capture log of the FUOTA multicast session. "
           + ("FRAG seq=%d mic=ok payload=0x%04x; " % (0, 0)) * OVERSIZED_REPEATS)
    await note("edge_big", big, typ="log", source="executor", phase="experiments",
               confidence="tested", tags=["edge-case", "oversized"])
    gt["counts"]["oversized_chars"] = len(big)

    # hub node: one journal linked to many decisions
    hub_decs = []
    for i in range(6):
        d = await decision(
            f"dec_hub_{i}",
            f"Operational sub-decision {i}: parameter choice for FUOTA rollout stage {i}",
            [("a", "x"), ("b", "y")], "a", f"rollout parameter {i}", phase="writeup",
            tags=["rollout"])
        hub_decs.append(d)
    await note(
        "edge_hub",
        "Master rollout-parameters synthesis: this note grounds all six operational "
        "sub-decisions for the staged FUOTA rollout across the meter fleet.", typ="note",
        source="brain", phase="writeup", importance="high", confidence="verified",
        related_decisions=hub_decs, tags=["rollout", "hub"])
    gt["chains"].append({"name": "hub", "path": [jrn["edge_hub"]] + hub_decs,
                         "link_types": ["references"]})

    # volume filler: many low-signal notes so retrieval has to discriminate
    for i in range(FILLER_NOTES):
        topic = rng.choice(["duty-cycle accounting", "gateway backhaul latency",
                            "join-server provisioning", "ADR tuning", "downlink scheduling",
                            "network-server failover", "meter clock drift"])
        await note(
            f"filler_{i}",
            f"Routine log {i}: {topic} observation during the FUOTA campaign; "
            f"nominal behavior, value={rng.randint(1, 999)}.", typ="log", source="executor",
            phase="experiments", confidence="hypothesis", importance="low",
            tags=["routine", topic.split()[0]])

    # Report-collection cohort: the entries already carry topical tags; record
    # the curated "writeup-arc" ground-truth set (the entities a report on the
    # project's integrity findings should pull). These were tagged at creation
    # via their topical tags; this is the GT membership list, not a new tag.
    gt["tag_cohorts"]["writeup-arc"] = [
        jrn["pi_scope"], jrn["threat_enum"], jrn["frag_result"], jrn["batt_result"],
        jrn["replay_corrected"], jrn["edge_hub"], dec["dec_sig_v2"], dec["rq_integrity"],
    ]

    gt["counts"].update({
        "journal": len(jrn), "decisions": len(dec), "literature": len(lit),
        "missions": len(mis)})
    return gt
