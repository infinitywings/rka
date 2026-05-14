//! Diagnostic-copy assembler.
//!
//! Produces the Markdown-ish text blob the Logs panel's "Copy diagnostic
//! info" command places on the clipboard. Brain mid-mission directive
//! (jrn_01KRJ1S13M628DZGAYRS9PFGAD) requires:
//!
//! 1. **First line**: app version + sidecar version + OS + UTC timestamp.
//! 2. **Per-client verified matrix** (table).
//! 3. **Full health + capabilities JSON** (redacted).
//! 4. **DB schema state**: `PRAGMA user_version` plus row counts for
//!    11 tables — journal_entries, decisions, literature, missions,
//!    claims, evidence_clusters, checkpoints, entity_links, claim_edges,
//!    tags, projects.
//! 5. **Log tail** (last 100 lines).
//!
//! Target size: <8 KB normal, <16 KB power-user. NO TELEMETRY transmits;
//! the blob lands on the clipboard only.
//!
//! Redaction policy (Brain ratification): replace any string field whose
//! value matches `^https?://` or `^/.+\.(sock|pipe)$` with `<redacted>`.
//! Covers private LLM endpoint URLs in `llm_model` and unix-domain
//! sockets that might appear in path-like config strings.

use std::io::Read;
use std::path::PathBuf;
use std::time::Duration;

use chrono::Utc;
use serde_json::Value;

use crate::log_writer;
use crate::mcp_clients;

const TABLES: &[&str] = &[
    "journal_entries",
    "decisions",
    "literature",
    "missions",
    "claims",
    "evidence_clusters",
    "checkpoints",
    "entity_links",
    "claim_edges",
    "tags",
    "projects",
];

const APP_VERSION: &str = env!("CARGO_PKG_VERSION");
const BACKEND_URL: &str = "http://127.0.0.1:9712";

pub fn assemble(log_path: &std::path::Path, db_path: &std::path::Path) -> String {
    let mut out = String::with_capacity(8 * 1024);

    let ts = Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string();
    let os = os_summary();
    let sidecar_version = sidecar_version_from_health()
        .unwrap_or_else(|| "<unreachable>".to_string());

    out.push_str(&format!(
        "# RKA diagnostic — {ts}\n\
         app: rka-desktop {APP_VERSION}  ·  sidecar: rka-serve {sidecar_version}  ·  os: {os}\n\n"
    ));

    out.push_str("## Per-client status\n\n");
    out.push_str("| Client | Detected | Config | rka entry | Backend | Capabilities |\n");
    out.push_str("|--------|---------|--------|-----------|---------|--------------|\n");
    for client in mcp_clients::registry() {
        let probe = client.detect();
        let v = client.verify(BACKEND_URL);
        out.push_str(&format!(
            "| {} | {} | {} | {} | {} | {} |\n",
            client.display_name(),
            if probe.detected { "✓" } else { "✗" },
            mark(v.config_syntax_ok),
            mark(v.rka_entry_present),
            mark(v.backend_reachable),
            mark(v.capabilities_reachable),
        ));
    }
    out.push('\n');

    out.push_str("## Backend snapshot\n\n");
    if let Some(body) = fetch_json("/api/health") {
        out.push_str("### /api/health\n\n```json\n");
        out.push_str(&redact_json(&body));
        out.push_str("\n```\n\n");
    } else {
        out.push_str("### /api/health\n\n_(unreachable)_\n\n");
    }
    if let Some(body) = fetch_json("/api/capabilities") {
        out.push_str("### /api/capabilities\n\n```json\n");
        out.push_str(&redact_json(&body));
        out.push_str("\n```\n\n");
    } else {
        out.push_str("### /api/capabilities\n\n_(unreachable)_\n\n");
    }

    out.push_str("## DB schema state\n\n");
    if let Some(stats) = sqlite_stats(db_path) {
        out.push_str(&stats);
    } else {
        out.push_str(&format!(
            "_(no database found at {} — first launch hasn't initialized rka.db yet, or sqlite3 CLI is unavailable)_\n",
            db_path.display()
        ));
    }
    out.push('\n');

    out.push_str("## Log tail (last 100 lines)\n\n```\n");
    match log_writer::tail(log_path, 100) {
        Ok(lines) if !lines.is_empty() => {
            for line in lines {
                out.push_str(&line);
                out.push('\n');
            }
        }
        _ => out.push_str("(empty)\n"),
    }
    out.push_str("```\n");

    out
}

fn mark(b: bool) -> &'static str {
    if b {
        "✓"
    } else {
        "✗"
    }
}

fn os_summary() -> String {
    #[cfg(target_os = "macos")]
    {
        run_capture("sw_vers", &["-productVersion"])
            .map(|v| format!("macOS {}", v.trim()))
            .unwrap_or_else(|| "macOS".to_string())
    }
    #[cfg(not(target_os = "macos"))]
    {
        format!("{} {}", std::env::consts::OS, std::env::consts::ARCH)
    }
}

fn run_capture(cmd: &str, args: &[&str]) -> Option<String> {
    let out = std::process::Command::new(cmd).args(args).output().ok()?;
    if !out.status.success() {
        return None;
    }
    String::from_utf8(out.stdout).ok()
}

fn sidecar_version_from_health() -> Option<String> {
    let body = fetch_json("/api/health")?;
    let parsed: Value = serde_json::from_str(&body).ok()?;
    parsed
        .get("version")
        .and_then(Value::as_str)
        .map(|s| s.to_string())
}

/// Lightweight blocking HTTP GET returning the response body if status
/// is 2xx. Keeps the crate set lean (no reqwest); same pattern as
/// `sidecar::reqwest_minimal` and `mcp_clients::verify`.
fn fetch_json(path: &str) -> Option<String> {
    use std::io::Write;
    use std::net::TcpStream;

    let host_port = BACKEND_URL.strip_prefix("http://")?;
    let host_port = host_port.split('/').next().unwrap_or(host_port);
    let mut stream = TcpStream::connect(host_port).ok()?;
    stream
        .set_read_timeout(Some(Duration::from_secs(2)))
        .ok()?;
    stream
        .set_write_timeout(Some(Duration::from_secs(2)))
        .ok()?;
    let req = format!(
        "GET {path} HTTP/1.1\r\nHost: {host_port}\r\nConnection: close\r\nUser-Agent: rka-desktop/0.1\r\n\r\n"
    );
    stream.write_all(req.as_bytes()).ok()?;
    let mut raw = Vec::new();
    stream.read_to_end(&mut raw).ok()?;
    let text = String::from_utf8_lossy(&raw);
    if !(text.starts_with("HTTP/1.1 2") || text.starts_with("HTTP/1.0 2")) {
        return None;
    }
    // Crude header/body split.
    let body_offset = text.find("\r\n\r\n")? + 4;
    Some(text[body_offset..].to_string())
}

/// Redact URL-shaped and unix-domain-socket-shaped string values in any
/// JSON document. Preserves structure; only string scalars are touched.
pub fn redact_json(raw: &str) -> String {
    let Ok(value) = serde_json::from_str::<Value>(raw) else {
        return raw.to_string();
    };
    let redacted = redact_value(value);
    serde_json::to_string_pretty(&redacted).unwrap_or_else(|_| raw.to_string())
}

fn redact_value(v: Value) -> Value {
    match v {
        Value::String(s) => Value::String(redact_str(&s)),
        Value::Array(arr) => Value::Array(arr.into_iter().map(redact_value).collect()),
        Value::Object(obj) => {
            let mut out = serde_json::Map::with_capacity(obj.len());
            for (k, v) in obj {
                out.insert(k, redact_value(v));
            }
            Value::Object(out)
        }
        other => other,
    }
}

fn redact_str(s: &str) -> String {
    if s.starts_with("http://") || s.starts_with("https://") {
        return "<redacted>".to_string();
    }
    if s.starts_with('/') && (s.ends_with(".sock") || s.ends_with(".pipe")) {
        return "<redacted>".to_string();
    }
    s.to_string()
}

/// Query the SQLite database via the stock `sqlite3` CLI (present on
/// every macOS install at `/usr/bin/sqlite3`). Avoids pulling rusqlite
/// as a dep for a single read-only query. Returns a Markdown-formatted
/// summary or `None` if the database / sqlite3 binary is unavailable.
fn sqlite_stats(db_path: &std::path::Path) -> Option<String> {
    if !db_path.exists() {
        return None;
    }
    let mut queries = String::new();
    queries.push_str("PRAGMA user_version;\n");
    for t in TABLES {
        queries.push_str(&format!("SELECT '{t}', count(*) FROM {t};\n"));
    }

    let out = std::process::Command::new("sqlite3")
        .arg("-readonly")
        .arg(db_path)
        .arg(queries)
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&out.stdout);
    let mut lines = text.lines();
    let user_version = lines.next().unwrap_or("?").to_string();

    let mut summary = String::new();
    summary.push_str(&format!("PRAGMA user_version: {user_version}\n\n"));
    summary.push_str("| Table | Rows |\n|-------|-----:|\n");
    for line in lines {
        if let Some((name, count)) = line.split_once('|') {
            summary.push_str(&format!("| `{name}` | {count} |\n"));
        }
    }
    Some(summary)
}

/// Resolve the bundled-sidecar SQLite path under
/// `~/Library/Application Support/RKA/rka.db`. Matches the
/// `RKA_PROJECT_DIR` env passed in `sidecar.rs::start`.
pub fn default_db_path() -> PathBuf {
    crate::rka_runtime_dir().join("rka.db")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redact_replaces_https_urls() {
        let input = r#"{"endpoint":"https://api.example.com/v1","name":"rka"}"#;
        let out = redact_json(input);
        assert!(out.contains("<redacted>"));
        assert!(out.contains("\"rka\""));
        assert!(!out.contains("api.example.com"));
    }

    #[test]
    fn redact_replaces_http_urls() {
        let input = r#"{"backend":"http://localhost:9712/v1"}"#;
        let out = redact_json(input);
        assert!(out.contains("<redacted>"));
    }

    #[test]
    fn redact_replaces_sock_paths() {
        let input = r#"{"path":"/var/run/foo.sock"}"#;
        let out = redact_json(input);
        assert!(out.contains("<redacted>"));
    }

    #[test]
    fn redact_replaces_pipe_paths() {
        let input = r#"{"path":"/var/run/foo.pipe"}"#;
        let out = redact_json(input);
        assert!(out.contains("<redacted>"));
    }

    #[test]
    fn redact_preserves_unrelated_strings() {
        let input = r#"{"name":"rka","version":"2.3.5","tag":"/projects/foo"}"#;
        let out = redact_json(input);
        assert!(out.contains("\"rka\""));
        assert!(out.contains("\"2.3.5\""));
        assert!(out.contains("/projects/foo"));
    }

    #[test]
    fn redact_recurses_into_objects_and_arrays() {
        let input = r#"{"a":[{"u":"https://x"},{"u":"plain"}],"b":{"u":"http://y"}}"#;
        let out = redact_json(input);
        // Both URL strings redacted, the plain string survives.
        let redacted_count = out.matches("<redacted>").count();
        assert_eq!(redacted_count, 2);
        assert!(out.contains("\"plain\""));
    }

    #[test]
    fn redact_leaves_unparseable_input_alone() {
        let input = "not valid json";
        let out = redact_json(input);
        assert_eq!(out, "not valid json");
    }
}
