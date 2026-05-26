---
description: "Show parked PI interrupts awaiting response. Renders each interrupt's structured payload and offers accept/reject/correct via AskUserQuestion."
---

Call `orchestrator_inbox()` (no arguments — list across all runs).

If empty: say "No parked interrupts." and stop. Don't call any other tools.

If non-empty: load the `rka-orchestrator-pi` skill if not already loaded, then for each item render per its `interrupt_type`:

- **pi_greenlight** — show the Confirmation Brief (title, objective, approach, provenance journals). Use one-tap response.
- **pi_decision_select** — show each proposed action with content + source_artifact. Use **TWO-TAP** response (first AskUserQuestion picks Accept/Reject/Correct, second AskUserQuestion confirms ratification when Accept). This is the privileged write-authorization gate.
- **pi_acceptance** — show the final summary (artifact count, USD spent, final_report_id, terminal summary line). One-tap response.

When you have the PI's pick, call:
- Accept → `orchestrator_accept(interrupt_id)`
- Reject → `orchestrator_reject(interrupt_id, reason=...)`
- Correct → `orchestrator_correct(interrupt_id, response_text=...)`

On the tool's return, if a NEW interrupt is parked (the segment chained), repeat for that one. If terminal_state is in the response, surface the outcome to the user (complete / escalated / failed + final_report_id).

Never call the response tools without explicit human pick via AskUserQuestion.
