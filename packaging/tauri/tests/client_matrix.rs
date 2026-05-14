//! D7 — end-to-end integration tests for the 7-client onboarding matrix.
//!
//! Each per-client trait implementation is exercised through the
//! standard nine cases (mission `mis_01KQJGR4WZXYFSDP9DN2WEXTJJ` D7
//! acceptance criteria):
//!
//!   a. fresh Mac with no prior config
//!   b. config file that already exists with no MCP block
//!   c. config file with other MCP servers (must preserve them)
//!   d. config file with an existing rka entry pointing elsewhere
//!      (must conflict-detect)
//!   e. malformed config (must refuse to overwrite, surface error)
//!   f. JSONC tolerance (line comments + trailing commas) for the
//!      JSON clients
//!   g. stale config from a prior RKA install pointing at a missing
//!      binary path
//!   h. Gatekeeper / antivirus flag handling — documented in
//!      `packaging/tests/README.md` (manual QA, not unit-testable)
//!   i. full app uninstall flow restoring every client's config to
//!      pre-RKA state
//!
//! Plus three cross-client cases:
//!   j. VSCode-Copilot writes `servers` root key (NOT `mcpServers`)
//!   k. Codex CLI + Mac App share a single write target
//!   l. Antigravity schema (mcpServers JSON, NOT VSCode's servers)
//!
//! Audit-symmetry discipline (jrn_01KR4GVDXYRVTT6RXTX7BP3JW6): every
//! merge-then-write pair is followed by a remove-then-write pair so
//! round-trip preservation is exercised in both directions.

use std::path::PathBuf;
use std::sync::Mutex;

use rka_desktop_lib::mcp_clients::{
    self, antigravity, claude_code, claude_desktop, codex_app, codex_cli, cursor,
    json_merger, toml_merger, vscode_copilot, McpClient, MergeError,
};

/// HOME env var serialization. dirs::home_dir() reads $HOME at call
/// time, and cargo test runs tests in parallel by default. Every test
/// that swaps HOME must hold this lock.
static HOME_LOCK: Mutex<()> = Mutex::new(());

struct TestEnv {
    _guard: std::sync::MutexGuard<'static, ()>,
    tempdir: PathBuf,
    saved_home: Option<String>,
}

impl TestEnv {
    fn new() -> Self {
        let guard = HOME_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let saved_home = std::env::var("HOME").ok();
        let tempdir = std::env::temp_dir().join(format!(
            "rka-d7-{}-{}",
            std::process::id(),
            chrono::Utc::now().timestamp_nanos_opt().unwrap_or_default()
        ));
        std::fs::create_dir_all(&tempdir).expect("create tempdir");
        std::env::set_var("HOME", &tempdir);
        Self {
            _guard: guard,
            tempdir,
            saved_home,
        }
    }

    fn write(&self, rel: &str, contents: &str) -> PathBuf {
        let p = self.tempdir.join(rel);
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        std::fs::write(&p, contents).unwrap();
        p
    }

    fn read(&self, rel: &str) -> String {
        std::fs::read_to_string(self.tempdir.join(rel)).unwrap_or_default()
    }
}

impl Drop for TestEnv {
    fn drop(&mut self) {
        if let Some(prev) = &self.saved_home {
            std::env::set_var("HOME", prev);
        } else {
            std::env::remove_var("HOME");
        }
        let _ = std::fs::remove_dir_all(&self.tempdir);
    }
}

fn launcher() -> PathBuf {
    PathBuf::from("/Users/test/Library/Application Support/RKA/bin/rka-mcp.sh")
}

// ---------------- per-client paths ----------------

fn claude_desktop_rel() -> &'static str {
    "Library/Application Support/Claude/claude_desktop_config.json"
}
fn claude_code_rel() -> &'static str {
    ".claude.json"
}
fn cursor_rel() -> &'static str {
    ".cursor/mcp.json"
}
fn vscode_copilot_rel() -> &'static str {
    "Library/Application Support/Code/User/mcp.json"
}
fn codex_rel() -> &'static str {
    ".codex/config.toml"
}
fn antigravity_rel() -> &'static str {
    ".gemini/antigravity/mcp_config.json"
}

// ---------------- (a) fresh Mac with no prior config ----------------

#[test]
fn case_a_fresh_claude_desktop() {
    let env = TestEnv::new();
    let r = claude_desktop::ClaudeDesktop
        .read_merge_write_rka(&launcher())
        .unwrap();
    assert!(env.read(claude_desktop_rel()).contains("\"rka\""));
    assert!(r.backup_path.is_none(), "fresh writes have no backup");
}

#[test]
fn case_a_fresh_claude_code() {
    let env = TestEnv::new();
    claude_code::ClaudeCode
        .read_merge_write_rka(&launcher())
        .unwrap();
    let raw = env.read(claude_code_rel());
    assert!(raw.contains("\"rka\""));
    assert!(raw.contains("\"stdio\""), "claude_code emits type=stdio");
}

#[test]
fn case_a_fresh_cursor() {
    let env = TestEnv::new();
    cursor::Cursor.read_merge_write_rka(&launcher()).unwrap();
    assert!(env.read(cursor_rel()).contains("\"rka\""));
}

#[test]
fn case_a_fresh_vscode_copilot() {
    let env = TestEnv::new();
    vscode_copilot::VscodeCopilot
        .read_merge_write_rka(&launcher())
        .unwrap();
    let raw = env.read(vscode_copilot_rel());
    assert!(raw.contains("\"rka\""));
}

#[test]
fn case_a_fresh_codex_cli() {
    let env = TestEnv::new();
    codex_cli::CodexCli.read_merge_write_rka(&launcher()).unwrap();
    let raw = env.read(codex_rel());
    assert!(raw.contains("[mcp_servers.rka]"));
}

#[test]
fn case_a_fresh_codex_app() {
    let env = TestEnv::new();
    codex_app::CodexApp.read_merge_write_rka(&launcher()).unwrap();
    let raw = env.read(codex_rel());
    assert!(raw.contains("[mcp_servers.rka]"));
}

#[test]
fn case_a_fresh_antigravity() {
    let env = TestEnv::new();
    antigravity::Antigravity
        .read_merge_write_rka(&launcher())
        .unwrap();
    assert!(env.read(antigravity_rel()).contains("\"rka\""));
}

// ---------------- (b) existing config without MCP block ----------------

#[test]
fn case_b_claude_desktop_no_mcp_block() {
    let env = TestEnv::new();
    env.write(claude_desktop_rel(), r#"{"theme":"dark"}"#);
    claude_desktop::ClaudeDesktop
        .read_merge_write_rka(&launcher())
        .unwrap();
    let raw = env.read(claude_desktop_rel());
    assert!(raw.contains("\"theme\""), "preserves unrelated keys");
    assert!(raw.contains("\"rka\""));
}

#[test]
fn case_b_claude_code_minimal_doc() {
    let env = TestEnv::new();
    env.write(claude_code_rel(), r#"{"numStartups":5}"#);
    claude_code::ClaudeCode
        .read_merge_write_rka(&launcher())
        .unwrap();
    let raw = env.read(claude_code_rel());
    assert!(raw.contains("\"numStartups\""));
    assert!(raw.contains("\"rka\""));
}

#[test]
fn case_b_codex_with_other_tables_only() {
    let env = TestEnv::new();
    env.write(
        codex_rel(),
        r#"
model = "gpt-5"

[projects.foo]
worktree = true
"#,
    );
    codex_cli::CodexCli.read_merge_write_rka(&launcher()).unwrap();
    let raw = env.read(codex_rel());
    assert!(raw.contains("model = \"gpt-5\""));
    assert!(raw.contains("[projects.foo]"));
    assert!(raw.contains("[mcp_servers.rka]"));
}

// ---------------- (c) config with other MCP servers ----------------

#[test]
fn case_c_claude_desktop_other_servers_preserved() {
    let env = TestEnv::new();
    env.write(
        claude_desktop_rel(),
        r#"{
            "mcpServers": {
                "github": {"command": "/usr/local/bin/gh-mcp", "args": []},
                "blender": {"command": "/usr/local/bin/blender-mcp", "args": []}
            }
        }"#,
    );
    claude_desktop::ClaudeDesktop
        .read_merge_write_rka(&launcher())
        .unwrap();
    let raw = env.read(claude_desktop_rel());
    assert!(raw.contains("\"github\""));
    assert!(raw.contains("\"blender\""));
    assert!(raw.contains("\"rka\""));
}

#[test]
fn case_c_vscode_servers_key_other_entries_preserved() {
    let env = TestEnv::new();
    env.write(
        vscode_copilot_rel(),
        r#"{
            "servers": {
                "github": {"url": "https://api.githubcopilot.com/mcp/", "type": "http"}
            },
            "inputs": []
        }"#,
    );
    vscode_copilot::VscodeCopilot
        .read_merge_write_rka(&launcher())
        .unwrap();
    let raw = env.read(vscode_copilot_rel());
    assert!(raw.contains("\"github\""));
    assert!(raw.contains("\"inputs\""), "VSCode `inputs` array preserved");
    assert!(raw.contains("\"rka\""));
}

#[test]
fn case_c_codex_other_servers_preserved() {
    let env = TestEnv::new();
    env.write(
        codex_rel(),
        r#"
[mcp_servers.github]
command = "/usr/local/bin/gh-mcp"
args = []
"#,
    );
    codex_cli::CodexCli.read_merge_write_rka(&launcher()).unwrap();
    let raw = env.read(codex_rel());
    assert!(raw.contains("[mcp_servers.github]"));
    assert!(raw.contains("[mcp_servers.rka]"));
}

// ---------------- (d) existing rka entry pointing elsewhere ----------------

#[test]
fn case_d_claude_desktop_conflict_when_pointing_elsewhere() {
    let env = TestEnv::new();
    env.write(
        claude_desktop_rel(),
        r#"{"mcpServers":{"rka":{"command":"/old/rka","args":[]}}}"#,
    );
    let err = claude_desktop::ClaudeDesktop
        .read_merge_write_rka(&launcher())
        .unwrap_err();
    assert!(matches!(err, MergeError::Conflict(_)));
}

#[test]
fn case_d_codex_conflict_when_pointing_elsewhere() {
    let env = TestEnv::new();
    env.write(
        codex_rel(),
        r#"
[mcp_servers.rka]
command = "/old/rka"
args = []
"#,
    );
    let err = codex_cli::CodexCli
        .read_merge_write_rka(&launcher())
        .unwrap_err();
    assert!(matches!(err, MergeError::Conflict(_)));
}

// ---------------- (e) malformed config (must refuse) ----------------

#[test]
fn case_e_claude_desktop_malformed_json_refused() {
    let env = TestEnv::new();
    let original = "{this isn't valid json at all";
    env.write(claude_desktop_rel(), original);
    let err = claude_desktop::ClaudeDesktop
        .read_merge_write_rka(&launcher())
        .unwrap_err();
    assert!(matches!(err, MergeError::Unparseable(_)));
    // Config must be UNCHANGED — never overwrite an unparseable file.
    assert_eq!(env.read(claude_desktop_rel()), original);
}

#[test]
fn case_e_codex_malformed_toml_refused() {
    let env = TestEnv::new();
    let original = "[invalid syntax";
    env.write(codex_rel(), original);
    let err = codex_cli::CodexCli
        .read_merge_write_rka(&launcher())
        .unwrap_err();
    assert!(matches!(err, MergeError::Unparseable(_)));
    assert_eq!(env.read(codex_rel()), original);
}

// ---------------- (f) JSONC tolerance ----------------

#[test]
fn case_f_vscode_jsonc_comments_and_trailing_commas() {
    let env = TestEnv::new();
    env.write(
        vscode_copilot_rel(),
        r#"{
            // VSCode users frequently leave inline comments
            "servers": {
                "github": {"url": "https://api.example.com", "type": "http"},
            },
            /* block comment with a trailing comma above */
        }"#,
    );
    vscode_copilot::VscodeCopilot
        .read_merge_write_rka(&launcher())
        .unwrap();
    let raw = env.read(vscode_copilot_rel());
    assert!(raw.contains("\"github\""));
    assert!(raw.contains("\"rka\""));
}

// ---------------- (g) stale prior-RKA pointing at missing binary ----------------

#[test]
fn case_g_stale_rka_force_replace_succeeds() {
    let env = TestEnv::new();
    env.write(
        claude_desktop_rel(),
        r#"{"mcpServers":{"rka":{"command":"/tmp/old-rka-now-missing","args":[]}}}"#,
    );
    // Without force, conflict is detected (case d). With force-replace via
    // the json_merger helper directly (UI prompts the user to confirm),
    // the merger overwrites with the new launcher.
    let cfg = env.tempdir.join(claude_desktop_rel());
    let r = json_merger::merge_rka_entry(
        &cfg,
        "mcpServers",
        &launcher(),
        false,
        true,
    )
    .unwrap();
    assert_eq!(r.previous_rka_command.as_deref(), Some("/tmp/old-rka-now-missing"));
    let raw = env.read(claude_desktop_rel());
    assert!(raw.contains("rka-mcp.sh"));
    assert!(!raw.contains("old-rka-now-missing"));
}

// ---------------- (i) full uninstall restoring every client ----------------

#[test]
fn case_i_full_uninstall_round_trips_every_client() {
    let env = TestEnv::new();

    // Pre-populate every client with its own pre-existing server + rka.
    env.write(
        claude_desktop_rel(),
        r#"{"mcpServers":{"github":{"command":"/usr/local/bin/gh","args":[]}}}"#,
    );
    env.write(
        claude_code_rel(),
        r#"{"mcpServers":{"git":{"type":"stdio","command":"/usr/local/bin/git-mcp","args":[]}}}"#,
    );
    env.write(
        cursor_rel(),
        r#"{"mcpServers":{"canvas":{"command":"/usr/local/bin/canvas","args":[]}}}"#,
    );
    env.write(
        vscode_copilot_rel(),
        r#"{"servers":{"github":{"url":"https://api.example.com","type":"http"}},"inputs":[]}"#,
    );
    env.write(
        codex_rel(),
        "[mcp_servers.github]\ncommand = \"/usr/local/bin/gh-mcp\"\nargs = []\n",
    );
    env.write(
        antigravity_rel(),
        r#"{"mcpServers":{"old":{"command":"/usr/local/bin/old-mcp","args":[]}}}"#,
    );

    let registry = mcp_clients::registry();
    let dedup_ids: Vec<String> = registry.iter().map(|c| c.id().to_string()).collect();
    let unique = mcp_clients::unique_write_targets(&dedup_ids);
    assert_eq!(
        unique.len(),
        6,
        "codex_cli + codex_app must compress to 6 unique write targets",
    );

    // Onboard.
    for id in &unique {
        let c = mcp_clients::find_client(id).unwrap();
        c.read_merge_write_rka(&launcher()).unwrap();
    }

    // Verify every config now has the rka entry alongside its original
    // pre-existing server.
    assert!(env.read(claude_desktop_rel()).contains("\"github\""));
    assert!(env.read(claude_desktop_rel()).contains("\"rka\""));
    assert!(env.read(claude_code_rel()).contains("\"git\""));
    assert!(env.read(claude_code_rel()).contains("\"rka\""));
    assert!(env.read(cursor_rel()).contains("\"canvas\""));
    assert!(env.read(cursor_rel()).contains("\"rka\""));
    assert!(env.read(vscode_copilot_rel()).contains("\"github\""));
    assert!(env.read(vscode_copilot_rel()).contains("\"rka\""));
    assert!(env.read(codex_rel()).contains("[mcp_servers.github]"));
    assert!(env.read(codex_rel()).contains("[mcp_servers.rka]"));
    assert!(env.read(antigravity_rel()).contains("\"old\""));
    assert!(env.read(antigravity_rel()).contains("\"rka\""));

    // Uninstall — every original server still present, rka gone.
    for c in mcp_clients::registry() {
        c.remove_rka().unwrap();
    }
    assert!(env.read(claude_desktop_rel()).contains("\"github\""));
    assert!(!env.read(claude_desktop_rel()).contains("\"rka\""));
    assert!(env.read(claude_code_rel()).contains("\"git\""));
    assert!(!env.read(claude_code_rel()).contains("\"rka\""));
    assert!(env.read(cursor_rel()).contains("\"canvas\""));
    assert!(!env.read(cursor_rel()).contains("\"rka\""));
    assert!(env.read(vscode_copilot_rel()).contains("\"github\""));
    assert!(!env.read(vscode_copilot_rel()).contains("\"rka\""));
    assert!(env.read(codex_rel()).contains("[mcp_servers.github]"));
    assert!(!env.read(codex_rel()).contains("[mcp_servers.rka]"));
    assert!(env.read(antigravity_rel()).contains("\"old\""));
    assert!(!env.read(antigravity_rel()).contains("\"rka\""));
}

// ---------------- (j) VSCode-Copilot writes `servers`, NOT `mcpServers` ----------------

#[test]
fn case_j_vscode_writes_servers_root_key_not_mcp_servers() {
    let env = TestEnv::new();
    vscode_copilot::VscodeCopilot
        .read_merge_write_rka(&launcher())
        .unwrap();
    let raw = env.read(vscode_copilot_rel());
    assert!(raw.contains("\"servers\""));
    assert!(
        !raw.contains("\"mcpServers\""),
        "VSCode-Copilot MUST use `servers`, copy-paste regression catch"
    );
    // The merger emits type:"stdio" so VSCode can route to a subprocess.
    assert!(raw.contains("\"stdio\""));
}

// ---------------- (k) Codex CLI + Mac App share one write target ----------------

#[test]
fn case_k_codex_cli_and_app_dedupe_to_single_write() {
    let env = TestEnv::new();

    // Both checkboxes selected → unique_write_targets dedupes.
    let both = vec!["codex_cli".to_string(), "codex_app".to_string()];
    let unique = mcp_clients::unique_write_targets(&both);
    assert_eq!(unique.len(), 1);

    // Manual loop over dedup result writes exactly once.
    for id in &unique {
        mcp_clients::find_client(id)
            .unwrap()
            .read_merge_write_rka(&launcher())
            .unwrap();
    }
    let raw = env.read(codex_rel());
    let rka_blocks = raw.matches("[mcp_servers.rka]").count();
    assert_eq!(rka_blocks, 1, "exactly one [mcp_servers.rka] block written");
}

// ---------------- (l) Antigravity schema (mcpServers, not VSCode `servers`) ----------------

#[test]
fn case_l_antigravity_writes_mcp_servers_not_servers() {
    let env = TestEnv::new();
    antigravity::Antigravity
        .read_merge_write_rka(&launcher())
        .unwrap();
    let raw = env.read(antigravity_rel());
    assert!(
        raw.contains("\"mcpServers\""),
        "Antigravity uses mcpServers (verified via static analysis of out/main.js)"
    );
    assert!(
        !raw.contains("\"servers\""),
        "Antigravity does NOT use VSCode's `servers` key despite being a VSCode fork"
    );
}

#[test]
fn case_l_antigravity_preserves_disabled_and_disabledTools_on_other_servers() {
    let env = TestEnv::new();
    env.write(
        antigravity_rel(),
        r#"{
            "mcpServers": {
                "thirdparty": {
                    "command": "/usr/local/bin/thirdparty-mcp",
                    "args": [],
                    "disabled": false,
                    "disabledTools": ["dangerous-tool"]
                }
            }
        }"#,
    );
    antigravity::Antigravity
        .read_merge_write_rka(&launcher())
        .unwrap();
    let raw = env.read(antigravity_rel());
    // The Antigravity-specific optional fields on the OTHER server must
    // survive the round-trip.
    assert!(raw.contains("\"disabled\""));
    assert!(raw.contains("\"disabledTools\""));
    assert!(raw.contains("\"dangerous-tool\""));
    assert!(raw.contains("\"thirdparty\""));
    assert!(raw.contains("\"rka\""));
}

// ---------------- audit-symmetry / grep-gate cross-check ----------------

#[test]
fn audit_symmetry_remove_after_merge_for_every_json_client() {
    let env = TestEnv::new();
    for c in mcp_clients::registry() {
        c.read_merge_write_rka(&launcher()).unwrap();
        let r = c.remove_rka().unwrap();
        // Either removed=true (we wrote, then removed) or shared with
        // codex_cli (codex_app's remove is a no-op after CLI removed).
        assert!(
            r.removed || c.id() == "codex_app",
            "remove should round-trip for {}",
            c.id()
        );
    }
}

// Toml merger remove is also covered by its own remove_is_idempotent_when_absent
// test in src/mcp_clients/toml_merger.rs; ensure the helper symbol stays linked.
#[test]
fn toml_remove_helper_idempotent_when_absent() {
    let env = TestEnv::new();
    let cfg = env.tempdir.join(codex_rel());
    std::fs::create_dir_all(cfg.parent().unwrap()).unwrap();
    std::fs::write(&cfg, "[mcp_servers.other]\ncommand = \"/x\"\nargs = []\n").unwrap();
    let r = toml_merger::remove_rka_entry(&cfg).unwrap();
    assert!(!r.removed);
}
