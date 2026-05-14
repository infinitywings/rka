//! Codex Mac App MCP-config integration.
//!
//! **Shares `~/.codex/config.toml` with the Codex CLI** — verified on
//! 2026-05-13 by auditing the Codex.app bundle's
//! `~/Library/Application Support/Codex/` directory (Electron Chromium
//! state only — no parallel config.toml). Bundle id `com.openai.codex`.
//!
//! UI presents this client as a separate checkbox so users can opt-in
//! based on the actual app they're using; under the hood the write
//! target dedupes against `CodexCli` so a single `cargo tauri` write
//! lands exactly once.
//!
//! Source: live filesystem audit + OpenAI Codex app docs
//! (https://developers.openai.com/codex/app, accessed 2026-05-13).

use std::path::{Path, PathBuf};

use super::{
    codex_cli, toml_merger, verify, ConfigFormat, McpClient, MergeError, MergeResult,
    ProbeResult, RemoveResult, VerifyResult,
};

pub struct CodexApp;

impl McpClient for CodexApp {
    fn id(&self) -> &'static str {
        "codex_app"
    }

    fn display_name(&self) -> &'static str {
        "Codex (macOS app)"
    }

    fn config_format(&self) -> ConfigFormat {
        ConfigFormat::Toml
    }

    fn detect(&self) -> ProbeResult {
        let mut evidence = Vec::new();
        let app_bundle = Path::new("/Applications/Codex.app");
        if app_bundle.exists() {
            evidence.push(app_bundle.display().to_string());
        }
        if let Some(d) = dirs::data_dir().map(|b| b.join("Codex")) {
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
        codex_cli::codex_config_path()
    }

    fn read_merge_write_rka(&self, launcher: &Path) -> Result<MergeResult, MergeError> {
        let path = codex_cli::codex_config_path()
            .ok_or_else(|| MergeError::Unparseable("no home dir".into()))?;
        toml_merger::merge_rka_entry(&path, launcher, false)
    }

    fn remove_rka(&self) -> Result<RemoveResult, MergeError> {
        let path = codex_cli::codex_config_path()
            .ok_or_else(|| MergeError::Unparseable("no home dir".into()))?;
        toml_merger::remove_rka_entry(&path)
    }

    fn verify(&self, backend_url: &str) -> VerifyResult {
        let Some(path) = codex_cli::codex_config_path() else {
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
