//! VSCode-Copilot MCP-config integration.
//!
//! Config: `~/Library/Application Support/Code/User/mcp.json` (Stable)
//!         `~/Library/Application Support/Code - Insiders/User/mcp.json` (Insiders)
//!
//! **Root key: `servers`** (NOT `mcpServers` — easy copy-paste hazard;
//! the D7 integration matrix has a dedicated case (j) catching any
//! regression that writes `mcpServers` here).
//!
//! Entry shape: `{"command": "...", "args": [], "type": "stdio"}` for
//! stdio transport, or `{"url": "...", "type": "http"}` for HTTP. Sibling
//! key `inputs: []` is preserved.
//!
//! Source: VSCode MCP docs
//! (https://code.visualstudio.com/docs/copilot/customization/mcp-servers,
//! accessed 2026-05-13) plus live config inspection on this Mac
//! confirming `servers` (not `mcpServers`) as root.

use std::path::{Path, PathBuf};

use super::{
    json_merger, verify, ConfigFormat, McpClient, MergeError, MergeResult, ProbeResult,
    RemoveResult, VerifyResult,
};

pub struct VscodeCopilot;

const VSCODE_ROOT_KEY: &str = "servers";

impl VscodeCopilot {
    fn candidate_paths() -> Vec<PathBuf> {
        let mut out = Vec::new();
        let Some(base) = dirs::config_dir() else {
            return out;
        };
        for variant in [
            "Code/User/mcp.json",
            "Code - Insiders/User/mcp.json",
            "VSCodium/User/mcp.json",
        ] {
            out.push(base.join(variant));
        }
        out
    }

    /// Prefer an existing config file; otherwise fall back to the
    /// Stable channel default.
    fn user_config() -> Option<PathBuf> {
        let candidates = Self::candidate_paths();
        candidates
            .iter()
            .find(|p| p.exists())
            .cloned()
            .or_else(|| candidates.into_iter().next())
    }
}

impl McpClient for VscodeCopilot {
    fn id(&self) -> &'static str {
        "vscode_copilot"
    }

    fn display_name(&self) -> &'static str {
        "VSCode + GitHub Copilot"
    }

    fn config_format(&self) -> ConfigFormat {
        ConfigFormat::Json
    }

    fn detect(&self) -> ProbeResult {
        let mut evidence = Vec::new();
        for app in [
            "/Applications/Visual Studio Code.app",
            "/Applications/Visual Studio Code - Insiders.app",
            "/Applications/VSCodium.app",
        ] {
            if Path::new(app).exists() {
                evidence.push(app.to_string());
            }
        }
        for c in Self::candidate_paths() {
            if c.parent().map(|p| p.exists()).unwrap_or(false) {
                evidence.push(c.parent().unwrap().display().to_string());
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
        // VSCode-Copilot expects `type: "stdio"` and uses the `servers`
        // root key (NOT mcpServers).
        json_merger::merge_rka_entry(&path, VSCODE_ROOT_KEY, launcher, true, false)
    }

    fn remove_rka(&self) -> Result<RemoveResult, MergeError> {
        let path = Self::user_config()
            .ok_or_else(|| MergeError::Unparseable("no home dir".into()))?;
        json_merger::remove_rka_entry(&path, VSCODE_ROOT_KEY)
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
        let (syntax, present, reason) =
            json_merger::verify_rka_entry(&path, VSCODE_ROOT_KEY, &launcher);
        VerifyResult {
            config_syntax_ok: syntax,
            rka_entry_present: present,
            backend_reachable: verify::backend_reachable(backend_url),
            capabilities_reachable: verify::capabilities_reachable(backend_url),
            reason,
        }
    }
}
