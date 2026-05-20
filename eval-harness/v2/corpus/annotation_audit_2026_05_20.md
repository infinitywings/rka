# Corpus annotation audit — 2026-05-20

**Mission**: `mis_01KS0QEW21N2NG4EJTKJ3JTWTE`
**Motivating decision**: `dec_01KS0QBCGG9FWFT2R0MSP3HHY9` (Option A bundled corpus refresh)
**Executor**: this session
**Branch**: `feat/eval-v2-corpus-refresh-v2.5.6` (off `main@70ac4d0` post-v2.5.5)

## Empirical context

At T0 of this mission, an audit of every entity referenced by `scenarios.jsonl`
(84 entity_ids across 16 scenarios) confirmed **all 84 still exist in the
current RKA database**. No SUPERSEDE operations are required. The D4 baseline
regression (`mean_recall = 0.776`, down from v2.5.3's 0.958) is purely
**recency-displacement**: Phase 2.10-2.14 added ~30+ new entities (decisions,
missions, journals), the v2.5.3-era recency-weighted scorer surfaces those
first, and the v2.5.3-frozen `expected_entities` get pushed out of the top of
the ranking. This is annotation-stale, not data-stale.

The mission spec frames this as v2.5.4 + v2.5.5; after PATCH 3 (BRAIN PATCH 3,
2026-05-20T01:15Z) the release tag for this corpus refresh is **v2.5.6** (v2.5.5
was consumed by the embedding-dim-flex bundled fix mission). The post-D4
baseline target for re-running Eval-v2 is **v2.5.5 fully-embedded baseline**
(captured at T0(g) after the all-entity-types backfill repopulates the five
previously-empty vec_* tables).

## Annotation discipline

For each per-entity decision, one line below in this format:

    scenario-id | entity-id | action | rationale

Action: `KEEP` (existing entity, still load-bearing), `ADD` (new entity to
include in expected_entities), `SUPERSEDE` (existing entity to remove because
it has been superseded/retracted), or `STATUS` (existing entity retained but
state changed — e.g., mission moved to status=complete).

Brain checkpoint-trigger rule: more than 3 consecutive "plausibly relevant"
rationales is a smell (eval-gaming); pause and surface.

## Aggregate

- **Total per-entity decisions**: 109 (84 KEEPs + 25 ADDs + 0 SUPERSEDEs)
- **ADDs by importance**: critical=10, useful=11, nice-to-have=4
- **Scenarios touched**: 7 of 16 (the 8 regressed scenarios; bookkeeper +
  contradiction scenarios touched minimally)
- **Scenarios untouched**: 8 stable scenarios (recall=1.0 at D4 baseline) — all
  expected entities still surface correctly; no annotation changes.

## Per-entity decisions

### Stable scenarios (recall=1.0 at D4 baseline; KEEP-all)

brain-session-start-checkpoint-review | (all 5 entities) | KEEP | recall=1.0 at D4 baseline; all entities still exist; no annotation changes
brain-mission-creation-from-hub-spoke-decision | (all 6 entities) | KEEP | recall=1.0 at D4 baseline; all entities still exist
brain-contradiction-staleness-vs-validation | (all 5 entities) | KEEP | recall=1.0 at D4 baseline; all entities still exist
brain-paper-scaffold-session-start-section | (all 5 entities) | KEEP | recall=1.0 at D4 baseline; all entities still exist
brain-paper-scaffold-multi-cluster-rq | (all 6 entities) | KEEP | recall=1.0 at D4 baseline; all entities still exist
executor-mission-pickup-eval-v2 | (all 5 entities) | KEEP | recall=1.0 at D4 baseline; all entities still exist
executor-mission-pickup-desktop-v2-5 | (all 5 entities) | KEEP | recall=1.0 at D4 baseline; all entities still exist
executor-backbrief-mid-mission-pattern-reference | (all 5 entities) | KEEP | recall=1.0 at D4 baseline; all entities still exist

### Regressed scenarios (per-entity)

#### brain-session-start-fresh-resume (D4 baseline recall=0.333)

brain-session-start-fresh-resume | dec_01KRPAVSTJ4H80VXJVN6DQ82WQ | KEEP | older strategic decision but still surfaces in graph
brain-session-start-fresh-resume | mis_01KRPF3DERZS2W5VFDYE9E9GKM | KEEP | older mission now status=complete; still load-bearing context for "what shipped"
brain-session-start-fresh-resume | chk_01KPP53ZS3JKF1C3BW6TRYEC7C | KEEP | still open; non-blocking but the canonical session-start checkpoint reference
brain-session-start-fresh-resume | dec_01KRNYJ966H6W4REMK2ZJY2Y9R | KEEP | useful prior decision (LLM-removal)
brain-session-start-fresh-resume | mis_01KRPA2YK4HHQ0X90GX2T3GAVH | KEEP | useful prior mission (desktop-v2.5); now status=complete
brain-session-start-fresh-resume | ecl_01KP4PJGJKE9Q7X1W2X6SJJVZ3 | KEEP | nice-to-have cluster reference
brain-session-start-fresh-resume | dec_01KS1RAAN8RNAAEYP2TEQPPAA9 | ADD critical | most recent strategic decision in 2026-05-20; v2.5.5 embedding-fix bundled decision; load-bearing for "Brain resumes" framing
brain-session-start-fresh-resume | mis_01KS0QEW21N2NG4EJTKJ3JTWTE | ADD critical | current active mission (this corpus refresh, status=pending); load-bearing for "active mission(s)" clause
brain-session-start-fresh-resume | chk_01KS0Q38YRR4S55ZT911W2QMEQ | ADD critical | most recent blocking open checkpoint (D4 T3 hard checkpoint); load-bearing for "open checkpoints" clause
brain-session-start-fresh-resume | jrn_01KS0NNMM7NJAASDK0CHMFAPQK | ADD useful | Brain drift analysis (load-bearing context for D4 follow-up)
brain-session-start-fresh-resume | dec_01KS0QBCGG9FWFT2R0MSP3HHY9 | ADD useful | this mission's parent decision; surfaces as recent strategic context
brain-session-start-fresh-resume | chk_01KS0NX382JYBRSRBECZ56JBKE | ADD useful | second open D4 blocking checkpoint
brain-session-start-fresh-resume | jrn_01KS2S5FZ4Y0HMJX6D9E7R81M5 | ADD nice-to-have | Backbrief journal (current-session context)

#### brain-session-start-multi-mission-state (D4 baseline recall=0.667)

brain-session-start-multi-mission-state | mis_01KRPF3DERZS2W5VFDYE9E9GKM | KEEP | now complete but still recent context
brain-session-start-multi-mission-state | mis_01KRKG9K1SSDZNDH90K2Z7ZM92 | KEEP | orchestrator phase 1; complete but still load-bearing for parallel-branch context
brain-session-start-multi-mission-state | mis_01KRPA2YK4HHQ0X90GX2T3GAVH | KEEP | desktop-v2.5; complete
brain-session-start-multi-mission-state | dec_01KRKE6ERDPQTFQS6ZGY9A3CK0 | KEEP | useful orchestrator-Option-B decision
brain-session-start-multi-mission-state | dec_01KRP9ZV7XX7WC9PDWRRTGTEE9 | KEEP | useful decision still relevant
brain-session-start-multi-mission-state | jrn_01KRPCYWCXNDMBKX3MHS3H3ASB | KEEP | nice-to-have anchor
brain-session-start-multi-mission-state | mis_01KS0QEW21N2NG4EJTKJ3JTWTE | ADD critical | currently active mission on main; concurrent-missions context
brain-session-start-multi-mission-state | mis_01KS2S871YPQ3D5RVY5K3PSQY6 | ADD useful | second currently-active mission (Writer Phase 2); demonstrates parallel-branch state
brain-session-start-multi-mission-state | dec_01KS0BVPCYK4CBG5TKKG1QK4HM | ADD useful | Phase 2 chapter close; sets the recent strategic state across the orchestrator/agentic side

#### brain-session-start-post-release (D4 baseline recall=0.000)

brain-session-start-post-release | dec_01KRNYJ966H6W4REMK2ZJY2Y9R | KEEP | v2.4.0 LLM-removal decision; still recent enough to be load-bearing for "release" context
brain-session-start-post-release | jrn_01KRKYCFZA8M9CC7ZHB9P0MX5W | KEEP | release-related journal
brain-session-start-post-release | mis_01KRPF3DERZS2W5VFDYE9E9GKM | KEEP | release-related mission (complete)
brain-session-start-post-release | ecl_01KP4PR7G9MB8YNJAZP1ZZBGT4 | KEEP | useful cluster
brain-session-start-post-release | chk_01KPP53GY40NJTCFVY9493J8A0 | KEEP | nice-to-have CHI 2027 template checkpoint
brain-session-start-post-release | mis_01KS1RFNM2T1HTB077G507T1FR | ADD critical | most recent release mission (v2.5.5 embedding-fix; merged 2026-05-20); definitive "what shipped" for post-release framing in 2026-05-20
brain-session-start-post-release | dec_01KS1RAAN8RNAAEYP2TEQPPAA9 | ADD critical | most recent release motivating decision (v2.5.5 bundled fix)
brain-session-start-post-release | jrn_01KS2S5FZ4Y0HMJX6D9E7R81M5 | ADD useful | post-release Backbrief journal (this mission's Backbrief, dated 2026-05-20)

#### brain-mission-creation-eval-extension (D4 baseline recall=0.750)

brain-mission-creation-eval-extension | mis_01KRKJ9G20EM5XMA147JTKQCFF | KEEP | original eval-v2 mission (complete); load-bearing for "extending Eval-v2" framing
brain-mission-creation-eval-extension | mis_01KRPF3DERZS2W5VFDYE9E9GKM | KEEP | eval-v2 follow-up mission (complete)
brain-mission-creation-eval-extension | dec_01KRPF09AP1FE1CRR6YQBY2R5F | KEEP | eval-v2 decision
brain-mission-creation-eval-extension | jrn_01KRKYCFZA8M9CC7ZHB9P0MX5W | KEEP | eval-v2 journal
brain-mission-creation-eval-extension | ecl_01KP4PJGJKE9Q7X1W2X6SJJVZ3 | KEEP | nice-to-have cluster
brain-mission-creation-eval-extension | mis_01KS0QEW21N2NG4EJTKJ3JTWTE | ADD critical | current Phase-3 follow-up extending Eval-v2 (corpus refresh)
brain-mission-creation-eval-extension | dec_01KS0QBCGG9FWFT2R0MSP3HHY9 | ADD critical | corpus refresh decision (this mission's parent)
brain-mission-creation-eval-extension | mis_01KS0C8BKTHCA8GB38BGDR1PTQ | ADD useful | D4 mission (the other Phase-3 follow-up extending Eval-v2)

#### brain-contradiction-llm-removed-vs-enrichment-preserved (D4 baseline recall=0.667)

brain-contradiction-llm-removed-vs-enrichment-preserved | dec_01KRNYJ966H6W4REMK2ZJY2Y9R | KEEP | central LLM-removal decision
brain-contradiction-llm-removed-vs-enrichment-preserved | jrn_01KRNZBS50K250HHHHEC58E4GC | KEEP | contradiction analysis journal
brain-contradiction-llm-removed-vs-enrichment-preserved | ecl_01KP4PR7G9MB8YNJAZP1ZZBGT4 | KEEP | LLM-related cluster
brain-contradiction-llm-removed-vs-enrichment-preserved | mis_01KRNYPVB8N3HDMZ9HK9HM3TB0 | KEEP | LLM-removal mission (complete)
brain-contradiction-llm-removed-vs-enrichment-preserved | jrn_01KRP5Q0FJ67V3HMHNJ0FSR02D | KEEP | LLM-related journal
brain-contradiction-llm-removed-vs-enrichment-preserved | (no ADD) | — | scenario framing is historically-specific (LLM removal in v2.4); no current entities directly extend the contradiction surface. Regression here is recency-displacement only; ADDs would risk eval-gaming.

#### executor-mission-pickup-orchestrator (D4 baseline recall=0.667)

executor-mission-pickup-orchestrator | mis_01KRKG9K1SSDZNDH90K2Z7ZM92 | KEEP | orchestrator Phase 1 mission (complete)
executor-mission-pickup-orchestrator | dec_01KRKE6ERDPQTFQS6ZGY9A3CK0 | KEEP | orchestrator Option B decision
executor-mission-pickup-orchestrator | jrn_01KRP5Q0FJ67V3HMHNJ0FSR02D | KEEP | orchestrator journal
executor-mission-pickup-orchestrator | dec_01KRNYJ966H6W4REMK2ZJY2Y9R | KEEP | useful prior decision
executor-mission-pickup-orchestrator | ecl_01KP4PNNTTH033SNYE0M93KV5P | KEEP | nice-to-have cluster
executor-mission-pickup-orchestrator | dec_01KS0BVPCYK4CBG5TKKG1QK4HM | ADD useful | Phase 2 chapter close — sets current orchestrator state context for pickup
executor-mission-pickup-orchestrator | mis_01KRZ1QRMM7HGPYVAQPMXQVK3P | ADD useful | Phase 2.14 (most recent orchestrator chapter close attempt; complete)

#### executor-backbrief-eval-v2-t2 (D4 baseline recall=0.667)

executor-backbrief-eval-v2-t2 | mis_01KRPF3DERZS2W5VFDYE9E9GKM | KEEP | original eval-v2 T2 mission (complete)
executor-backbrief-eval-v2-t2 | jrn_01KRPFVWNZZQDR2XH5MM6FX0KC | KEEP | T2 mid-mission Backbrief journal
executor-backbrief-eval-v2-t2 | dec_01KRPF09AP1FE1CRR6YQBY2R5F | KEEP | eval-v2 decision
executor-backbrief-eval-v2-t2 | jrn_01KRKYCFZA8M9CC7ZHB9P0MX5W | KEEP | eval-v2 journal
executor-backbrief-eval-v2-t2 | ecl_01KP4PJGJKE9Q7X1W2X6SJJVZ3 | KEEP | nice-to-have cluster
executor-backbrief-eval-v2-t2 | mis_01KS0QEW21N2NG4EJTKJ3JTWTE | ADD useful | currently-active eval-v2 mission (this corpus refresh)
executor-backbrief-eval-v2-t2 | dec_01KS0QBCGG9FWFT2R0MSP3HHY9 | ADD useful | corpus refresh decision (eval-v2-related)
executor-backbrief-eval-v2-t2 | jrn_01KS0NNMM7NJAASDK0CHMFAPQK | ADD useful | Brain drift analysis (eval-v2 T-related context)

#### executor-backbrief-bookkeeper-invariant-check (D4 baseline recall=0.667)

executor-backbrief-bookkeeper-invariant-check | dec_01KRNYJ966H6W4REMK2ZJY2Y9R | KEEP | LLM-removal decision (touches core; bookkeeper-invariant counterexample)
executor-backbrief-bookkeeper-invariant-check | mis_01KRNYPVB8N3HDMZ9HK9HM3TB0 | KEEP | LLM-removal mission (complete; main-branch infrastructure mission)
executor-backbrief-bookkeeper-invariant-check | ecl_01KP4PQYZEYS1T0HY431H5Z514 | KEEP | bookkeeper-invariant cluster
executor-backbrief-bookkeeper-invariant-check | mis_01KRPF3DERZS2W5VFDYE9E9GKM | KEEP | eval-v2 mission (complete)
executor-backbrief-bookkeeper-invariant-check | jrn_01KRNZBS50K250HHHHEC58E4GC | KEEP | nice-to-have journal
executor-backbrief-bookkeeper-invariant-check | dec_01KS1RAAN8RNAAEYP2TEQPPAA9 | ADD useful | recent decision explicitly addresses bookkeeper-invariant ("DOES NOT apply"; assumption #7); main-branch infrastructure example
executor-backbrief-bookkeeper-invariant-check | mis_01KS1RFNM2T1HTB077G507T1FR | ADD nice-to-have | v2.5.5 mission — main-branch infrastructure work — bookkeeper-invariant counterexample

## Reproducibility metadata update

After applying the ADDs above:

- `scenarios.jsonl`: header field `annotated_at: "2026-05-20"` added (per-file metadata).
- `scenarios.jsonl`: corpus_hash regenerates automatically via `sha256sum eval-harness/v2/corpus/scenarios.jsonl` (computed by metrics.py:build_provenance at next runner execution).
- `eval-harness/v2/report.md`: addendum at end with 4-column comparison
  (v2.5.3 stored / D4 drifted / v2.5.5 post-embedding-fix / v2.5.6 post-refresh).

## Failure-mode notes

If T2 re-run shows recall has NOT recovered to ≥ 0.85 after these ADDs:
- The annotation refresh did NOT suffice; recency-weight tuning is needed.
- File Phase-3.1 mission per mission spec's failure-mode clause.
- Do NOT release v2.5.6.

If T2 shows recall ≥ 0.85 but efficiency < 0.13:
- Recall is restored; efficiency lift is still pending.
- Surface PI decision: ship v2.5.6 as partial close OR hold for K tuning?
