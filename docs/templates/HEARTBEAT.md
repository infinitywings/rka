# HEARTBEAT — RKA Event Polling

This file configures cron-based event polling for an OpenClaw agent.
Place it in each agent's workspace directory alongside SOUL.md.

## Polling Schedule

Every 30 seconds:

1. Call `rka_get_events(role_id="ROLE_ID", status="pending")` to check for new events
2. If events exist:
   a. For each event, follow the processing protocol defined in SOUL.md
   b. Call `rka_ack_event(event_id)` after processing each event
   c. Call `rka_save_role_state(role_id="ROLE_ID", role_state={...})` if state changed
3. If no events, terminate quietly (no-op cycle)

## Configuration

Replace `ROLE_ID` with the actual role ID from `rka_register_role`.

## Notes

- Events left unacknowledged for 72 hours are automatically expired by RKA.
- If an event fails mid-processing, it remains in `pending` (or `processing`)
  status and will be retried on the next poll cycle.
- Priority ordering: higher-priority events are returned first, then FIFO by
  creation time.
- The polling interval (30s) is a starting point. Adjust based on workload —
  longer intervals reduce API calls but increase latency for event processing.
- The exact cron syntax depends on OpenClaw's HEARTBEAT implementation.
  Verify against OpenClaw documentation.
