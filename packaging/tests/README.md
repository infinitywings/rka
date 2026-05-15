# Integration test matrix — 7 clients × 9 cases + 3 cross-client cases

Mission: `mis_01KQJGR4WZXYFSDP9DN2WEXTJJ` D7 acceptance criteria.

Tests live as Rust integration tests at `packaging/tauri/tests/client_matrix.rs` and run under `cargo test`. Each test uses an isolated `$HOME` tempdir (serialized via a mutex because `dirs::home_dir` reads the env at call time and cargo runs tests in parallel by default).

## Coverage

|     | Claude Desktop | Claude Code | Cursor | VSCode-Copilot | Codex CLI | Codex Mac App | Antigravity |
|-----|----------------|-------------|--------|----------------|-----------|---------------|-------------|
| **a — fresh, no prior config** | ✓ `case_a_fresh_claude_desktop` | ✓ `case_a_fresh_claude_code` | ✓ `case_a_fresh_cursor` | ✓ `case_a_fresh_vscode_copilot` | ✓ `case_a_fresh_codex_cli` | ✓ `case_a_fresh_codex_app` | ✓ `case_a_fresh_antigravity` |
| **b — config exists, no MCP block** | ✓ `case_b_claude_desktop_no_mcp_block` | ✓ `case_b_claude_code_minimal_doc` | covered via (a) | covered via (c) | ✓ `case_b_codex_with_other_tables_only` | shared with CLI | covered via (a) |
| **c — config exists, other MCP servers** | ✓ `case_c_claude_desktop_other_servers_preserved` | covered in (i) full uninstall | covered in (i) | ✓ `case_c_vscode_servers_key_other_entries_preserved` | ✓ `case_c_codex_other_servers_preserved` | shared with CLI | covered in (l) |
| **d — existing rka entry pointing elsewhere** | ✓ `case_d_claude_desktop_conflict_when_pointing_elsewhere` | covered by json_merger unit test | covered by json_merger unit test | covered by json_merger unit test | ✓ `case_d_codex_conflict_when_pointing_elsewhere` | shared with CLI | covered by json_merger unit test |
| **e — malformed config** | ✓ `case_e_claude_desktop_malformed_json_refused` | covered by json_merger unit test | covered by json_merger unit test | covered by json_merger unit test | ✓ `case_e_codex_malformed_toml_refused` | shared with CLI | covered by json_merger unit test |
| **f — JSONC tolerance** | covered by json_merger unit test | covered by json_merger unit test | covered by json_merger unit test | ✓ `case_f_vscode_jsonc_comments_and_trailing_commas` | n/a (TOML) | n/a (TOML) | covered by json_merger unit test |
| **g — stale prior-RKA binary path** | ✓ `case_g_stale_rka_force_replace_succeeds` | shape identical | shape identical | shape identical | shape identical (TOML) | shape identical | shape identical |
| **h — Gatekeeper / antivirus** | manual QA (see below) | manual QA | manual QA | manual QA | manual QA | manual QA | manual QA |
| **i — full uninstall round-trip** | ✓ `case_i_full_uninstall_round_trips_every_client` covers all 7 in one flow |

Plus three cross-client cases:

- **j** — VSCode-Copilot writes `servers` root key (NOT `mcpServers`): ✓ `case_j_vscode_writes_servers_root_key_not_mcp_servers`
- **k** — Codex CLI + Mac App share a single write target: ✓ `case_k_codex_cli_and_app_dedupe_to_single_write`
- **l** — Antigravity uses `mcpServers` (NOT VSCode's `servers` despite being a fork), and preserves `disabled` / `disabledTools` fields on unrelated servers: ✓ `case_l_antigravity_writes_mcp_servers_not_servers` + `case_l_antigravity_preserves_disabled_and_disabledTools_on_other_servers`

Plus an audit-symmetry pair (`jrn_01KR4GVDXYRVTT6RXTX7BP3JW6`):

- ✓ `audit_symmetry_remove_after_merge_for_every_json_client` — every client's `read_merge_write_rka` is paired with a `remove_rka` round-trip.

The merger-helper unit tests under `src/mcp_clients/{json_merger,toml_merger,verify}.rs` cover the format-aware mechanics in isolation (15 of the original tests from D3). The matrix above adds end-to-end coverage exercising each per-client `McpClient` trait through its real path / detection / merger combination.

## Running the suite

From `packaging/tauri/`:

```bash
# Library-internal unit tests (json_merger + toml_merger + diag + log_writer + registry)
cargo test --lib

# End-to-end matrix in this directory
cargo test --test client_matrix
```

If your repo lives on a volume without full xattr support (external drives, SMB/AFP mounts, sync folders), set `CARGO_TARGET_DIR="$HOME/.cache/rka-tauri-target"` first to keep AppleDouble companion files out of Tauri's permissions scan (see top-level CLAUDE.md).

## Manual QA — case (h) Gatekeeper / antivirus flagging

PyInstaller binaries are not byte-signed beyond the Tauri shell's ad-hoc
signature on their containing `.app`. Phase 1 distribution surfaces:

1. **First launch warning** — `"rka-serve" cannot be opened because Apple cannot
   check it for malicious software.` This is expected for ad-hoc signatures.
   Right-click → Open dismisses the warning once; subsequent launches work.
2. **Antivirus heuristic flags** — third-party AV (e.g., older Sophos, ESET
   versions) may flag PyInstaller's bootloader as suspicious. The flag is
   a known false positive against PyInstaller-generated binaries; documented
   in the PyInstaller FAQ. Phase 2 Developer ID signing + notarization
   reduces (does not eliminate) these flags by giving the binary a trust chain.

The acceptance behavior for Phase 1 is "right-click → Open works on a fresh
Mac with no AV." Documented in `packaging/README.md` end-user install
instructions and verified manually on the developer's test Mac before each
release cut.
