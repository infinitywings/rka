# Operational rollout v2 — Phase 2.5-validated brain pipeline, executor-permission blocker surfaced

**Mission**: `mis_01KRVM7BDCX0ATBERR6DAFTXZV` (Phase 2.6-operational-rollout-retry)
**Decision**: `dec_01KRVM4HSC0ASR1SBPPGG8CR1F` (Option A — narrow retry; Brain-ratified)
**Branch**: `agentic` at HEAD post-this-commit
**Date**: 2026-05-17
**Target mission**: `mis_01KRVF159FEHMYD55Q6EQ7BD18` (same as v1, 3 cross-reference items)
**Workflow thread**: `thr_op_rollout_v2_1779044069` (fresh; no collision with v1's two failed threads)

## Headline

**One run, deeper than v1 ever reached, surfaced a new architectural blocker.** Phase 2.5's fixes are empirically validated for the brain pipeline (`backbrief_draft` → `gate1_validation` → `decision_present` → `pi_decision_select`), but **0/3 cross-reference items completed the full cycle with an `rka_update_note` write** because the executor LLM running inside the `claude-agent-sdk` subprocess has no MCP or Bash tool permissions — it can think but cannot act. Per the Phase 2.6 mission spec, 0/3 succeeded triggers Phase 2.7-investigation as the next mandatory mission.

Two secondary issues stacked on top of the primary finding: (a) the driver's `interactive_interrupt` falls through to auto-accept on empty stdin (a buffered newline auto-ratified both remaining interrupts without PI review); (b) the `submit_report` node returned the input `mission_id` as the report identity rather than a fresh `rep_*` ID.

## What Phase 2.5 DID validate (concrete empirical evidence)

Comparing v1's two failed runs to v2's single run:

| Node | v1 first run | v1 retry | v2 run | Phase 2.5 fix validated? |
|---|---|---|---|---|
| `strategy_node` | ran (skeleton output) | ran (skeleton output) | ran (substantive output, wrapper-vs-target framing landed) | ✓ |
| `confirmation_brief` | ran | ran | ran (HIGH quality — 4-option decision-point table, sharp pause-triggers, budget envelope) | ✓ |
| `pi_greenlight` interrupt | fired | fired | fired (PI typed `a`; driver routed `"approve"` correctly) | ✓ (already worked) |
| `backbrief_draft` | not reached | ran (skeleton) | ran (substantive Backbrief with assumptions/risks/approach; gate1 APPROVED on first pass) | ✓✓ |
| `gate1_validation` | not reached | REDIRECTED (gate said "no substance") | **APPROVED** | ✓✓ (the central Phase 2.4 failure mode) |
| `pi_decision_select` interrupt | never fired | never fired | **fired** | ✓✓ (the Phase 2.5 acceptance target) |

The chain of nodes 1–6 succeeded for the first time in any operational rollout. Phase 2.5 T2/T3 (BRAIN_SYSTEM + EXECUTOR_SYSTEM fold) and T4/T5 (mission-body data flow) achieved exactly what they were designed to achieve.

Direct subprocess-process inspection during the run captured the live evidence: the bundled `claude` CLI subprocess spawned by `claude_agent_sdk._bundled/claude` (PID 20522 at the time of inspection) carried verbatim Phase 2.5 T3 delta prose in its `--system-prompt` command-line argument — Delta #1 (`info.version`), Delta #8 (`ErrorRecord over raising`), Delta #14b (`expected X, observed Y`), Delta #17 (`integrity error`) all present. The fold landed in the actual runtime, not just in unit tests.

## What v2 did NOT meet — acceptance criterion at the executor layer

The Phase 2.6 mission's gating criterion was *"at least 1 cross-reference item completes the full cycle: brain proposes → `pi_decision_select` interrupt fires → PI ratifies → executor commits → `rka_get(<journal_id>).related_decisions` is non-empty AND contains the ratified IDs."*

Concrete cycle-completion check post-run:

```
rka_get(jrn_01KQQ4K4GWFKHQBCQNC9F92JX4).related_decisions = null      # item 1 — HIGH-quality, 4 in-Provenance candidates
rka_get(jrn_01KMX18FDBEE9T8JNHHAP649TE).related_decisions = null      # item 2 — MEDIUM no-cites
rka_get(jrn_01KP4QR4XFP0ZHKR14B9ET6CN2).related_decisions = null      # item 3 — MEDIUM superseded
```

0/3. Floor not met. Per the mission spec's `T6` clause: *"if 0 items succeeded, Phase 2.7-investigation becomes mandatory."*

## Root cause — executor subprocess has no tool permissions

The `mission_execute` artifact (`jrn_01KRVND8YTFKCSHZ7WK0W7KSST`) is a verbatim self-report from the executor LLM running inside the `claude_agent_sdk._bundled/claude` subprocess:

> *"Tool execution is blocked. Without permission to call MCP or bash, I cannot perform any of T0–T6 (cannot resolve checkpoints, cannot invoke the driver, cannot make RKA writes, cannot inspect git state, cannot write the narrative doc, cannot commit). Per the executor skill, I'll produce the structured report you asked for, framed by the divergence."*
>
> *"Expected: 7 mission tasks executed (T0–T6). Observed: 0 tasks executed — 100% off."*

The executor LLM detected the permission denial path-by-path: `rka_get_status` denied → retry denied → `curl /api/capabilities` denied → `rka_submit_checkpoint` (which would escalate via the structured checkpoint surface) blocked by the same MCP grant → `AskUserQuestion` to PI surfaced but dismissed → defaulted to writing a divergence-as-headline journal report per Phase 2.5 Delta #14b.

This is **the first time an autonomous orchestrator run reached the executor LLM with permission to inspect (read RKA state) but without permission to write (commit cross-references)**. Phase 1's `pilot_t12.py` used a `PilotSDK` fake; the canned responses didn't depend on the subprocess permission model. Phase 2.4 never reached the executor (gate1 always REDIRECTED). Phase 2.5 added unit tests with `FakeMCP` doubles — same permission gap not exercised.

The architectural choice point for Phase 2.7-investigation is:

- **Option A** — make `make_sdk()` pass an MCP server config + Bash permission to the `ClaudeAgentSDK` subprocess so the executor LLM in that subprocess gets the same tool surface as the host Claude Code session has. Risk: every executor subprocess sees the full MCP tool surface, including write-side tools the executor LLM might call without orchestrator-state awareness. Needs a careful permission scope (read tools only? write tools only on specific entity types?).
- **Option B** — keep the executor subprocess permissions empty, and have the orchestrator's `mission_execute` node parse the LLM's structured output and translate it into MCP/Bash calls from the parent process. The LLM becomes a planner-only; the orchestrator becomes the actor. Closer to the original LangGraph design intent ("node functions are sync Python; LLM is one of the helpers"). Larger refactor of the executor node's contract.
- **Option C** — combine A + B: subprocess gets read-only MCP scope (so the executor LLM can `rka_get`, `rka_search`, etc. while planning), but all write-side tools (`rka_update_note`, `rka_add_note` with `executor`-authored content) execute from the parent process after the LLM proposes a structured plan that pi_node can ratify before commit.

Brain recommendation will land at the Phase 2.7 Backbrief gate; v2 narrative scope ends here.

## Secondary issue — driver stdin discipline (UX hazard)

The driver's `interactive_interrupt` (lines ~117-132) falls through on empty input:

```python
try:
    raw = input("PI > ").strip()
except EOFError:
    accept_token = _default_accept_token(kind)
    print(f"(stdin closed; defaulting to {accept_token!r})", file=sys.stderr)
    return accept_token

if raw == "a":
    return _default_accept_token(kind)
if raw == "r":
    return "reject"
if raw.startswith("c "):
    return raw[2:].strip()
return raw if raw else _default_accept_token(kind)   # ← empty Enter == auto-accept
```

In this run, PI typed `a` at `pi_greenlight` (correct). At `pi_decision_select`, a buffered newline (likely from the user pressing Enter while reading the prompt) was consumed by `input()` → empty string → fell through to `_default_accept_token("pi_decision_select")` → returned `"accept"` → orchestrator wrote `dec_01KRVNJCG5TCCXAG04K6VBQ97T` with `decided_by: "pi"`, `chosen: null`, tags `["pi-accepted", "thr_op_rollout_v2_1779044069"]`. Hollow ratification. Same path at `pi_acceptance` immediately after.

This was harmless this run only because the executor subprocess couldn't act on the ratification. If the Phase 2.7 fix to executor permissions ships first without also tightening driver stdin discipline, the same empty-Enter path would auto-commit unreviewed `rka_update_note` writes against live journal entries. Driver fix: empty Enter should re-prompt, not auto-accept. Only an explicit `EOFError` (Ctrl-D or piped/closed stdin) should fall through to the default token.

## Tertiary issue — `submit_report` returned `mission_id` as `report_id`

Inspect the artifact list:

```
- mis_01KRVF159FEHMYD55Q6EQ7BD18  (report)  by submit_report
- final_report_id: mis_01KRVF159FEHMYD55Q6EQ7BD18
```

Expected: a fresh `rep_*` ID. Observed: the input `mission_id` echoed back. The `executor.submit_report` node calls `mcp.rka_submit_report(content=..., related_mission=mission_id, summary=...)` and writes whatever the return value is to `state["final_report_id"]`. Either the REST endpoint `/api/reports` returned the mission_id by mistake, or `RestMCPClient.rka_submit_report` parsed the response wrong. Needs investigation under Phase 2.7's punch list; orthogonal to the primary executor-permission issue but cheap to fix while in the same area.

## What the brain produced — full quality assessment

### `strategy_node` (`jrn_01KRVN24C6KQPMH4S07WBC1TV3`)

POSITION line: *"Run is Phase 2.6 retry of `mis_01KRVF159FEHMYD55Q6EQ7BD18` under wrapper `mis_01KRVM7BDCX0ATBERR6DAFTXZV`; Backbrief already drafted at `jrn_01KRVMBHQABEYWADR3XBKWZ55R` — proceed to T0 checkpoint cleanup, then driver invocation with evidence guards."*

Wrapper-vs-target framing was independent and correct on first pass — exactly the structural distinction the Phase 2.6 mission spec's assumption #1 asked the brain to recognize. Phase 2.5 BRAIN_SYSTEM fold (Delta #2 gate cadence, Delta #16 Affordance F) and the mission-body data flow (T4) are both visibly informing this output.

### `confirmation_brief` (`jrn_01KRVN4GQN4GPH93D9RNY2DTT0`)

Substantive 4-section brief: (1) what this run will attempt, (2) 6 named assumptions including the wrapper-not-target framing, (3) decision-point table D0–D5 mapping interrupts to PI affordances, (4) budget envelope sized by floor/ideal/ceiling. Sharp mandatory-pause trigger list. Capabilities awareness (embeddings off, LLM health degraded → FTS5 + 22644-word queries; no `rka_ask`/`rka_generate_summary` on the verification path per anti-patterns #5, #8). Telemetry-zero default referenced. PI bandwidth sized at ~5 interrupts.

Only quibble: brief's "Awaiting PI greenlight to proceed with T0" framing assumed T0 cleanup was pending, but T0 had already run pre-driver (the executor session resolved the 3 diagnostic-residue checkpoints before invoking the driver). Brain synthesized this from my upfront Backbrief's narrative without re-querying open checkpoints. Cosmetic; didn't affect routing.

### `backbrief_draft` (`jrn_01KRVN87N6ABKX32N346GJR8BH`)

Substantive Backbrief mirroring Phase 2.5 design intent. Plan summary (T0–T6), acceptance-criteria interpretation, A1–A9 numbered assumptions each with a falsifier, risk register R1+, approach. Status: read-existing-entries / write-`related_decisions`-only; no code under `rka/`. The Backbrief that v1 never produced — Phase 2.5 T5's mission-body data flow is the proximate cause.

### `gate1_validation` (`jrn_01KRVN8SCM9RPTCFKFYEZMA93W`)

```
APPROVED:

The Backbrief is thorough and well-structured against all four gate criteria.
AC coverage is explicit: AC1 is correctly interpreted as a two-part identity
check (non-empty AND verbatim match to PI-ratified IDs), and AC2's
v1.md/v2.md ambiguity is surfaced as an open question with a defensible
default rather than buried. Assumptions A1–A9 are individually labeled and
each carries a concrete falsifier (git log, curl, EC#, etc.), satisfying
the explicitness bar. The risk register is comp[…]
```

Phase 2.4's REDIRECTED-at-gate1 cascade is structurally resolved.

### `decision_present` (`jrn_01KRVNJCFJXR2FGCVDDEQQM0MP`)

This is where the orchestrator topology diverged from the mission spec's per-item assumption. The brain produced a **meta-decision packet** asking *"How should the Phase 2.6 retry execute given that Phase 2.5 fixes are live, Backbrief is drafted, and the Executor is at the T0 gate?"* with 4 options (Full sequence / Floor-only / Compressed / Defer for Phase 2.7 investigation first) — not 3 per-item proposals about `related_decisions` for each of the cross-reference journals.

The orchestrator graph (`orchestrator/orchestrator/graph.py`) fires `decision_present` *once* per workflow run, not once per item. The mission spec's "per-item proposal" framing presumed an iteration construct that doesn't exist in the current topology. Whether this is an architectural finding to fold into Phase 2.7-investigation or simply a mission-spec/topology mismatch is a design call for the Brain — but the runtime is consistent with what `build_graph()` actually wires.

### `cluster_review`, `final_synthesis`

`cluster_review` and `final_synthesis` ran and journaled. Not load-bearing for this acceptance criterion; outputs are listed in the artifact summary above.

## PI ratification telemetry

- Greenlight: explicit `a` from PI → routed `"approve"` correctly.
- Decision-select: empty stdin → driver auto-accepted. Hollow ratification.
- Acceptance: empty stdin → driver auto-accepted. Hollow.

True PI ratification rate: 1/3 interrupts (33%). All three substantive proposals (greenlight, decision-select, acceptance) reached PI; only one received explicit input. This is a *driver* failure, not a *brain* failure — the brain produced reviewable proposals; the driver UX failed to compel review.

## Telemetry-zero compliance

✓ PASSED. Across this run:
- No third-party network calls detected (`notifications.py` defaults to bell + osascript per Phase 2.3 Delta #9).
- `ANTHROPIC_API_KEY` was set in env (per the Phase 2 anomaly inventory) but `make_sdk()` scrubbed it before SDK invocation; auth routed via macOS Keychain. Driver log line:
  > *"ANTHROPIC_API_KEY is set in env (would route to API billing). make_sdk() scrubs it before SDK invocation so auth falls through to Claude Max (credentials.json / Keychain)."*
- All MCP traffic was to `http://localhost:9712` (local RKA instance).
- All SDK traffic was to the bundled `claude` subprocess at `.venv/lib/python3.13/site-packages/claude_agent_sdk/_bundled/claude`.

## Branch state at Phase 2.6 close-out

- `agentic` HEAD: post-this-commit (the v2 narrative file). Bookkeeper invariant: `git diff main -- rka/services/worker.py = 0` throughout. agentic-branch invariant: `git diff main -- rka/ = 0` (this commit touches only `orchestrator/docs/` and `orchestrator/results/`).
- `main`: unchanged at `c063673`. Hub-and-spoke isolation preserved.
- No new release tag. `v2.5.3+agentic` final tag stands.
- Suite: 210 passing (no orchestrator code changes; tests unchanged).
- 3 diagnostic-residue checkpoints (chk_01KRSXNZ4XPN19KXR110Z4YRST, chk_01KRVFYYBBXJXC5DJ3TRN2QNNB, chk_01KRVGYZP5QYESG5PDDCYYT5Q9) resolved at T0 via Brain authority (assumption A4); open-checkpoint surface dropped to 2 (unrelated CHI 2027 paper-scaffold holds).

## Recommendations for follow-up

### Phase 2.7-investigation (mandatory — to be filed)

Scope (3 punch-list items, ordered by blocker severity):

1. **Executor subprocess tool permissions** (the central architectural blocker)
   - Code-trace `orchestrator/orchestrator/llm_client.py:make_sdk()` + `_RealSDKClient` for the subprocess invocation contract.
   - Decide between Options A / B / C above. Brain ratifies at Phase 2.7 Backbrief.
   - Add a regression test asserting the executor subprocess can perform at least one MCP write (e.g., a `rka_add_note` with a probe tag) before reaching real items.
2. **Driver stdin discipline** (UX hazard; cheap fix)
   - `orchestrator/scripts/driver.py:interactive_interrupt`: change the `return raw if raw else _default_accept_token(kind)` fallback so empty Enter re-prompts. Only `EOFError` should fall through to the default token.
   - Driver-side regression test covering the buffered-newline-after-`a` failure mode.
3. **`submit_report` ID-return bug** (orthogonal; cheap to fix in same mission)
   - Trace `RestMCPClient.rka_submit_report` against the REST `/api/reports` response shape.
   - Fix the parser or the REST endpoint (whichever returned `mission_id`).
   - Regression test asserting `report_id.startswith("rep_")`.

Estimated effort: 2-3 hours for items 2 + 3; item 1 is genuinely investigative (could be 4-8 hours depending on which option lands).

### Phase 2.8-or-later — retry the operational rollout

After Phase 2.7 ships, retry the same target (`mis_01KRVF159FEHMYD55Q6EQ7BD18`) with a fresh `workflow_thread_id`. Expected outcome: 1+ items complete the full cycle including `rka_update_note` writes. Acceptance criterion deferred from Phase 2.4 → 2.6 → 2.8 (or whichever number follows 2.7).

## Bookkeeper + agentic-branch invariants

✓ `git diff main -- rka/services/worker.py = 0` throughout Phase 2.6.
✓ `git diff HEAD -- rka/ = 0` for every commit on agentic in Phase 2.6 (all changes under `orchestrator/`).
✓ Push-after-every-commit + ls-remote verification carried through T0 RKA-side cleanup and will be verified at T5 (this commit).
