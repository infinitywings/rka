//! Atomic TOML-config merger for Codex (CLI + Mac App share
//! `~/.codex/config.toml`).
//!
//! Uses `toml_edit` so unrelated tables, comments, and whitespace are
//! preserved across the read/merge/write cycle. Round-trip preservation
//! is the audit-symmetry invariant for D7.

use std::fs;
use std::path::{Path, PathBuf};

use chrono::Utc;
use toml_edit::{value, Array, DocumentMut, Item, Table};

use super::{MergeError, MergeResult, RemoveResult};

const RKA_ENTRY_KEY: &str = "rka";
const ROOT_TABLE: &str = "mcp_servers";

fn backup_path(config_path: &Path) -> PathBuf {
    let ts = Utc::now().format("%Y%m%d-%H%M%S").to_string();
    let mut name = config_path
        .file_name()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "config.toml".to_string());
    name.push_str(&format!(".backup-{ts}"));
    config_path.with_file_name(name)
}

fn atomic_write(config_path: &Path, content: &str) -> Result<(), MergeError> {
    let tmp = config_path.with_extension("rka-tmp");
    fs::write(&tmp, content)?;
    fs::rename(&tmp, config_path)?;
    Ok(())
}

fn read_doc(config_path: &Path) -> Result<DocumentMut, MergeError> {
    if !config_path.exists() {
        return Ok(DocumentMut::new());
    }
    let raw = fs::read_to_string(config_path)?;
    if raw.trim().is_empty() {
        return Ok(DocumentMut::new());
    }
    raw.parse::<DocumentMut>()
        .map_err(|e| MergeError::Unparseable(format!("{e} (file: {})", config_path.display())))
}

/// Merge `[mcp_servers.rka]` into a TOML config, preserving every
/// unrelated table + comments.
pub fn merge_rka_entry(
    config_path: &Path,
    launcher: &Path,
    force_replace: bool,
) -> Result<MergeResult, MergeError> {
    if let Some(parent) = config_path.parent() {
        fs::create_dir_all(parent)?;
    }

    let mut doc = read_doc(config_path)?;

    if doc.get(ROOT_TABLE).is_none() {
        let mut tbl = Table::new();
        tbl.set_implicit(true);
        doc.insert(ROOT_TABLE, Item::Table(tbl));
    }

    let servers_table = doc
        .get_mut(ROOT_TABLE)
        .and_then(Item::as_table_mut)
        .ok_or_else(|| {
            MergeError::Unparseable(format!(
                "expected `[{ROOT_TABLE}]` to be a table in {}",
                config_path.display()
            ))
        })?;

    let previous_command: Option<String> = servers_table
        .get(RKA_ENTRY_KEY)
        .and_then(Item::as_table)
        .and_then(|t| t.get("command"))
        .and_then(Item::as_str)
        .map(|s| s.to_string());

    let new_command = launcher.to_string_lossy().into_owned();
    if let Some(prev) = &previous_command {
        if prev != &new_command && !force_replace {
            return Err(MergeError::Conflict(format!(
                "`[mcp_servers.rka]` already points at `{prev}`; new launcher is `{new_command}`"
            )));
        }
    }

    let backup = if config_path.exists() {
        let b = backup_path(config_path);
        fs::copy(config_path, &b)?;
        Some(b)
    } else {
        None
    };

    let mut entry = Table::new();
    entry["command"] = value(new_command.clone());
    entry["args"] = value(Array::new());
    servers_table.insert(RKA_ENTRY_KEY, Item::Table(entry));

    let serialized = doc.to_string();
    atomic_write(config_path, &serialized)?;

    let verify = read_doc(config_path)
        .map_err(|e| MergeError::VerifyFailed(format!("re-read: {e}")))?;
    let verified = verify
        .get(ROOT_TABLE)
        .and_then(Item::as_table)
        .and_then(|t| t.get(RKA_ENTRY_KEY))
        .is_some();
    if !verified {
        return Err(MergeError::VerifyFailed(
            "`[mcp_servers.rka]` not present after atomic write".into(),
        ));
    }

    Ok(MergeResult {
        config_path: config_path.to_path_buf(),
        backup_path: backup,
        previous_rka_command: previous_command,
        new_rka_command: new_command,
    })
}

pub fn remove_rka_entry(config_path: &Path) -> Result<RemoveResult, MergeError> {
    if !config_path.exists() {
        return Ok(RemoveResult {
            config_path: config_path.to_path_buf(),
            removed: false,
            backup_path: None,
        });
    }

    let mut doc = read_doc(config_path)?;
    let removed = if let Some(servers) = doc.get_mut(ROOT_TABLE).and_then(Item::as_table_mut) {
        servers.remove(RKA_ENTRY_KEY).is_some()
    } else {
        false
    };

    if !removed {
        return Ok(RemoveResult {
            config_path: config_path.to_path_buf(),
            removed: false,
            backup_path: None,
        });
    }

    let backup = backup_path(config_path);
    fs::copy(config_path, &backup)?;

    let serialized = doc.to_string();
    atomic_write(config_path, &serialized)?;

    Ok(RemoveResult {
        config_path: config_path.to_path_buf(),
        removed: true,
        backup_path: Some(backup),
    })
}

pub fn verify_rka_entry(
    config_path: &Path,
    expected_launcher: &Path,
) -> (bool, bool, Option<String>) {
    if !config_path.exists() {
        return (false, false, Some(format!("missing: {}", config_path.display())));
    }
    let doc = match read_doc(config_path) {
        Ok(d) => d,
        Err(e) => return (false, false, Some(e.to_string())),
    };
    let Some(entry) = doc
        .get(ROOT_TABLE)
        .and_then(Item::as_table)
        .and_then(|t| t.get(RKA_ENTRY_KEY))
        .and_then(Item::as_table)
    else {
        return (true, false, Some(format!("no `[{ROOT_TABLE}.{RKA_ENTRY_KEY}]`")));
    };
    let cmd = entry.get("command").and_then(Item::as_str).unwrap_or("");
    let expected = expected_launcher.to_string_lossy();
    let matches = cmd == expected;
    (
        true,
        matches,
        if matches {
            None
        } else {
            Some(format!("command mismatch: got `{cmd}`, expected `{expected}`"))
        },
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;
    use std::sync::atomic::{AtomicU64, Ordering};

    fn tmp_config() -> PathBuf {
        static COUNTER: AtomicU64 = AtomicU64::new(0);
        let id = COUNTER.fetch_add(1, Ordering::SeqCst);
        let pid = std::process::id();
        let dir = env::temp_dir().join(format!("rka-toml-merger-{pid}-{id}"));
        fs::create_dir_all(&dir).unwrap();
        dir.join("config.toml")
    }

    fn launcher() -> PathBuf {
        PathBuf::from("/Users/test/Library/Application Support/RKA/bin/rka-mcp.sh")
    }

    #[test]
    fn merge_into_empty() {
        let p = tmp_config();
        let r = merge_rka_entry(&p, &launcher(), false).unwrap();
        assert_eq!(r.new_rka_command, launcher().to_string_lossy());
        let raw = fs::read_to_string(&p).unwrap();
        assert!(raw.contains("[mcp_servers.rka]"));
        assert!(raw.contains("command"));
    }

    #[test]
    fn round_trip_preserves_other_tables() {
        let p = tmp_config();
        let existing = r#"
# Codex global config
model = "gpt-5"
model_reasoning_effort = "high"

[mcp_servers.github]
command = "/usr/local/bin/gh-mcp"
args = []

[projects.foo]
worktree_enabled = true
"#;
        fs::write(&p, existing).unwrap();

        merge_rka_entry(&p, &launcher(), false).unwrap();
        let after = fs::read_to_string(&p).unwrap();
        assert!(after.contains("# Codex global config"), "comment preserved");
        assert!(after.contains("[mcp_servers.github]"));
        assert!(after.contains("[mcp_servers.rka]"));
        assert!(after.contains("[projects.foo]"));
        assert!(after.contains("model = \"gpt-5\""));

        let rm = remove_rka_entry(&p).unwrap();
        assert!(rm.removed);
        let final_raw = fs::read_to_string(&p).unwrap();
        assert!(final_raw.contains("[mcp_servers.github]"));
        assert!(!final_raw.contains("[mcp_servers.rka]"));
        assert!(final_raw.contains("[projects.foo]"));
    }

    #[test]
    fn conflict_when_existing_rka_points_elsewhere() {
        let p = tmp_config();
        let existing = r#"
[mcp_servers.rka]
command = "/old/path/rka"
args = []
"#;
        fs::write(&p, existing).unwrap();
        let err = merge_rka_entry(&p, &launcher(), false).unwrap_err();
        assert!(matches!(err, MergeError::Conflict(_)));
    }

    #[test]
    fn refuses_malformed_toml() {
        let p = tmp_config();
        fs::write(&p, "[invalid toml { syntax").unwrap();
        let err = merge_rka_entry(&p, &launcher(), false).unwrap_err();
        assert!(matches!(err, MergeError::Unparseable(_)));
    }

    #[test]
    fn remove_is_idempotent_when_absent() {
        let p = tmp_config();
        fs::write(&p, "[mcp_servers.other]\ncommand = \"/x\"\nargs = []\n").unwrap();
        let rm = remove_rka_entry(&p).unwrap();
        assert!(!rm.removed);
    }
}
