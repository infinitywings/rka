# Researcher Heartbeat Debugging Notes

**Date:** 2026-03-20
**Problem:** Researcher heartbeat session repeatedly returned "I'm blocked" instead of processing pending RKA events.
**Timeline:** ~4 hours of debugging across multiple sessions.

---

## Symptoms

The researcher heartbeat session was stuck in a repeated failure loop:

```
I'm blocked: the available RKA environment here is still not usable...
Same situation. Still blocked.
```

Meanwhile, reviewer and executor heartbeats were working correctly.

---

## Incorrect Diagnoses Reached Along the Way

### 1. Heartbeat prompt wording problem
**Hypothesis:** The HEARTBEAT.md file had weak instructions that let the researcher conclude the environment was unusable.

**Action taken:** Rewrote HEARTBEAT.md with stronger live-API-first instructions, explicitly forbidding "environment unusable" claims unless HTTP API actually fails.

**Result:** No change. The researcher still repeated the same blocked message.

### 2. Session state / behavioral poisoning
**Hypothesis:** The long-lived researcher session had become stuck in a learned failure groove from earlier local-DB errors.

**Action taken:** Restarted OpenClaw gateway to refresh researcher session state.

**Result:** No change. The behavior persisted across the restart.

### 3. Researcher-specific MCP loading failure
**Hypothesis:** The researcher heartbeat was not loading RKA MCP tools the way manual ACP runs did.

**Action taken:** Investigated MCP configuration for the workspace.

**Result:** MCP config was present and correct. This was not the root cause.

### 4. Project selection / RKA CLI stale state
**Hypothesis:** The researcher was using a local workspace SQLite database that lacked project data.

**Action taken:** Confirmed workspace `config/mcporter.json` and `.mcp.json` were wired to the live RKA API at `http://localhost:9712`.

**Result:** Configuration was correct. Not the root cause.

---

## Actual Root Cause

**Two separate issues were conflated:**

### Issue A — OpenAI ChatGPT team plan usage limit (external)
All three heartbeat workers — executor, researcher, and reviewer — were running on `openai-codex/gpt-5.4`. The OpenAI team plan hit its usage quota:

```
"You have hit your ChatGPT usage limit (team plan). Try again in ~6517 min."
```

This was the **primary** reason the researcher heartbeat was failing. The "environment not usable" message was the model's misleading explanation when it was actually rate-limited.

**Evidence:**
- Session transcript showed: `stopReason: error, errorMessage: "You have hit your ChatGPT usage limit (team plan)."`
- The same error appeared for executor and reviewer when they were on gpt-5.4.
- Main session (MiniMax) was unaffected.

**Fix applied:** Switched all three heartbeat agents (executor, researcher, reviewer) from `openai-codex/gpt-5.4` to `minimax/MiniMax-M2.7` in `/Users/ceron/.openclaw/openclaw.json`.

### Issue B — Exec tool approval for automated heartbeat sessions (secondary)
After switching to MiniMax, researcher heartbeat started firing but hit a second blocker:

```
I'm blocked: all exec calls are rejected in this heartbeat session
(exec approval unavailable for automated heartbeats),
and the live RKA API at http://localhost:9712 is unreachable without it.
```

The heartbeat workers use `exec` to call the RKA API via `curl`/`python3`. The exec tool was blocked for automated sessions.

**What was tried:**
- Added `python3` and `curl` to the exec allowlist for researcher, reviewer, and executor agents via `openclaw approvals allowlist add`.

**What actually worked:**
- Reviewer succeeded without needing exec — it used MCP tools instead.
- Researcher continued to fail because it was still trying to use `exec` even after allowlisting.
- The researcher session was **behaviorally stuck** in a learned failure pattern: "exec blocked → environment unusable → give up."

**The key insight:** Reviewer succeeded because it naturally converged on MCP tools. Researcher failed because it kept trying `exec` even when MCP was available, and when `exec` was blocked, it gave up instead of switching tactics.

**Final fix for researcher:**
- Rewrote researcher's HEARTBEAT.md to explicitly prioritize MCP tools over exec/HTTP API.
- Changed instruction from "use live API" to "prefer MCP tools if available, fall back to HTTP only if MCP is completely unavailable."
- Researcher eventually broke out of the failure loop and started making real API calls — but took many cycles and processed old events before getting to the target event.

---

## Key Lessons Learned

### 1. Model pricing/availability is a real infrastructure risk
Using gpt-5.4 for automated heartbeat workers without dedicated quota is fragile. The team plan limit affected all three workers simultaneously and was non-obvious because the error manifested as a "blocked" message rather than a clear quota error.

**Recommendation:** Use a model with reliable quota (MiniMax, Claude, or a dedicated OpenAI key) for all automated workers. Do not mix automated and interactive usage on the same shared team plan.

### 2. "Environment not usable" from a model is a red herring
The researcher model (both gpt-5.4 and MiniMax) repeatedly claimed the environment was unusable. This was misleading — the actual blockers were:
- Quota limit (gpt-5.4)
- Exec blocking (MiniMax)

The model generated plausible-sounding explanations for its failure to act rather than genuinely diagnosing the issue.

**Recommendation:** When a model says "environment not usable," verify independently with direct API calls rather than accepting the model's self-reported diagnosis.

### 3. Behavioral patterns in long-lived sessions are sticky
The researcher session retained its failure behavior even after the original cause (quota limit) was removed. This suggests that session state / conversational history can anchor a role in a bad behavioral groove.

**Recommendation:** If a heartbeat session becomes behaviorally stuck, prefer a true session reset over further prompt tweaks. The current `openclaw sessions cleanup` tool does not prune sessions that are within retention policy, so a more aggressive reset mechanism may be needed.

### 4. MCP-first is more reliable than exec/HTTP for heartbeat workers
Reviewer succeeded consistently because it naturally converged on MCP tools. Researcher failed more often because it tried exec first. When exec was blocked, researcher gave up rather than switching to MCP.

**Recommendation:** Design heartbeat workers to prefer MCP tools exclusively, and treat exec/HTTP as a last resort rather than a primary path.

---

## Debugging Commands Used

```bash
# Check session status and model
openclaw status

# List all sessions with their models
openclaw sessions --all-agents --json

# Check specific session transcript
# (via sessions_history tool with sessionKey)

# Check exec approvals
openclaw approvals get --json

# Add exec allowlist for an agent
openclaw approvals allowlist add --agent researcher "python3"
openclaw approvals allowlist add --agent researcher "curl"

# Switch agent model in config
# Edit ~/.openclaw/openclaw.json agents.list[].model

# Restart gateway
openclaw gateway restart

# Send direct message to a session
# sessions_send with sessionKey

# Check RKA events directly
curl -sS http://localhost:9712/api/roles/{role_id}/events \
  -H 'X-RKA-Project: prj_01KKQM9JFG67GT5FGWTAHD9YE4'
```

---

## Timeline

| Time (EDT) | Event |
|---|---|
| ~19:00 | Researcher's gpt-5.4 hits usage limit. Starts returning "environment not usable." |
| ~19:30 | HEARTBEAT.md rewritten. No improvement. |
| ~19:45 | OpenClaw restarted. Behavior persists. |
| ~20:00 | Model switch to MiniMax-M2.7 attempted. |
| ~20:30 | Researcher still failing — now hitting exec blocking instead of quota. |
| ~21:00 | Reviewer succeeds (uses MCP). Researcher fails (uses exec). |
| ~21:45 | Exec allowlist added for all heartbeat agents. |
| ~22:00 | Researcher HEARTBEAT.md updated to prefer MCP. |
| ~22:55 | Researcher starts making real API calls. |
| ~23:53 | Direct intervention: researcher event manually acked + synthesis note written. |

---

## Files Modified During Debugging

- `/Users/ceron/.openclaw/openclaw.json` — switched heartbeat agents from gpt-5.4 to MiniMax-M2.7
- `/Users/ceron/.openclaw/exec-approvals.json` — added python3/curl allowlist for researcher, reviewer, executor
- `/Users/ceron/.openclaw/workspace-researcher/HEARTBEAT.md` — multiple rewrites
- `/Users/ceron/.openclaw/workspace-reviewer/HEARTBEAT.md` — rewrite
- `/Users/ceron/.openclaw/workspace-executor/HEARTBEAT.md` — rewrite
