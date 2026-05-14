//! RKA desktop shell — Tauri + Python sidecar.
//!
//! Lifecycle:
//!   1. Single-instance lock acquired via `tauri-plugin-single-instance`.
//!   2. Stable launcher script written to
//!      `~/Library/Application Support/RKA/bin/rka-mcp.sh` (macOS) so MCP
//!      clients can reference a path that survives app moves.
//!   3. PyInstaller-bundled `rka-serve` spawned with `Stdio::piped()`; PID
//!      recorded under `~/Library/Application Support/RKA/runtime/server.pid`.
//!   4. Health-check task polls `http://127.0.0.1:9712/api/health` every 5 s;
//!      three consecutive failures trigger an auto-restart and a
//!      `sidecar-unhealthy` event surfaced to the UI.
//!   5. On `WindowEvent::CloseRequested`: SIGTERM the sidecar, wait 2 s,
//!      then SIGKILL if still alive.

mod launcher;
mod mcp_clients;
mod sidecar;

use std::sync::Arc;

use serde::{Deserialize, Serialize};
use tauri::{Emitter, Manager, RunEvent, WindowEvent};
use tokio::sync::Mutex;

use mcp_clients::{
    find_client, registry, unique_write_targets, ConfigFormat, MergeResult, ProbeResult,
    RemoveResult, VerifyResult,
};
use sidecar::SidecarManager;

pub struct AppState {
    pub sidecar: Arc<Mutex<SidecarManager>>,
}

/// Returns the directory under the user's home that RKA owns at runtime.
/// macOS:   `~/Library/Application Support/RKA/`
/// Linux:   `~/.local/share/RKA/`
/// Windows: `%APPDATA%\RKA\`
pub fn rka_runtime_dir() -> std::path::PathBuf {
    let base = dirs::data_dir().unwrap_or_else(|| std::env::temp_dir());
    base.join("RKA")
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClientSummary {
    pub id: String,
    pub display_name: String,
    pub format: String,
    pub detection: ProbeResult,
    pub config_path: Option<String>,
}

#[tauri::command]
async fn get_backend_url(_state: tauri::State<'_, AppState>) -> Result<String, String> {
    Ok("http://127.0.0.1:9712".to_string())
}

#[tauri::command]
async fn sidecar_status(state: tauri::State<'_, AppState>) -> Result<serde_json::Value, String> {
    let mgr = state.sidecar.lock().await;
    Ok(serde_json::json!({
        "running": mgr.is_running(),
        "pid": mgr.pid(),
        "consecutive_failures": mgr.consecutive_failures(),
    }))
}

#[tauri::command]
async fn restart_sidecar(
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let mut mgr = state.sidecar.lock().await;
    mgr.restart(&app).await.map_err(|e| e.to_string())
}

/// List the seven supported clients with their detection state.
#[tauri::command]
async fn list_mcp_clients() -> Result<Vec<ClientSummary>, String> {
    Ok(registry()
        .into_iter()
        .map(|c| ClientSummary {
            id: c.id().to_string(),
            display_name: c.display_name().to_string(),
            format: match c.config_format() {
                ConfigFormat::Json => "json".to_string(),
                ConfigFormat::Toml => "toml".to_string(),
            },
            detection: c.detect(),
            config_path: c.config_path().map(|p| p.display().to_string()),
        })
        .collect())
}

/// Merge the `rka` entry into a single client's config.
#[tauri::command]
async fn merge_mcp_client(id: String) -> Result<MergeResult, String> {
    let client = find_client(&id).ok_or_else(|| format!("unknown client: {id}"))?;
    let launcher = mcp_clients::stable_launcher_path();
    client
        .read_merge_write_rka(&launcher)
        .map_err(|e| e.to_string())
}

/// Merge across a list of selected clients, dedup-ing Codex CLI + Mac App
/// to a single write target.
#[derive(Debug, Clone, Serialize)]
struct MergeSummary {
    client_id: String,
    result: Option<MergeResult>,
    error: Option<String>,
}

#[tauri::command]
async fn merge_mcp_clients(ids: Vec<String>) -> Result<Vec<MergeSummary>, String> {
    let deduped = unique_write_targets(&ids);
    let launcher = mcp_clients::stable_launcher_path();
    Ok(deduped
        .into_iter()
        .map(|id| {
            let client = find_client(&id);
            match client {
                Some(c) => match c.read_merge_write_rka(&launcher) {
                    Ok(result) => MergeSummary {
                        client_id: id,
                        result: Some(result),
                        error: None,
                    },
                    Err(e) => MergeSummary {
                        client_id: id,
                        result: None,
                        error: Some(e.to_string()),
                    },
                },
                None => MergeSummary {
                    client_id: id,
                    result: None,
                    error: Some("unknown client".into()),
                },
            }
        })
        .collect())
}

#[tauri::command]
async fn remove_mcp_client(id: String) -> Result<RemoveResult, String> {
    let client = find_client(&id).ok_or_else(|| format!("unknown client: {id}"))?;
    client.remove_rka().map_err(|e| e.to_string())
}

#[tauri::command]
async fn verify_mcp_client(id: String) -> Result<VerifyResult, String> {
    let client = find_client(&id).ok_or_else(|| format!("unknown client: {id}"))?;
    Ok(client.verify("http://127.0.0.1:9712"))
}

#[tauri::command]
async fn verify_all_mcp_clients(ids: Vec<String>) -> Result<Vec<(String, VerifyResult)>, String> {
    let backend = "http://127.0.0.1:9712";
    Ok(ids
        .into_iter()
        .filter_map(|id| find_client(&id).map(|c| (id, c.verify(backend))))
        .collect())
}

/// Force-rewrite the stable launcher script (Settings tab "Re-register MCP"
/// recovery path).
#[tauri::command]
async fn rewrite_launcher(app: tauri::AppHandle) -> Result<String, String> {
    let path = launcher::write_stable_launcher(&app).map_err(|e| e.to_string())?;
    Ok(path.display().to_string())
}

/// Reveal a file in macOS Finder (or open its containing dir on other
/// platforms). Used by the Settings tab's per-client "Show in Finder"
/// button and the global "Show all MCP config files" action.
#[tauri::command]
async fn show_path_in_finder(path: String) -> Result<(), String> {
    let target = std::path::PathBuf::from(&path);
    if !target.exists() {
        return Err(format!("path does not exist: {path}"));
    }
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg("-R")
            .arg(&target)
            .spawn()
            .map_err(|e| e.to_string())?;
        return Ok(());
    }
    #[cfg(not(target_os = "macos"))]
    {
        let parent = target.parent().unwrap_or(std::path::Path::new("."));
        opener::open(parent).map_err(|e| e.to_string())?;
        Ok(())
    }
}

/// Open a URL in the user's default browser. Used by D9 Claude Desktop
/// install-assist's "Open download page" button.
#[tauri::command]
async fn open_external_url(url: String) -> Result<(), String> {
    if !url.starts_with("http://") && !url.starts_with("https://") {
        return Err(format!("refusing non-http(s) URL: {url}"));
    }
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(&url)
            .spawn()
            .map_err(|e| e.to_string())?;
        return Ok(());
    }
    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(&url)
            .spawn()
            .map_err(|e| e.to_string())?;
        Ok(())
    }
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("cmd")
            .args(["/C", "start", "", &url])
            .spawn()
            .map_err(|e| e.to_string())?;
        Ok(())
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let runtime_dir = rka_runtime_dir();
    std::fs::create_dir_all(runtime_dir.join("bin")).ok();
    std::fs::create_dir_all(runtime_dir.join("runtime")).ok();
    std::fs::create_dir_all(runtime_dir.join("logs")).ok();

    let sidecar = Arc::new(Mutex::new(SidecarManager::new(runtime_dir.clone())));
    let state = AppState {
        sidecar: sidecar.clone(),
    };

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(
            |app, _argv, _cwd| {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                    let _ = window.unminimize();
                }
            },
        ))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_opener::init())
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            get_backend_url,
            sidecar_status,
            restart_sidecar,
            list_mcp_clients,
            merge_mcp_client,
            merge_mcp_clients,
            remove_mcp_client,
            verify_mcp_client,
            verify_all_mcp_clients,
            rewrite_launcher,
            show_path_in_finder,
            open_external_url,
        ])
        .setup(move |app| {
            let handle = app.handle().clone();
            let sidecar_clone = sidecar.clone();

            if let Err(err) = launcher::write_stable_launcher(&handle) {
                log::warn!("Failed to write stable launcher: {err}");
            }

            tauri::async_runtime::spawn(async move {
                let mut mgr = sidecar_clone.lock().await;
                if let Err(err) = mgr.start(&handle).await {
                    log::error!("Failed to start sidecar: {err}");
                    let _ = handle.emit("sidecar-failed", err.to_string());
                }
            });

            let handle_for_loop = app.handle().clone();
            let sidecar_for_loop = sidecar.clone();
            tauri::async_runtime::spawn(async move {
                sidecar::health_check_loop(handle_for_loop, sidecar_for_loop).await;
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    let shutdown_state = app.state::<AppState>();
    let shutdown_sidecar = shutdown_state.sidecar.clone();

    app.run(move |_app_handle, event| {
        if let RunEvent::WindowEvent {
            event: WindowEvent::CloseRequested { .. },
            ..
        } = event
        {
            let sidecar_clone = shutdown_sidecar.clone();
            tauri::async_runtime::block_on(async move {
                let mut mgr = sidecar_clone.lock().await;
                if let Err(err) = mgr.shutdown().await {
                    log::error!("Sidecar shutdown error: {err}");
                }
            });
        }
    });
}
