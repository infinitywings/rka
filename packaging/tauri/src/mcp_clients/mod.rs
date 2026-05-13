//! Per-client MCP-config registry.
//!
//! Each supported client (Claude Desktop, Claude Code, Cursor,
//! VSCode-Copilot, Codex CLI, Codex Mac App, Antigravity) has a module
//! that implements the [`McpClient`] trait. D3 fleshes out the
//! per-client modules. This module declares the shared trait + the
//! result types only.
//!
//! See `packaging/tauri/src/mcp_clients/README.md` for the registry
//! pattern and the per-client config-format quirks (VSCode-Copilot's
//! `servers`-not-`mcpServers`, Codex CLI+App shared config, Antigravity
//! schema verification gate).

use std::path::PathBuf;

use serde::{Deserialize, Serialize};

/// Result of probing the filesystem to see whether a client is installed.
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
    #[error("conflicting rka entry already present pointing elsewhere: {0}")]
    Conflict(String),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("serialization error: {0}")]
    Serde(String),
    #[error("verification failed after write: {0}")]
    VerifyFailed(String),
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

/// Shared interface every per-client module implements.
pub trait McpClient: Send + Sync {
    fn id(&self) -> &'static str;
    fn display_name(&self) -> &'static str;
    fn config_format(&self) -> ConfigFormat;

    /// Filesystem probe to determine whether the client is installed.
    fn detect(&self) -> ProbeResult;

    /// Where the merged config lives. Returns `None` if the client is
    /// detected only through its presence as an app bundle but RKA does
    /// not yet know the actual user-scope config path (e.g. VSCode build
    /// variance).
    fn config_path(&self) -> Option<PathBuf>;

    /// Merge an `rka` entry into the user's existing config, atomically
    /// and with backup. Implementations MUST refuse to overwrite a
    /// config that cannot be parsed, and MUST surface a conflict when an
    /// existing `rka` entry points elsewhere.
    fn read_merge_write_rka(&self, launcher: &std::path::Path) -> Result<MergeResult, MergeError>;

    /// Remove the RKA entry while preserving every other server.
    fn remove_rka(&self) -> Result<RemoveResult, MergeError>;

    /// Two-stage verification: config-syntax + backend reachability.
    fn verify(&self, backend_url: &str) -> VerifyResult;
}

/// Returns the canonical ordering of every client the registry knows about.
/// The order is presentation-stable; D3 builds the onboarding grid from
/// this list.
pub fn registry() -> Vec<Box<dyn McpClient>> {
    // D3 will fill in the modules. For scaffolding, return an empty Vec
    // so the rest of the codebase compiles.
    Vec::new()
}
