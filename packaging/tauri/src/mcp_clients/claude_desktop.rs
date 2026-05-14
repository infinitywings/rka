//! Claude Desktop MCP-config integration.
//!
//! Config: `~/Library/Application Support/Claude/claude_desktop_config.json`
//! Root key: `mcpServers`
//! Entry shape: `{"command": "...", "args": []}`
//!
//! Source: Anthropic's MCP quickstart docs (https://docs.claude.com/en/docs/mcp/quickstart, accessed 2026-05-13)
//! and direct inspection of an existing live config on this Mac.

use std::path::{Path, PathBuf};

use super::{
    json_merger, verify, ConfigFormat, McpClient, MergeError, MergeResult, ProbeResult,
    RemoveResult, VerifyResult,
};

pub struct ClaudeDesktop;

impl ClaudeDesktop {
    fn user_config() -> Option<PathBuf> {
        let base = dirs::config_dir()?; // ~/Library/Application Support on macOS
        Some(base.join("Claude").join("claude_desktop_config.json"))
    }
}

impl McpClient for ClaudeDesktop {
    fn id(&self) -> &'static str {
        "claude_desktop"
    }

    fn display_name(&self) -> &'static str {
        "Claude Desktop"
    }

    fn config_format(&self) -> ConfigFormat {
        ConfigFormat::Json
    }

    fn detect(&self) -> ProbeResult {
        let mut evidence = Vec::new();
        let app_bundle = Path::new("/Applications/Claude.app");
        if app_bundle.exists() {
            evidence.push(app_bundle.display().to_string());
        }
        if let Some(cfg) = Self::user_config() {
            if let Some(parent) = cfg.parent() {
                if parent.exists() {
                    evidence.push(parent.display().to_string());
                }
            }
        }
        ProbeResult {
            detected: !evidence.is_empty(),
            evidence,
        }
    }

    fn config_path(&self) -> Option<PathBuf> {
        Self::user_config()
    }

    fn read_merge_write_rka(&self, launcher: &Path) -> Result<MergeResult, MergeError> {
        let path = Self::user_config()
            .ok_or_else(|| MergeError::Unparseable("no home dir".into()))?;
        json_merger::merge_rka_entry(&path, "mcpServers", launcher, false, false)
    }

    fn remove_rka(&self) -> Result<RemoveResult, MergeError> {
        let path = Self::user_config()
            .ok_or_else(|| MergeError::Unparseable("no home dir".into()))?;
        json_merger::remove_rka_entry(&path, "mcpServers")
    }

    fn verify(&self, backend_url: &str) -> VerifyResult {
        let Some(path) = Self::user_config() else {
            return VerifyResult {
                config_syntax_ok: false,
                rka_entry_present: false,
                backend_reachable: false,
                capabilities_reachable: false,
                reason: Some("no home dir".into()),
            };
        };
        let launcher = super::stable_launcher_path();
        let (syntax, present, reason) = json_merger::verify_rka_entry(&path, "mcpServers", &launcher);
        VerifyResult {
            config_syntax_ok: syntax,
            rka_entry_present: present,
            backend_reachable: verify::backend_reachable(backend_url),
            capabilities_reachable: verify::capabilities_reachable(backend_url),
            reason,
        }
    }
}
