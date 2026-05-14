//! Backend reachability probe used by every client's `verify()`.
//!
//! Per D8 (`mis_01KQJGR4WZXYFSDP9DN2WEXTJJ`), each enabled client gets
//! two checks after merge:
//!   1. config syntax + `rka` entry parses correctly (per-format)
//!   2. `GET http://127.0.0.1:9712/api/health` returns 200 AND
//!      `GET .../api/capabilities` returns 200 (Affordance C surface).

use std::io::{Read, Write};
use std::net::TcpStream;
use std::time::Duration;

const HEALTH_PATH: &str = "/api/health";
const CAPABILITIES_PATH: &str = "/api/capabilities";

fn probe_path(backend_url: &str, path: &str) -> bool {
    let stripped = match backend_url.strip_prefix("http://") {
        Some(s) => s,
        None => return false,
    };
    let host_port = stripped.split('/').next().unwrap_or(stripped);
    let mut stream = match TcpStream::connect(host_port) {
        Ok(s) => s,
        Err(_) => return false,
    };
    if stream.set_read_timeout(Some(Duration::from_secs(2))).is_err() {
        return false;
    }
    let req = format!(
        "GET {path} HTTP/1.1\r\nHost: {host_port}\r\nConnection: close\r\nUser-Agent: rka-desktop/0.1\r\n\r\n"
    );
    if stream.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut buf = Vec::with_capacity(512);
    let mut chunk = [0u8; 512];
    while let Ok(n) = stream.read(&mut chunk) {
        if n == 0 {
            break;
        }
        buf.extend_from_slice(&chunk[..n]);
        if buf.len() >= 16 {
            break;
        }
    }
    let head = String::from_utf8_lossy(&buf);
    head.starts_with("HTTP/1.1 2") || head.starts_with("HTTP/1.0 2")
}

pub fn backend_reachable(backend_url: &str) -> bool {
    probe_path(backend_url, HEALTH_PATH)
}

pub fn capabilities_reachable(backend_url: &str) -> bool {
    probe_path(backend_url, CAPABILITIES_PATH)
}
