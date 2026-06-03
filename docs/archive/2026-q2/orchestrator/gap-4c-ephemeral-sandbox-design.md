# Gap 4c — Ephemeral sandbox container for SDK subprocess

**Status:** design-only; implementation deferred to a focused Phase G3 session.

**Author rationale:** Gap 4a (bashlex AST classifier) and Gap 4b (bash allowlist
mode) close most of the threat model an honest LLM presents. Gap 4c addresses
the *adversarial* LLM case — where the LLM is actively trying to escape the
classifier, the sandbox boundary is the real defense. This document captures
the design so it can ship without re-deriving the architecture.

## Threat model

Pre-Gap-4c, the SDK subprocess runs:
- Inside the orchestrator daemon container
- As the `orchestrator` user (post-Gap-5 hardening)
- With access to: workspace bind mount (rw), `~/.claude.json` (ro),
  `/data` (rw), `/home/orchestrator` (rw), `/tmp` (rw)

What an escape looks like:
- Bash classifier bypass (variable indirection, dynamic environment,
  Python `subprocess.run()`, base64-encoded payloads)
- The SDK subprocess writes to `/home/orchestrator/.claude/` and persists
  state across calls — an attacker could plant artifacts that influence
  future calls
- The bind-mounted workspace is shared across projects (until per-project
  workspace_path wires fully through, but even then the daemon's view of
  HOST_WORKSPACE_ROOT is the union)

What we want:
- Each SDK call runs in its own container, destroyed afterward
- Filesystem view: the workspace mount + the OAuth token (RO) only — no
  `/data`, no daemon code, no other projects' workspaces
- Network: deny all by default; egress allowlist for `claude.ai/api` only
- Privileges: drop everything (`--cap-drop=ALL`, `--user nobody`,
  seccomp profile blocks `mount`/`setuid`/`ptrace`/`kexec`/`reboot`)
- The container is gone when the call ends — no persistent attacker
  artifacts

## Architecture

```
Host                 Daemon container          Per-call sandbox container
┌──────────────┐    ┌────────────────────┐    ┌──────────────────────────┐
│ Workspace    │ ─→ │ orchestrator user  │ ─→ │ nobody user (UID 65534)  │
│  /Users/x/   │    │  • FastAPI         │    │  • SDK CLI binary        │
│  Research/   │    │  • LangGraph       │    │  • workspace mount (rw)  │
│              │    │  • runs SDK via    │    │  • oauth token (ro tmpfs)│
│ ~/.claude    │    │    `docker run`    │    │  • --cap-drop=ALL        │
│  .json       │    │    instead of      │    │  • --network=none        │
│              │    │    subprocess.run  │    │    + egress proxy        │
└──────────────┘    └────────────────────┘    │  • seccomp deny syscalls │
                                              │  • destroyed at exit     │
                                              └──────────────────────────┘
```

The orchestrator daemon delegates the SDK call to a child container instead
of spawning `subprocess.run("claude")` directly. We need:

1. **A sandbox image** — `rka-orchestrator-sdk-sandbox:latest`, built once,
   containing only the Claude CLI + minimal Python runtime. ~150 MB.

2. **A spawn helper** in `orchestrator/orchestrator/sdk_sandbox.py` that
   replaces `subprocess.run` with `docker run --rm` (or `podman run --rm`)
   with the right flags.

3. **Communication** — the SDK is a streaming JSON-line protocol over
   stdin/stdout. The daemon pipes prompts in via stdin and reads results
   from stdout, same as today; the container is just a sandbox wrapper.

4. **Workspace mount** — same identical-path bind mount as today, scoped
   to the per-call project workspace_path (Gap 1 already threads this).

5. **OAuth token** — passed as a tmpfs mount or env var. tmpfs is preferable
   (process exit destroys it).

## docker run command

```bash
docker run --rm \
    --user 65534:65534 \
    --read-only \
    --cap-drop=ALL \
    --security-opt no-new-privileges \
    --security-opt seccomp=/path/to/seccomp-profile.json \
    --network=egress-proxy \
    --tmpfs /tmp:rw,size=64m,mode=1777 \
    --tmpfs /home/sdk:rw,size=8m,mode=0700,uid=65534 \
    -v ${WORKSPACE_PATH}:${WORKSPACE_PATH}:rw \
    -v ${OAUTH_TOKEN_FILE}:/run/secrets/oauth:ro \
    -e CLAUDE_CODE_OAUTH_TOKEN_FILE=/run/secrets/oauth \
    -e HOME=/home/sdk \
    --memory=2g \
    --cpus=2 \
    --pids-limit=200 \
    rka-orchestrator-sdk-sandbox:latest \
    claude --print --output-format=json
```

Key flags:
- `--user 65534:65534`: nobody:nogroup
- `--read-only`: rootfs is immutable; tmpfs provides scratch in `/tmp` + `/home/sdk`
- `--cap-drop=ALL`: no Linux capabilities
- `--security-opt no-new-privileges`: setuid binaries don't work
- `--security-opt seccomp=…`: custom profile (see below)
- `--network=egress-proxy`: separate Docker network with a proxy container
  that allowlists `*.anthropic.com`, denies the rest
- `--memory=2g --cpus=2 --pids-limit=200`: resource caps prevent
  fork-bomb / memory-bomb escapes
- `--tmpfs` for `/tmp` and `/home/sdk` (writable scratch, destroyed at exit)

## Seccomp profile

Built off Docker's default seccomp profile with extra denies:
```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "syscalls": [
    {
      "names": ["mount", "umount", "umount2", "pivot_root",
                "chroot", "setuid", "setgid", "setresuid", "setresgid",
                "ptrace", "kexec_load", "init_module", "delete_module",
                "reboot", "create_module", "settimeofday", "clock_settime",
                "unshare", "setns", "swapon", "swapoff",
                "mlock", "mlock2", "munlock"],
      "action": "SCMP_ACT_ERRNO"
    }
  ]
}
```

Plus the standard allowlist for normal Python + I/O syscalls.

## Egress proxy

A small Squid or Envoy container on a private Docker network:
- Allowlist hosts: `api.anthropic.com`, `claude.ai`
- Deny all other CONNECT requests
- Log every outbound request to a daemon-readable log

The sandbox container's `--network=egress-proxy` connects only to this
proxy. No direct external connectivity.

## Performance

Expected overhead per SDK call:
- Docker: ~500ms container startup + ~100ms teardown = ~600ms overhead
- Podman: ~150ms startup + ~50ms teardown = ~200ms overhead
- Comparison: a Brain LLM call takes 30s-3min today; sandbox overhead
  is in the noise

For tight loops (Phase O hygiene_pass that fires N SDK calls in series),
the overhead adds up to 5-10 seconds per N=10 calls. Acceptable.

## What we lose

- **Shell state across calls.** The SDK subprocess's own
  `~/.claude/shell-snapshots/` history is destroyed each call. Today the
  SDK reuses this for performance; we'd give that up.
- **Build cache.** Any binary the SDK fetches lives only for the call's
  duration. For mission work that runs `pip install`, the install cost
  repeats per call (though `pip` is in the allowlist so the install
  itself works).
- **Streaming output.** Today the SDK streams tokens to the daemon. With
  Docker, streaming still works via stdout — Docker doesn't buffer
  by default — but there's a one-shot connection setup latency.

## Open design questions

1. **Docker-in-Docker vs. host Docker socket.** Mounting `/var/run/docker.sock`
   into the daemon container is the easier path but means daemon-compromise
   → host-Docker-control. The cleaner path is rootless podman or a
   sibling Docker daemon — heavier to set up. Decide based on operator
   trust model.

2. **Per-project sandbox images?** Most missions only need a subset of
   tools (Python+pip is the universal need). We could pre-build
   per-project images with the registered tool set baked in. Trade-off:
   image-build time at project onboarding vs. cold-start time at call
   time. Default = single shared image for now.

3. **Sandbox the orchestrator daemon too?** Today the daemon runs in a
   regular Docker container; the FastAPI + LangGraph code itself isn't
   sandboxed. Compromising the daemon code is a higher-skill attack but
   not impossible. Adding seccomp + read-only rootfs to the daemon
   container itself is a cheap defense — propose folding into Gap 5 v2.

## Effort estimate

- Sandbox image build: 2 hours
- `sdk_sandbox.py` helper + integration: 4 hours
- Seccomp profile authoring + testing: 4 hours
- Egress proxy setup: 3 hours
- End-to-end testing across mission types: 4 hours
- Documentation + operator runbook: 2 hours

Total: ~20 hours = 2.5 focused workdays.

## Acceptance criteria

When Gap 4c lands:
- [ ] An adversarial LLM that tries `python -c "import shutil; shutil.rmtree('/')"`
      inside its Bash invocation cannot delete the daemon's `/data` directory
- [ ] An adversarial LLM cannot write to `/etc`, `/usr`, or the daemon's code paths
- [ ] An adversarial LLM cannot make a network connection to a non-Anthropic host
- [ ] An adversarial LLM cannot persist artifacts (no shell snapshots, no
      caches, no logs) that influence future SDK calls — full ephemeral
- [ ] Performance regression on mission workflows < 10% over the
      no-sandbox baseline
- [ ] All existing 976+ tests still pass (sandbox mode opt-in via env var
      so the test suite can keep using subprocess.run for speed)
- [ ] An operator runbook describes how to verify the sandbox is actually
      active (look at `docker ps` during an SDK call; expect a transient
      `rka-orchestrator-sdk-sandbox` container)

## What this does NOT solve

- **Bugs in the seccomp profile or Docker itself.** A 0-day in the kernel
  seccomp implementation, or in Docker's container isolation, would
  bypass the sandbox. Defense in depth is required: sandbox + AST
  classifier + allowlist + workspace mount scope all stay.
- **Logic bugs in our own dispatch code.** If `execute_ratified_fs_actions`
  has a TOCTOU race or a path-traversal bug, the sandbox doesn't help.
- **Social engineering of the PI.** The PI ratifying a destructive action
  via `pi_decision_select` accept is still a path; double-classify at
  dispatch (already shipped in Gap 2) is the only guard there.

The sandbox is the floor of the security stack, not the ceiling. The
LLM-level prompt discipline, hook-level classifier, and PI ratification
remain the load-bearing protections; the sandbox just bounds the blast
radius when those upstream layers fail.
