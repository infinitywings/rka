//! Sidecar process lifecycle for the bundled `rka-serve` binary.
//!
//! Responsibilities:
//!   - Locate the bundled binary inside the app's resource directory.
//!   - Spawn it with stdio piped; record PID to disk so a later launch
//!     can clean up an orphaned process from a crashed prior session.
//!   - Provide graceful shutdown (SIGTERM → 2 s grace → SIGKILL).
//!   - Run a periodic health check; emit `sidecar-unhealthy` after three
//!     consecutive failures and attempt a restart.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use serde_json::json;
use tauri::{AppHandle, Emitter, Manager};
use tokio::process::{Child, Command};
use tokio::sync::Mutex;
use tokio::time::sleep;

const HEALTH_URL: &str = "http://127.0.0.1:9712/api/health";
const HEALTH_INTERVAL: Duration = Duration::from_secs(5);
const HEALTH_FAILURE_THRESHOLD: u32 = 3;
const SIDECAR_BINARY: &str = "rka-serve";

pub struct SidecarManager {
    runtime_dir: PathBuf,
    child: Option<Child>,
    consecutive_failures: u32,
    last_known_pid: Option<u32>,
}

impl SidecarManager {
    pub fn new(runtime_dir: PathBuf) -> Self {
        Self {
            runtime_dir,
            child: None,
            consecutive_failures: 0,
            last_known_pid: None,
        }
    }

    pub fn is_running(&self) -> bool {
        self.last_known_pid.is_some()
    }

    pub fn pid(&self) -> Option<u32> {
        self.last_known_pid
    }

    pub fn consecutive_failures(&self) -> u32 {
        self.consecutive_failures
    }

    fn pid_file(&self) -> PathBuf {
        self.runtime_dir.join("runtime").join("server.pid")
    }

    /// Look for a leftover PID from a prior crashed launch and kill it.
    fn reap_orphan(&self) {
        let pid_path = self.pid_file();
        let Ok(contents) = std::fs::read_to_string(&pid_path) else {
            return;
        };
        let Ok(pid) = contents.trim().parse::<u32>() else {
            return;
        };
        #[cfg(unix)]
        {
            use nix::sys::signal::{kill, Signal};
            use nix::unistd::Pid;
            let _ = kill(Pid::from_raw(pid as i32), Signal::SIGTERM);
        }
        let _ = std::fs::remove_file(&pid_path);
        log::info!("Reaped orphan sidecar pid={pid}");
    }

    fn resolve_binary_path(&self, app: &AppHandle) -> Result<PathBuf> {
        let resource_dir = app
            .path()
            .resource_dir()
            .context("resource_dir unavailable")?;
        let candidate = resource_dir.join(SIDECAR_BINARY);
        if candidate.exists() {
            return Ok(candidate);
        }
        // Development fallback: project-relative dist/ from a pyinstaller build.
        let dev_candidate = std::env::current_dir()
            .ok()
            .map(|p| p.join("packaging/pyinstaller/dist").join(SIDECAR_BINARY))
            .filter(|p| p.exists());
        if let Some(path) = dev_candidate {
            return Ok(path);
        }
        Err(anyhow!(
            "rka-serve binary not found under resource dir or dev dist/ path"
        ))
    }

    pub async fn start(&mut self, app: &AppHandle) -> Result<()> {
        self.reap_orphan();
        let binary = self.resolve_binary_path(app)?;
        let log_dir = self.runtime_dir.join("logs");
        std::fs::create_dir_all(&log_dir).ok();

        let mut cmd = Command::new(&binary);
        cmd.env("RKA_PROJECT_DIR", &self.runtime_dir);
        cmd.env("RKA_DB_PATH", "rka.db");
        cmd.kill_on_drop(true);

        let child = cmd
            .spawn()
            .with_context(|| format!("failed to spawn sidecar {binary:?}"))?;

        let pid = child
            .id()
            .ok_or_else(|| anyhow!("sidecar spawned without a PID"))?;
        std::fs::write(self.pid_file(), pid.to_string()).ok();
        self.last_known_pid = Some(pid);
        self.child = Some(child);
        self.consecutive_failures = 0;

        log::info!("Sidecar spawned pid={pid} binary={binary:?}");
        let _ = app.emit("sidecar-started", json!({"pid": pid}));
        Ok(())
    }

    pub async fn shutdown(&mut self) -> Result<()> {
        let Some(child) = self.child.as_mut() else {
            return Ok(());
        };
        let pid = child.id();

        #[cfg(unix)]
        if let Some(pid) = pid {
            use nix::sys::signal::{kill, Signal};
            use nix::unistd::Pid;
            let _ = kill(Pid::from_raw(pid as i32), Signal::SIGTERM);
        }

        // Wait up to 2 s for graceful exit.
        let exited = tokio::select! {
            _ = child.wait() => true,
            _ = sleep(Duration::from_secs(2)) => false,
        };

        if !exited {
            let _ = child.kill().await;
            log::warn!("Sidecar did not exit on SIGTERM; SIGKILL issued");
        }

        let _ = std::fs::remove_file(self.pid_file());
        self.child = None;
        self.last_known_pid = None;
        log::info!("Sidecar shutdown complete (pid={pid:?})");
        Ok(())
    }

    pub async fn restart(&mut self, app: &AppHandle) -> Result<()> {
        self.shutdown().await?;
        self.start(app).await
    }

    fn note_health_success(&mut self) {
        self.consecutive_failures = 0;
    }

    fn note_health_failure(&mut self) {
        self.consecutive_failures = self.consecutive_failures.saturating_add(1);
    }
}

async fn probe_health() -> bool {
    let client = match reqwest_minimal::get(HEALTH_URL).await {
        Ok(ok) => ok,
        Err(_) => return false,
    };
    client
}

mod reqwest_minimal {
    use std::io::{Read, Write};
    use std::net::TcpStream;
    use std::time::Duration;

    /// Tiny synchronous HTTP/1.1 GET for localhost — keeps the crate set lean.
    /// Returns `true` only on a 2xx status.
    pub async fn get(url: &str) -> Result<bool, std::io::Error> {
        // Run the blocking I/O off the executor thread.
        let url = url.to_string();
        tokio::task::spawn_blocking(move || blocking_get(&url))
            .await
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?
    }

    fn blocking_get(url: &str) -> Result<bool, std::io::Error> {
        let stripped = url
            .strip_prefix("http://")
            .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::InvalidInput, "scheme"))?;
        let (host_port, path) = stripped.split_once('/').unwrap_or((stripped, ""));
        let path = format!("/{path}");

        let mut stream = TcpStream::connect(host_port)?;
        stream.set_read_timeout(Some(Duration::from_secs(2)))?;
        stream.set_write_timeout(Some(Duration::from_secs(2)))?;

        let req = format!(
            "GET {path} HTTP/1.1\r\nHost: {host_port}\r\nConnection: close\r\nUser-Agent: rka-desktop/0.1\r\n\r\n"
        );
        stream.write_all(req.as_bytes())?;

        let mut buf = Vec::with_capacity(512);
        let mut chunk = [0u8; 512];
        loop {
            match stream.read(&mut chunk) {
                Ok(0) => break,
                Ok(n) => {
                    buf.extend_from_slice(&chunk[..n]);
                    if buf.len() >= 16 {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
        let head = String::from_utf8_lossy(&buf);
        Ok(head.starts_with("HTTP/1.1 2") || head.starts_with("HTTP/1.0 2"))
    }
}

pub async fn health_check_loop(app: AppHandle, sidecar: Arc<Mutex<SidecarManager>>) {
    loop {
        sleep(HEALTH_INTERVAL).await;
        let ok = probe_health().await;
        let mut mgr = sidecar.lock().await;
        if ok {
            mgr.note_health_success();
            continue;
        }
        mgr.note_health_failure();
        let failures = mgr.consecutive_failures();
        log::warn!("Health check failure ({failures}/{HEALTH_FAILURE_THRESHOLD})");
        if failures >= HEALTH_FAILURE_THRESHOLD {
            log::error!("Sidecar unhealthy after {failures} consecutive checks; restarting");
            let _ = app.emit("sidecar-unhealthy", json!({"failures": failures}));
            if let Err(err) = mgr.restart(&app).await {
                log::error!("Auto-restart failed: {err}");
                let _ = app.emit("sidecar-restart-failed", err.to_string());
            }
        }
    }
}
