---
description: "Show orchestrator workflow runs (status, current node, cost). Optionally filter by status (running, awaiting_pi, complete, escalated, failed, cancelled)."
---

Parse any user argument as a status filter (one of: `running`, `awaiting_pi`, `complete`, `escalated`, `failed`, `cancelled`). No argument = list everything (limit 50).

Call:
- `orchestrator_list_runs(status=<filter>?, limit=50)` for the list
- `orchestrator_health()` for daemon liveness

Render as a concise table-style summary:

```
Daemon: <ok / unreachable>

Runs (N total, M shown):
  thr_xxx [awaiting_pi]  mis_yyy  node=pi_greenlight  $0.12  parked 3m ago
  thr_zzz [complete]     mis_qqq                       $1.45  finished 1h ago
  ...
```

If the daemon is unreachable, surface a one-line hint about bringing up the orchestrator service via the Compose overlay, then stop (no list).

If the user asks for detail on a specific run after seeing the list, call `orchestrator_get_run(workflow_thread_id)` and render the full row. If they want to see what's parked on it, call `orchestrator_inbox(workflow_thread_id=...)`.

Keep the response under 20 lines unless the user asks for verbose output.
