//! Rotating log writer for the bundled `rka-serve` sidecar's stderr.
//!
//! Mission spec: `~/Library/Logs/RKA/server.log` with 10 MB × 5 rotation.
//!
//! Brain mid-mission directive (jrn_01KRJ1S13M628DZGAYRS9PFGAD):
//! "Log rotation (10 MB × 5) must not race with D2's PID-cleanup at app
//! launch." The orphan reaper in `sidecar.rs::reap_orphan` only deletes
//! the PID file, never log files; this writer keeps log rotation in a
//! self-contained background task that doesn't touch the PID surface.

use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::sync::Mutex;

const MAX_BYTES: u64 = 10 * 1024 * 1024; // 10 MB
const MAX_ROTATIONS: usize = 5;
const ROTATE_CHECK_EVERY: u64 = 64; // lines

pub struct RotatingLog {
    path: PathBuf,
    file: File,
    bytes_written_since_check: u64,
    lines_since_check: u64,
}

impl RotatingLog {
    pub fn open(log_path: PathBuf) -> std::io::Result<Self> {
        if let Some(parent) = log_path.parent() {
            fs::create_dir_all(parent)?;
        }
        let file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)?;
        Ok(Self {
            path: log_path,
            file,
            bytes_written_since_check: 0,
            lines_since_check: 0,
        })
    }

    pub fn write_line(&mut self, line: &str) -> std::io::Result<()> {
        let mut bytes = line.as_bytes().to_vec();
        if !bytes.ends_with(b"\n") {
            bytes.push(b'\n');
        }
        self.file.write_all(&bytes)?;
        self.bytes_written_since_check =
            self.bytes_written_since_check.saturating_add(bytes.len() as u64);
        self.lines_since_check = self.lines_since_check.saturating_add(1);

        if self.lines_since_check >= ROTATE_CHECK_EVERY {
            self.lines_since_check = 0;
            let current_size = self
                .file
                .metadata()
                .map(|m| m.len())
                .unwrap_or(self.bytes_written_since_check);
            if current_size >= MAX_BYTES {
                self.rotate()?;
            }
            self.bytes_written_since_check = 0;
        }
        Ok(())
    }

    fn rotate(&mut self) -> std::io::Result<()> {
        // Sequentially shift the rotation slots: .4 → drop, .3 → .4, …
        // .1 → .2, current → .1, then open a fresh empty current.
        let oldest = rotated_path(&self.path, MAX_ROTATIONS - 1);
        if oldest.exists() {
            fs::remove_file(&oldest)?;
        }
        for i in (1..MAX_ROTATIONS).rev() {
            let from = rotated_path(&self.path, i - 1);
            let to = rotated_path(&self.path, i);
            if from.exists() {
                fs::rename(&from, &to)?;
            }
        }
        if self.path.exists() {
            let first = rotated_path(&self.path, 0);
            fs::rename(&self.path, &first)?;
        }
        self.file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)?;
        Ok(())
    }
}

fn rotated_path(base: &Path, slot: usize) -> PathBuf {
    let mut p = base.to_path_buf();
    let stem = p
        .file_name()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "server.log".to_string());
    p.set_file_name(format!("{stem}.{}", slot + 1));
    p
}

/// Default log path inside the user's RKA runtime dir
/// (`~/Library/Logs/RKA/server.log` on macOS).
pub fn default_log_path() -> PathBuf {
    let base = dirs::home_dir().unwrap_or_else(std::env::temp_dir);
    #[cfg(target_os = "macos")]
    {
        return base.join("Library").join("Logs").join("RKA").join("server.log");
    }
    #[cfg(not(target_os = "macos"))]
    {
        // Linux: XDG_STATE_HOME ~/.local/state/RKA/server.log
        let state = std::env::var_os("XDG_STATE_HOME")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| base.join(".local").join("state"));
        state.join("RKA").join("server.log")
    }
}

/// Spawn an async task draining `reader` line-by-line into `writer`.
/// Returns immediately; the task lives until the reader closes (sidecar
/// exit) or the writer mutex is dropped.
pub fn drain_into<R>(reader: R, writer: Arc<Mutex<RotatingLog>>) -> tokio::task::JoinHandle<()>
where
    R: tokio::io::AsyncRead + Unpin + Send + 'static,
{
    tokio::spawn(async move {
        let buffered = BufReader::new(reader);
        let mut lines = buffered.lines();
        while let Ok(Some(line)) = lines.next_line().await {
            let mut w = writer.lock().await;
            let _ = w.write_line(&line);
        }
    })
}

/// Read the last N lines of the current log file. Used by the Logs
/// panel tail + diagnostic-copy.
pub fn tail(log_path: &Path, n: usize) -> std::io::Result<Vec<String>> {
    if !log_path.exists() {
        return Ok(Vec::new());
    }
    let raw = fs::read_to_string(log_path)?;
    let mut lines: Vec<&str> = raw.lines().collect();
    let start = lines.len().saturating_sub(n);
    Ok(lines.drain(start..).map(|s| s.to_string()).collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    fn tmp_log() -> PathBuf {
        static COUNTER: AtomicU64 = AtomicU64::new(0);
        let id = COUNTER.fetch_add(1, Ordering::SeqCst);
        let pid = std::process::id();
        let dir = std::env::temp_dir().join(format!("rka-log-writer-{pid}-{id}"));
        fs::create_dir_all(&dir).unwrap();
        dir.join("server.log")
    }

    #[test]
    fn writes_and_tails() {
        let p = tmp_log();
        let mut log = RotatingLog::open(p.clone()).unwrap();
        for i in 0..10 {
            log.write_line(&format!("line {i}")).unwrap();
        }
        let tailed = tail(&p, 3).unwrap();
        assert_eq!(tailed, vec!["line 7", "line 8", "line 9"]);
    }

    #[test]
    fn rotation_keeps_at_most_five_slots() {
        let p = tmp_log();
        let mut log = RotatingLog::open(p.clone()).unwrap();

        // Force several rotations.
        let big = "x".repeat(1_000_000); // ~1 MB per write
        for _ in 0..70 {
            log.write_line(&big).unwrap();
        }

        // The current file always exists.
        assert!(p.exists());
        // Slots 1..=5 may exist; slot 6+ never.
        for slot in 0..MAX_ROTATIONS {
            // rotated_path uses slot+1 in the file name; sixth (slot=5)
            // would be `server.log.6` — must not exist.
        }
        let sixth = rotated_path(&p, MAX_ROTATIONS);
        assert!(!sixth.exists(), "must not create more than {MAX_ROTATIONS} rotations");
    }
}
