//! Codex CLI MCP-config integration.
//!
//! Config: `~/.codex/config.toml`
//! Root table: `[mcp_servers.<name>]`
//! Entry shape: `{command, args}` (optional `tools` table allowed).
//!
//! Source: OpenAI Codex MCP docs
//! (https://developers.openai.com/codex/mcp, accessed 2026-05-13) +
//! live `~/.codex/config.toml` inspection.

use std::path::{Path, PathBuf};

use super::{
    toml_merger, verify, ConfigFormat, McpClient, MergeError, MergeResult, ProbeResult,
    RemoveResult, VerifyResult,
};

pub struct CodexCli;

pub fn codex_config_path() -> Option<PathBuf> {
    Some(dirs::home_dir()?.join(".codex").join("config.toml"))
}

impl McpClient for CodexCli {
    fn id(&self) -> &'static str {
        "codex_cli"
    }

    fn display_name(&self) -> &'static str {
        "Codex CLI"
    }

    fn config_format(&self) -> ConfigFormat {
        ConfigFormat::Toml
    }

    fn detect(&self) -> ProbeResult {
        let mut evidence = Vec::new();
        for cand in ["/opt/homebrew/bin/codex", "/usr/local/bin/codex"] {
            if Path::new(cand).exists() {
                evidence.push(cand.to_string());
            }
        }
        if let Some(d) = dirs::home_dir().map(|h| h.join(".codex")) {
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
        codex_config_path()
    }

    fn read_merge_write_rka(&self, launcher: &Path) -> Result<MergeResult, MergeError> {
        let path = codex_config_path()
            .ok_or_else(|| MergeError::Unparseable("no home dir".into()))?;
        toml_merger::merge_rka_entry(&path, launcher, false)
    }

    fn remove_rka(&self) -> Result<RemoveResult, MergeError> {
        let path = codex_config_path()
            .ok_or_else(|| MergeError::Unparseable("no home dir".into()))?;
        toml_merger::remove_rka_entry(&path)
    }

    fn verify(&self, backend_url: &str) -> VerifyResult {
        let Some(path) = codex_config_path() else {
            return VerifyResult {
                config_syntax_ok: false,
                rka_entry_present: false,
                backend_reachable: false,
                capabilities_reachable: false,
                reason: Some("no home dir".into()),
            };
        };
        let launcher = super::stable_launcher_path();
        let (syntax, present, reason) = toml_merger::verify_rka_entry(&path, &launcher);
        VerifyResult {
            config_syntax_ok: syntax,
            rka_entry_present: present,
            backend_reachable: verify::backend_reachable(backend_url),
            capabilities_reachable: verify::capabilities_reachable(backend_url),
            reason,
        }
    }
}
