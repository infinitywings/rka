//! Cursor MCP-config integration (user-scope only; project `.cursor/`
//! is out of scope per the mission boundary).
//!
//! Config: `~/.cursor/mcp.json`
//! Root key: `mcpServers`
//! Entry shape: `{"command": "...", "args": []}`
//!
//! Source: Cursor MCP docs (https://cursor.com/docs/mcp, accessed
//! 2026-05-13) plus live config inspection on this Mac.

use std::path::{Path, PathBuf};

use super::{
    json_merger, verify, ConfigFormat, McpClient, MergeError, MergeResult, ProbeResult,
    RemoveResult, VerifyResult,
};

pub struct Cursor;

impl Cursor {
    fn user_config() -> Option<PathBuf> {
        Some(dirs::home_dir()?.join(".cursor").join("mcp.json"))
    }
}

impl McpClient for Cursor {
    fn id(&self) -> &'static str {
        "cursor"
    }

    fn display_name(&self) -> &'static str {
        "Cursor"
    }

    fn config_format(&self) -> ConfigFormat {
        ConfigFormat::Json
    }

    fn detect(&self) -> ProbeResult {
        let mut evidence = Vec::new();
        let app_bundle = Path::new("/Applications/Cursor.app");
        if app_bundle.exists() {
            evidence.push(app_bundle.display().to_string());
        }
        if let Some(d) = dirs::home_dir().map(|h| h.join(".cursor")) {
            if d.exists() {
                evidence.push(d.display().to_string());
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
