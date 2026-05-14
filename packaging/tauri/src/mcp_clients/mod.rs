//! Per-client MCP-config registry.
//!
//! Seven clients (Claude Desktop, Claude Code, Cursor, VSCode-Copilot,
//! Codex CLI, Codex Mac App, Antigravity) share a single trait
//! ([`McpClient`]) but each module owns its own detection, config-path
//! resolver, and format-aware merger.
//!
//! Schema variance across the seven (from `jrn_01KRJ10CSJY14N3ZR7FFK186PX`):
//!
//! | Client | Format | Root key | `type: stdio` |
//! |--------|--------|----------|---------------|
//! | Claude Desktop | JSON | `mcpServers` | no |
//! | Claude Code | JSON | `mcpServers` | yes |
//! | Cursor | JSON | `mcpServers` | no |
//! | VSCode-Copilot | JSON | **`servers`** | yes |
//! | Codex CLI | TOML | `[mcp_servers.…]` | n/a |
//! | Codex Mac App | TOML | `[mcp_servers.…]` (shares with CLI) | n/a |
//! | Antigravity | JSON | `mcpServers` | no |
//!
//! Codex CLI + Mac App share `~/.codex/config.toml`. [`unique_write_targets`]
//! dedupes the write target so onboarding selecting both checkboxes
//! lands a single TOML write.

pub mod antigravity;
pub mod claude_code;
pub mod claude_desktop;
pub mod codex_app;
pub mod codex_cli;
pub mod cursor;
pub mod json_merger;
pub mod toml_merger;
pub mod verify;
pub mod vscode_copilot;

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::rka_runtime_dir;

const LAUNCHER_FILENAME: &str = "rka-mcp.sh";

/// Path to the stable launcher script the per-client mergers point at.
pub fn stable_launcher_path() -> PathBuf {
    rka_runtime_dir().join("bin").join(LAUNCHER_FILENAME)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProbeResult {
    pub detected: bool,
    pub evidence: Vec<String>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub enum ConfigFormat {
    Json,
    Toml,
}

#[derive(Debug, thiserror::Error)]
pub enum MergeError {
    #[error("config not parseable: {0}")]
    Unparseable(String),
    #[error("conflicting rka entry already present: {0}")]
    Conflict(String),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("serialization error: {0}")]
    Serde(String),
    #[error("verification failed after write: {0}")]
    VerifyFailed(String),
}

impl serde::Serialize for MergeError {
    fn serialize<S: serde::Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str(&self.to_string())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MergeResult {
    pub config_path: PathBuf,
    pub backup_path: Option<PathBuf>,
    pub previous_rka_command: Option<String>,
    pub new_rka_command: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RemoveResult {
    pub config_path: PathBuf,
    pub removed: bool,
    pub backup_path: Option<PathBuf>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VerifyResult {
    pub config_syntax_ok: bool,
    pub rka_entry_present: bool,
    pub backend_reachable: bool,
    pub capabilities_reachable: bool,
    pub reason: Option<String>,
}

pub trait McpClient: Send + Sync {
    fn id(&self) -> &'static str;
    fn display_name(&self) -> &'static str;
    fn config_format(&self) -> ConfigFormat;
    fn detect(&self) -> ProbeResult;
    fn config_path(&self) -> Option<PathBuf>;
    fn read_merge_write_rka(&self, launcher: &Path) -> Result<MergeResult, MergeError>;
    fn remove_rka(&self) -> Result<RemoveResult, MergeError>;
    fn verify(&self, backend_url: &str) -> VerifyResult;
}

/// Returns the seven supported clients in presentation order.
pub fn registry() -> Vec<Box<dyn McpClient>> {
    vec![
        Box::new(claude_desktop::ClaudeDesktop),
        Box::new(claude_code::ClaudeCode),
        Box::new(cursor::Cursor),
        Box::new(vscode_copilot::VscodeCopilot),
        Box::new(codex_cli::CodexCli),
        Box::new(codex_app::CodexApp),
        Box::new(antigravity::Antigravity),
    ]
}

/// Look up a client by id without consuming the registry.
pub fn find_client(id: &str) -> Option<Box<dyn McpClient>> {
    registry().into_iter().find(|c| c.id() == id)
}

/// Compress a list of clients to one entry per unique config path so
/// Codex CLI + Codex Mac App (which share `~/.codex/config.toml`) write
/// once instead of twice. Preserves the original list ordering.
pub fn unique_write_targets(ids: &[String]) -> Vec<String> {
    let mut seen_paths: Vec<PathBuf> = Vec::new();
    let mut out: Vec<String> = Vec::new();
    for id in ids {
        let Some(client) = find_client(id) else {
            continue;
        };
        let Some(path) = client.config_path() else {
            continue;
        };
        if !seen_paths.iter().any(|p| p == &path) {
            seen_paths.push(path);
            out.push(id.clone());
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registry_has_seven_clients() {
        let r = registry();
        assert_eq!(r.len(), 7, "registry must surface exactly the seven supported clients");
        let ids: Vec<&str> = r.iter().map(|c| c.id()).collect();
        assert_eq!(
            ids,
            vec![
                "claude_desktop",
                "claude_code",
                "cursor",
                "vscode_copilot",
                "codex_cli",
                "codex_app",
                "antigravity",
            ]
        );
    }

    #[test]
    fn codex_cli_and_app_share_one_write_target() {
        // Both checked → dedupes to a single write target.
        let both = vec!["codex_cli".to_string(), "codex_app".to_string()];
        let deduped = unique_write_targets(&both);
        assert_eq!(deduped.len(), 1, "Codex CLI + Mac App must dedupe");

        // Only CLI checked → CLI passes through.
        let cli_only = vec!["codex_cli".to_string()];
        assert_eq!(unique_write_targets(&cli_only), cli_only);

        // Only App checked → App passes through.
        let app_only = vec!["codex_app".to_string()];
        assert_eq!(unique_write_targets(&app_only), app_only);
    }

    #[test]
    fn unique_write_targets_preserves_other_clients() {
        let mix = vec![
            "claude_desktop".to_string(),
            "codex_cli".to_string(),
            "codex_app".to_string(),
            "cursor".to_string(),
        ];
        let deduped = unique_write_targets(&mix);
        assert_eq!(deduped.len(), 3); // codex_app drops, others stay
        assert_eq!(deduped[0], "claude_desktop");
        assert_eq!(deduped[1], "codex_cli");
        assert_eq!(deduped[2], "cursor");
    }
}
