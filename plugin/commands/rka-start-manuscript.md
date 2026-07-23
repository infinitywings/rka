---
description: "Register or verify an RKA manuscript and atomically create a complete Writer workspace."
argument-hint: "--project-id <prj_...> --venue <id> --title <title> [--path <dir>]"
---

Run the plugin compatibility wrapper, forwarding the user's flags exactly:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/start-manuscript.py \
  --project-id <prj_...> --venue <venue-id> --title <PI-authored-title> \
  [--path <workspace>] [--manuscript-id <man_...>] [--cfp-url <url>] \
  [--api-url <local-rka-url>]
```

The wrapper delegates to `rka writer init`. The command requires an explicit
project, registers a new canonical `man_` manuscript (or verifies
`--manuscript-id`; legacy `jrn_` aliases remain accepted for compatibility),
renders every template token in a sibling staging directory, verifies that no
core sentinel remains, writes `.rka/manuscript.json`, and atomically publishes
the target. It refuses a non-empty target and never stores API keys or a
default-project environment variable in the workspace.

Report the JSON result. If registration succeeds but publication fails, retain
the returned manuscript ID and rerun with `--manuscript-id` so the operation is
recoverable without registering a duplicate. Do not use the removed `--force`
or `RKA_PROJECT` mechanisms.
