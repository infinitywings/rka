//! Claude Code MCP-config integration.
//!
//! Config: `~/.claude.json` (the `mcpServers` block sits alongside ~20
//! other top-level keys; we touch ONLY the `mcpServers.rka` slot).
//! Root key: `mcpServers`
//! Entry shape: `{"type": "stdio", "command": "...", "args": [], "env": {}}`
//!
//! Source: Anthropic's Claude Code MCP docs
//! (https://docs.claude.com/en/docs/claude-code/mcp, accessed 2026-05-13)
//! plus inspection of a live `~/.claude.json` showing `type: "stdio"`
//! on every existing entry.

use std::path::{Path, PathBuf};

use super::{
    json_merger, verify, ConfigFormat, McpClient, MergeError, MergeResult, ProbeResult,
    RemoveResult, VerifyResult,
};

pub struct ClaudeCode;

impl ClaudeCode {
    fn user_config() -> Option<PathBuf> {
        Some(dirs::home_dir()?.join(".claude.json"))
    }
    fn claude_dir() -> Option<PathBuf> {
        Some(dirs::home_dir()?.join(".claude"))
    }
}

impl McpClient for ClaudeCode {
    fn id(&self) -> &'static str {
        "claude_code"
    }

    fn display_name(&self) -> &'static str {
        "Claude Code"
    }

    fn config_format(&self) -> ConfigFormat {
        ConfigFormat::Json
    }

    fn detect(&self) -> ProbeResult {
        let mut evidence = Vec::new();
        if let Some(d) = Self::claude_dir() {
            if d.exists() {
                evidence.push(d.display().to_string());
            }
        }
        if let Some(c) = Self::user_config() {
            if c.exists() {
                evidence.push(c.display().to_string());
            }
        }
        // CLI in PATH (Homebrew or local install)
        for cand in ["/opt/homebrew/bin/claude", "/usr/local/bin/claude"] {
            if Path::new(cand).exists() {
                evidence.push(cand.to_string());
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
        // Claude Code expects `type: "stdio"`.
        json_merger::merge_rka_entry(&path, "mcpServers", launcher, true, false)
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
