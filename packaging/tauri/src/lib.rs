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

use tauri::{Emitter, Manager, RunEvent, WindowEvent};
use tokio::sync::Mutex;

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
        ])
        .setup(move |app| {
            let handle = app.handle().clone();
            let sidecar_clone = sidecar.clone();

            // Best-effort: rewrite the stable launcher to point at this app's
            // current bundle. Skipping is non-fatal — D4 surfaces a recovery
            // action via the "Re-register MCP" button.
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
