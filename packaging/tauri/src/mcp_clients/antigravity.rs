//! Antigravity MCP-config integration.
//!
//! Config: `~/.gemini/antigravity/mcp_config.json`
//! Root key: **`mcpServers`** (NOT `servers` — despite Antigravity
//! being a VSCode fork, Google's MCP integration uses `mcpServers`
//! as the root key, verified by grepping `out/main.js` in the app
//! bundle on 2026-05-13).
//! Entry shape: `{"command": "...", "args": []}`. Optional fields
//! `disabled: bool` and `disabledTools: [string]` may be present on
//! existing entries — the merger preserves them by virtue of the
//! `preserve_order` serde_json round-trip; we only touch the `rka`
//! key.
//!
//! Source: WebFetch of https://antigravity.google/docs/mcp returned
//! an empty page on 2026-05-13; schema was confirmed by static code
//! analysis of `/Applications/Antigravity.app/Contents/Resources/app/
//! out/main.js` (jrn_01KRJ10CSJY14N3ZR7FFK186PX).

use std::path::{Path, PathBuf};

use super::{
    json_merger, verify, ConfigFormat, McpClient, MergeError, MergeResult, ProbeResult,
    RemoveResult, VerifyResult,
};

pub struct Antigravity;

impl Antigravity {
    fn user_config() -> Option<PathBuf> {
        Some(
            dirs::home_dir()?
                .join(".gemini")
                .join("antigravity")
                .join("mcp_config.json"),
        )
    }
}

impl McpClient for Antigravity {
    fn id(&self) -> &'static str {
        "antigravity"
    }

    fn display_name(&self) -> &'static str {
        "Antigravity (Google)"
    }

    fn config_format(&self) -> ConfigFormat {
        ConfigFormat::Json
    }

    fn detect(&self) -> ProbeResult {
        let mut evidence = Vec::new();
        let app_bundle = Path::new("/Applications/Antigravity.app");
        if app_bundle.exists() {
            evidence.push(app_bundle.display().to_string());
        }
        if let Some(d) = dirs::home_dir().map(|h| h.join(".gemini").join("antigravity")) {
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
