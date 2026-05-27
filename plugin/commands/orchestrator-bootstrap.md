---
description: "Bootstrap orchestrator-level credentials (Phase B): discuss install state, ratify catalog subset, write orchestrator/.env template, probe filled keys. Usage: /orchestrator-bootstrap"
---

Phase B is **orchestrator-level** credential setup. Use this on a fresh install before any project exists — it writes `orchestrator/.env` so the daemon itself can call Claude. This is distinct from `/orchestrator-onboard` (which writes per-project credentials at `~/rka-projects/<id>/.env`).

Before kicking off:
1. `orchestrator_health()` — verify the daemon is reachable. If not, the user must bring up `rka-orchestrator` via the Compose overlay (`docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d --build`).
2. Check whether `orchestrator/.env` is already filled. If so, ask via `AskUserQuestion`: "orchestrator/.env appears to be set already. Re-bootstrap (will write a fresh `.env.example` next to the live file; the live file is NOT overwritten — you pick what to copy across)?" Proceed only on confirm.
3. On confirm: `orchestrator_bootstrap_start()`.

After `orchestrator_bootstrap_start` returns:
- Returns `{parked_interrupt_id, parked_interrupt_type: "pi_bootstrap_intent", ...}`.
- Load the `rka-orchestrator-pi` skill if not already loaded.
- Render the intent prompt: ask the PI to describe their install state ("fresh install", "switching to Claude OAuth", "I want everything including SerpAPI", etc.).
- Call `orchestrator_correct(interrupt_id, response_text=<PI's free text>)` to feed the intent.

The subgraph then advances:
1. `bootstrap_propose` (background) — matches the intent against the catalog (Claude OAuth, Anthropic API key, Semantic Scholar, SerpAPI, OpenAlex polite-pool email).
2. Parks at `pi_bootstrap_ratify` — render the shortlist. The PI ratifies via TWO-TAP (per orchestrator-pi skill: present the shortlist, separate accept call). On accept the ratified ids advance; on reject/correct the workflow ends and the .env stays untouched.
3. `bootstrap_emit_template` (background) — writes `orchestrator/.env.example` next to the live `.env` with annotated slots: each var has a comment block listing purpose, criticality, sign-up URL, and format hint. Vars already set in the live `.env` are commented out (the PI uncomments to replace).
4. Parks at `pi_bootstrap_fill_ack` — surface the template path + the list of `env_var` slots the PI needs to fill. **Tell the PI**: "Open the file, copy slots into `orchestrator/.env`, save (file mode 0600), then accept this interrupt." Then call `orchestrator_accept(interrupt_id)` when the PI confirms they've done it.
5. `bootstrap_verify` (background) — reads the live `orchestrator/.env`, probes each entry's `probe.url` (never logging values), reports pass/fail per key. The terminal state is "complete" iff every `required` entry verified as `valid` or `deferred`.

After the workflow terminates, surface to the PI:
- The verify results (✓ valid / · deferred / ✗ missing/rejected / ? unreachable, one per entry).
- For any `rejected` or `missing` required entry: instruct the PI to fix and re-run `/orchestrator-bootstrap` (the .env.example is preserved on disk so they can re-resume mid-flow if they prefer).
- Mention that after a successful Phase B, the PI should restart the `rka-orchestrator` container (`docker compose -f docker-compose.yml -f orchestrator/docker-compose.yml up -d --force-recreate rka-orchestrator`) for the new credentials to be picked up by running workflows.

Privileged-gate rule: `pi_bootstrap_ratify` is set-identity (ratified_ids non-empty iff PI accepted). Use the orchestrator-pi skill's TWO-TAP discipline — show the shortlist first, then ask the PI to explicitly accept, then call `orchestrator_accept`. **Never** auto-accept based on the intent alone; the PI must see and explicitly approve the candidate list.

Security invariants enforced by the orchestrator:
- Key VALUES are never echoed back through any interrupt payload, any log line, or any verify report.
- Probe results contain only the env_var name + classification + a non-secret detail string (e.g., "HTTP 401 (endpoint reachable; key rejected)").
- The .env files are written with file mode 0600 (owner-readable only) when the OS supports it.
