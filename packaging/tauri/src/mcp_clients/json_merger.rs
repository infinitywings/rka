//! Atomic JSON-config merger for `mcpServers`-style (Claude Desktop /
//! Claude Code / Cursor / Antigravity) and `servers`-style
//! (VSCode-Copilot) clients.
//!
//! Round-trip preservation is the load-bearing invariant: writing the
//! `rka` entry must not perturb any other server, and removing it must
//! leave every other entry intact. The `preserve_order` feature on
//! `serde_json` keeps key ordering stable across the read/merge/write
//! cycle.

use std::fs;
use std::path::{Path, PathBuf};

use chrono::Utc;
use serde_json::{json, Map, Value};

use super::{MergeError, MergeResult, RemoveResult};

const RKA_ENTRY_KEY: &str = "rka";

/// Strip `//` line and `/* … */` block comments + trailing commas so we
/// can read VSCode-Copilot's JSONC-tolerant configs without pulling a
/// real JSONC parser.
fn lenient_parse(raw: &str) -> Result<Value, serde_json::Error> {
    let mut cleaned = String::with_capacity(raw.len());
    let bytes = raw.as_bytes();
    let mut i = 0;
    let mut in_string = false;
    let mut escape = false;
    while i < bytes.len() {
        let b = bytes[i];
        if in_string {
            cleaned.push(b as char);
            if escape {
                escape = false;
            } else if b == b'\\' {
                escape = true;
            } else if b == b'"' {
                in_string = false;
            }
            i += 1;
            continue;
        }
        if b == b'"' {
            in_string = true;
            cleaned.push('"');
            i += 1;
            continue;
        }
        if b == b'/' && i + 1 < bytes.len() {
            if bytes[i + 1] == b'/' {
                while i < bytes.len() && bytes[i] != b'\n' {
                    i += 1;
                }
                continue;
            }
            if bytes[i + 1] == b'*' {
                i += 2;
                while i + 1 < bytes.len() && !(bytes[i] == b'*' && bytes[i + 1] == b'/') {
                    i += 1;
                }
                i += 2;
                continue;
            }
        }
        cleaned.push(b as char);
        i += 1;
    }

    // Strip trailing commas before `}` and `]`.
    let mut final_buf = String::with_capacity(cleaned.len());
    let chars: Vec<char> = cleaned.chars().collect();
    let mut j = 0;
    while j < chars.len() {
        let c = chars[j];
        if c == ',' {
            let mut k = j + 1;
            while k < chars.len() && chars[k].is_whitespace() {
                k += 1;
            }
            if k < chars.len() && (chars[k] == '}' || chars[k] == ']') {
                j += 1;
                continue;
            }
        }
        final_buf.push(c);
        j += 1;
    }
    serde_json::from_str(&final_buf)
}

fn backup_path(config_path: &Path) -> PathBuf {
    let ts = Utc::now().format("%Y%m%d-%H%M%S").to_string();
    let mut name = config_path.file_name().map(|s| s.to_string_lossy().into_owned()).unwrap_or_else(|| "config".to_string());
    name.push_str(&format!(".backup-{ts}"));
    config_path.with_file_name(name)
}

fn atomic_write(config_path: &Path, content: &str) -> Result<(), MergeError> {
    let tmp = config_path.with_extension("rka-tmp");
    fs::write(&tmp, content)?;
    fs::rename(&tmp, config_path)?;
    Ok(())
}

/// Read an existing JSON config, returning a parsed `Value` plus the raw
/// text. Returns an empty object value when the file is missing or 0-byte
/// (so callers can merge without a pre-existing config).
fn read_existing(config_path: &Path) -> Result<(Value, Option<String>), MergeError> {
    if !config_path.exists() {
        return Ok((json!({}), None));
    }
    let raw = fs::read_to_string(config_path)?;
    if raw.trim().is_empty() {
        return Ok((json!({}), Some(raw)));
    }
    let parsed = lenient_parse(&raw)
        .map_err(|e| MergeError::Unparseable(format!("{e} (file: {})", config_path.display())))?;
    if !parsed.is_object() {
        return Err(MergeError::Unparseable(format!(
            "expected JSON object at root in {}",
            config_path.display()
        )));
    }
    Ok((parsed, Some(raw)))
}

fn build_entry(
    launcher: &Path,
    include_type: bool,
    extra: &[(&str, Value)],
) -> Value {
    let mut obj: Map<String, Value> = Map::new();
    obj.insert("command".to_string(), Value::String(launcher.to_string_lossy().into_owned()));
    obj.insert("args".to_string(), json!([]));
    if include_type {
        obj.insert("type".to_string(), Value::String("stdio".to_string()));
    }
    for (k, v) in extra {
        obj.insert((*k).to_string(), v.clone());
    }
    Value::Object(obj)
}

/// Merge an `rka` entry into a JSON config, preserving every unrelated
/// server.
///
/// `root_key` is `"mcpServers"` for Claude Desktop / Code / Cursor /
/// Antigravity, `"servers"` for VSCode-Copilot.
///
/// `include_type` emits `"type": "stdio"` (Claude Code, VSCode-Copilot
/// expect it).
///
/// `force_replace=false` returns `Conflict` when an existing `rka`
/// entry points at a different launcher; UI prompts the user to
/// confirm replacement.
pub fn merge_rka_entry(
    config_path: &Path,
    root_key: &str,
    launcher: &Path,
    include_type: bool,
    force_replace: bool,
) -> Result<MergeResult, MergeError> {
    if let Some(parent) = config_path.parent() {
        fs::create_dir_all(parent)?;
    }

    let (mut root, raw_existing) = read_existing(config_path)?;
    let root_obj = root.as_object_mut().expect("read_existing guarantees object");

    if !root_obj.contains_key(root_key) {
        root_obj.insert(root_key.to_string(), Value::Object(Map::new()));
    }
    let servers = root_obj
        .get_mut(root_key)
        .and_then(|v| v.as_object_mut())
        .ok_or_else(|| {
            MergeError::Unparseable(format!(
                "expected `{root_key}` to be an object in {}",
                config_path.display()
            ))
        })?;

    let previous = servers.get(RKA_ENTRY_KEY).cloned();
    let new_entry = build_entry(launcher, include_type, &[]);
    let previous_command = previous
        .as_ref()
        .and_then(|p| p.get("command"))
        .and_then(Value::as_str)
        .map(|s| s.to_string());

    if let Some(prev) = &previous {
        let prev_cmd = prev.get("command").and_then(Value::as_str).unwrap_or("");
        let new_cmd = launcher.to_string_lossy();
        if prev_cmd != new_cmd && !force_replace {
            return Err(MergeError::Conflict(format!(
                "`rka` already points at `{prev_cmd}`; new launcher is `{new_cmd}`"
            )));
        }
    }

    let backup = if raw_existing.is_some() && config_path.exists() {
        let backup_path = backup_path(config_path);
        fs::copy(config_path, &backup_path)?;
        Some(backup_path)
    } else {
        None
    };

    servers.insert(RKA_ENTRY_KEY.to_string(), new_entry.clone());

    let serialized = serde_json::to_string_pretty(&root)
        .map_err(|e| MergeError::Serde(e.to_string()))?;
    atomic_write(config_path, &serialized)?;

    let (verify_root, _) = read_existing(config_path)
        .map_err(|e| MergeError::VerifyFailed(format!("re-read: {e}")))?;
    let verified = verify_root
        .get(root_key)
        .and_then(|v| v.get(RKA_ENTRY_KEY))
        .is_some();
    if !verified {
        return Err(MergeError::VerifyFailed(
            "`rka` entry not present after atomic write".into(),
        ));
    }

    Ok(MergeResult {
        config_path: config_path.to_path_buf(),
        backup_path: backup,
        previous_rka_command: previous_command,
        new_rka_command: launcher.to_string_lossy().into_owned(),
    })
}

/// Remove the `rka` entry while preserving every other server.
///
/// Returns `removed: false` when the config or `rka` entry is absent
/// (idempotent — calling this on an un-onboarded client is a no-op).
pub fn remove_rka_entry(
    config_path: &Path,
    root_key: &str,
) -> Result<RemoveResult, MergeError> {
    if !config_path.exists() {
        return Ok(RemoveResult {
            config_path: config_path.to_path_buf(),
            removed: false,
            backup_path: None,
        });
    }

    let (mut root, _) = read_existing(config_path)?;
    let root_obj = root.as_object_mut().expect("read_existing guarantees object");
    let servers = match root_obj.get_mut(root_key).and_then(|v| v.as_object_mut()) {
        Some(s) => s,
        None => {
            return Ok(RemoveResult {
                config_path: config_path.to_path_buf(),
                removed: false,
                backup_path: None,
            });
        }
    };
    if !servers.contains_key(RKA_ENTRY_KEY) {
        return Ok(RemoveResult {
            config_path: config_path.to_path_buf(),
            removed: false,
            backup_path: None,
        });
    }

    let backup = {
        let b = backup_path(config_path);
        fs::copy(config_path, &b)?;
        b
    };

    servers.remove(RKA_ENTRY_KEY);

    let serialized = serde_json::to_string_pretty(&root)
        .map_err(|e| MergeError::Serde(e.to_string()))?;
    atomic_write(config_path, &serialized)?;

    Ok(RemoveResult {
        config_path: config_path.to_path_buf(),
        removed: true,
        backup_path: Some(backup),
    })
}

/// Re-parse the config and check the `rka` entry is present + its
/// `command` field matches the expected launcher.
pub fn verify_rka_entry(
    config_path: &Path,
    root_key: &str,
    expected_launcher: &Path,
) -> (bool, bool, Option<String>) {
    if !config_path.exists() {
        return (false, false, Some(format!("missing: {}", config_path.display())));
    }
    let (root, _) = match read_existing(config_path) {
        Ok(r) => r,
        Err(e) => return (false, false, Some(e.to_string())),
    };
    let Some(entry) = root.get(root_key).and_then(|v| v.get(RKA_ENTRY_KEY)) else {
        return (true, false, Some(format!("no `rka` under `{root_key}`")));
    };
    let cmd = entry.get("command").and_then(Value::as_str).unwrap_or("");
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
        let dir = env::temp_dir().join(format!("rka-json-merger-{pid}-{id}"));
        fs::create_dir_all(&dir).unwrap();
        dir.join("config.json")
    }

    fn launcher() -> PathBuf {
        PathBuf::from("/Users/test/Library/Application Support/RKA/bin/rka-mcp.sh")
    }

    #[test]
    fn merge_into_empty() {
        let p = tmp_config();
        let r = merge_rka_entry(&p, "mcpServers", &launcher(), false, false).unwrap();
        assert_eq!(r.new_rka_command, launcher().to_string_lossy());
        assert!(r.backup_path.is_none());
        let raw = fs::read_to_string(&p).unwrap();
        assert!(raw.contains("\"rka\""));
        assert!(raw.contains("mcpServers"));
    }

    #[test]
    fn round_trip_preserves_other_servers() {
        let p = tmp_config();
        let existing = r#"{
            "mcpServers": {
                "github":  {"command": "/usr/bin/gh-mcp", "args": []},
                "other":   {"command": "/usr/bin/other-mcp", "args": ["x"]}
            },
            "preferences": {"theme": "dark"}
        }"#;
        fs::write(&p, existing).unwrap();

        merge_rka_entry(&p, "mcpServers", &launcher(), false, false).unwrap();
        let after_merge = fs::read_to_string(&p).unwrap();
        assert!(after_merge.contains("\"github\""));
        assert!(after_merge.contains("\"other\""));
        assert!(after_merge.contains("\"rka\""));
        assert!(after_merge.contains("\"preferences\""));

        let rm = remove_rka_entry(&p, "mcpServers").unwrap();
        assert!(rm.removed);
        let after_remove = fs::read_to_string(&p).unwrap();
        assert!(after_remove.contains("\"github\""));
        assert!(after_remove.contains("\"other\""));
        assert!(!after_remove.contains("\"rka\""));
        assert!(after_remove.contains("\"preferences\""));
    }

    #[test]
    fn conflict_when_existing_rka_points_elsewhere() {
        let p = tmp_config();
        let existing = r#"{"mcpServers": {"rka": {"command": "/old/path/rka", "args": []}}}"#;
        fs::write(&p, existing).unwrap();
        let err = merge_rka_entry(&p, "mcpServers", &launcher(), false, false).unwrap_err();
        match err {
            MergeError::Conflict(_) => {}
            other => panic!("expected Conflict, got {other:?}"),
        }
    }

    #[test]
    fn force_replace_overrides_conflict() {
        let p = tmp_config();
        let existing = r#"{"mcpServers": {"rka": {"command": "/old/path/rka", "args": []}}}"#;
        fs::write(&p, existing).unwrap();
        let r = merge_rka_entry(&p, "mcpServers", &launcher(), false, true).unwrap();
        assert_eq!(r.previous_rka_command.as_deref(), Some("/old/path/rka"));
    }

    #[test]
    fn refuses_malformed_json() {
        let p = tmp_config();
        fs::write(&p, "{not valid json").unwrap();
        let err = merge_rka_entry(&p, "mcpServers", &launcher(), false, false).unwrap_err();
        assert!(matches!(err, MergeError::Unparseable(_)));
    }

    #[test]
    fn tolerates_jsonc_comments() {
        let p = tmp_config();
        let existing = r#"{
            // VSCode style — line comment
            "servers": {
                "github": {"url": "https://api.example.com", "type": "http"},
            }
        }"#;
        fs::write(&p, existing).unwrap();
        let r = merge_rka_entry(&p, "servers", &launcher(), true, false).unwrap();
        assert!(r.backup_path.is_some());
        let after = fs::read_to_string(&p).unwrap();
        assert!(after.contains("\"rka\""));
        assert!(after.contains("\"github\""));
    }

    #[test]
    fn verify_rka_entry_ok_after_merge() {
        let p = tmp_config();
        merge_rka_entry(&p, "mcpServers", &launcher(), false, false).unwrap();
        let (syntax, present, reason) =
            super::verify_rka_entry(&p, "mcpServers", &launcher());
        assert!(syntax);
        assert!(present);
        assert!(reason.is_none());
    }

    #[test]
    fn verify_rka_entry_command_mismatch_marks_not_present() {
        let p = tmp_config();
        merge_rka_entry(&p, "mcpServers", &launcher(), false, false).unwrap();
        let different_launcher = PathBuf::from("/Users/test/elsewhere/rka-mcp.sh");
        let (syntax, present, reason) =
            super::verify_rka_entry(&p, "mcpServers", &different_launcher);
        // Semantics: `present` means "the rka entry we expect is present
        // (correct shape + correct command)". An entry pointing elsewhere
        // is NOT the entry we wrote, so present=false and the reason
        // explains the command-mismatch detail.
        assert!(syntax, "config still parses");
        assert!(!present);
        let reason = reason.expect("mismatch should surface a reason");
        assert!(reason.contains("command mismatch"));
        assert!(reason.contains("elsewhere"));
    }

    #[test]
    fn verify_rka_entry_missing_entry_surfaces_reason() {
        let p = tmp_config();
        std::fs::write(
            &p,
            r#"{"mcpServers":{"github":{"command":"/usr/local/bin/gh","args":[]}}}"#,
        )
        .unwrap();
        let (syntax, present, reason) =
            super::verify_rka_entry(&p, "mcpServers", &launcher());
        assert!(syntax);
        assert!(!present);
        let reason = reason.expect("missing rka should surface a reason");
        assert!(reason.contains("no `rka`"));
    }

    #[test]
    fn verify_rka_entry_missing_file_reports_path() {
        let p = tmp_config();
        // Don't create the file.
        let (syntax, present, reason) =
            super::verify_rka_entry(&p, "mcpServers", &launcher());
        assert!(!syntax);
        assert!(!present);
        assert!(reason.unwrap().contains("missing"));
    }

    #[test]
    fn vscode_root_key_servers_not_mcpServers() {
        let p = tmp_config();
        merge_rka_entry(&p, "servers", &launcher(), true, false).unwrap();
        let raw = fs::read_to_string(&p).unwrap();
        assert!(raw.contains("\"servers\""), "must use `servers` root for VSCode-Copilot");
        assert!(!raw.contains("\"mcpServers\""), "must NOT use `mcpServers` for VSCode-Copilot");
        let parsed: Value = serde_json::from_str(&raw).unwrap();
        let entry = parsed.get("servers").and_then(|v| v.get("rka")).unwrap();
        assert_eq!(entry.get("type").and_then(Value::as_str), Some("stdio"));
    }
}
