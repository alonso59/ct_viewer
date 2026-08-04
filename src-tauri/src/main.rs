#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    collections::HashMap,
    fs::{self, OpenOptions},
    io::{Read, Write},
    net::{Ipv4Addr, SocketAddr, SocketAddrV4, TcpStream},
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Condvar, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

use rand::{rngs::OsRng, RngCore};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, State, WindowEvent};
use tauri_plugin_dialog::{DialogExt, MessageDialogKind};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

const BACKEND_START_TIMEOUT: Duration = Duration::from_secs(60);
const BACKEND_STOP_TIMEOUT: Duration = Duration::from_secs(5);
const HEALTH_RETRY_INTERVAL: Duration = Duration::from_millis(100);

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct BackendRuntime {
    base_url: String,
    token: String,
}

#[derive(Debug, Deserialize)]
struct BackendHandshake {
    pid: u32,
    port: u16,
}

#[derive(Clone, Debug)]
enum RuntimeStatus {
    Pending,
    Ready(BackendRuntime),
    Failed(String),
}

struct SharedRuntime {
    status: Mutex<RuntimeStatus>,
    status_changed: Condvar,
    child: Mutex<Option<CommandChild>>,
    terminated: Mutex<bool>,
    terminated_changed: Condvar,
    runtime_path: PathBuf,
    log_path: PathBuf,
    shutdown_started: AtomicBool,
    failure_reported: AtomicBool,
}

impl SharedRuntime {
    fn new(runtime_path: PathBuf, log_path: PathBuf) -> Self {
        Self {
            status: Mutex::new(RuntimeStatus::Pending),
            status_changed: Condvar::new(),
            child: Mutex::new(None),
            terminated: Mutex::new(false),
            terminated_changed: Condvar::new(),
            runtime_path,
            log_path,
            shutdown_started: AtomicBool::new(false),
            failure_reported: AtomicBool::new(false),
        }
    }

    fn set_ready(&self, runtime: BackendRuntime) {
        let mut status = self
            .status
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        if matches!(*status, RuntimeStatus::Pending) {
            *status = RuntimeStatus::Ready(runtime);
            self.status_changed.notify_all();
        }
    }

    fn set_failed(&self, message: String) {
        let mut status = self
            .status
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        if matches!(*status, RuntimeStatus::Pending) {
            *status = RuntimeStatus::Failed(message);
            self.status_changed.notify_all();
        }
    }

    fn runtime_if_ready(&self) -> Option<BackendRuntime> {
        let status = self
            .status
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        match &*status {
            RuntimeStatus::Ready(runtime) => Some(runtime.clone()),
            _ => None,
        }
    }

    fn wait_until_ready(&self, timeout: Duration) -> Result<BackendRuntime, String> {
        let deadline = Instant::now() + timeout;
        let mut status = self
            .status
            .lock()
            .unwrap_or_else(|error| error.into_inner());

        loop {
            match &*status {
                RuntimeStatus::Ready(runtime) => return Ok(runtime.clone()),
                RuntimeStatus::Failed(message) => return Err(message.clone()),
                RuntimeStatus::Pending => {}
            }

            let now = Instant::now();
            if now >= deadline {
                return Err("The backend did not become ready within 60 seconds.".to_string());
            }
            let remaining = deadline.saturating_duration_since(now);
            let waited = self
                .status_changed
                .wait_timeout(status, remaining)
                .unwrap_or_else(|error| error.into_inner());
            status = waited.0;
            if waited.1.timed_out() {
                return Err("The backend did not become ready within 60 seconds.".to_string());
            }
        }
    }

    fn mark_terminated(&self) {
        {
            let mut terminated = self
                .terminated
                .lock()
                .unwrap_or_else(|error| error.into_inner());
            *terminated = true;
            self.terminated_changed.notify_all();
        }

        if !self.shutdown_started.load(Ordering::SeqCst) {
            self.set_failed("The backend process exited before startup completed.".to_string());
        }
    }

    fn wait_for_termination(&self, timeout: Duration) -> bool {
        let terminated = self
            .terminated
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        if *terminated {
            return true;
        }
        let result = self
            .terminated_changed
            .wait_timeout_while(terminated, timeout, |value| !*value)
            .unwrap_or_else(|error| error.into_inner());
        *result.0
    }
}

struct DesktopState(Arc<SharedRuntime>);

#[tauri::command]
async fn get_backend_runtime(state: State<'_, DesktopState>) -> Result<BackendRuntime, String> {
    let shared = state.0.clone();
    tauri::async_runtime::spawn_blocking(move || shared.wait_until_ready(BACKEND_START_TIMEOUT))
        .await
        .map_err(|error| format!("Backend readiness task failed: {error}"))?
}

#[tauri::command]
fn frontend_ready(app: AppHandle, state: State<'_, DesktopState>) -> Result<(), String> {
    if state.0.runtime_if_ready().is_none() {
        return Err("The backend is not ready.".to_string());
    }
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "The main window is unavailable.".to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())
}

#[tauri::command]
async fn browse_for_dataset_directory(app: AppHandle) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("Open Dataset")
            .blocking_pick_folder()
            .map(|path| {
                path.into_path()
                    .map(|value| value.to_string_lossy().into_owned())
                    .map_err(|error| error.to_string())
            })
            .transpose()
    })
    .await
    .map_err(|error| format!("Folder dialog task failed: {error}"))?
}

fn generate_runtime_token() -> String {
    let mut bytes = [0_u8; 32];
    OsRng.fill_bytes(&mut bytes);
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn append_desktop_log(path: &Path, message: &str) {
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(mut stream) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(stream, "{message}");
    }
}

fn report_startup_failure(app: &AppHandle, shared: &Arc<SharedRuntime>, message: String) {
    shared.set_failed(message.clone());
    append_desktop_log(&shared.log_path, &format!("desktop host: {message}"));
    if shared.failure_reported.swap(true, Ordering::SeqCst) {
        return;
    }

    let body = format!(
        "Radiology Desktop could not start its local backend.\n\n{message}\n\nLog: {}",
        shared.log_path.display()
    );
    let exit_handle = app.clone();
    let shutdown_state = shared.clone();
    app.dialog()
        .message(body)
        .title("Radiology Desktop startup error")
        .kind(MessageDialogKind::Error)
        .show(move |_| stop_backend(exit_handle, shutdown_state, 1));
}

fn read_handshake(path: &Path) -> Result<BackendHandshake, String> {
    let payload = fs::read_to_string(path).map_err(|error| error.to_string())?;
    let handshake: BackendHandshake =
        serde_json::from_str(&payload).map_err(|error| error.to_string())?;
    if handshake.pid == 0 || handshake.port == 0 {
        return Err("The backend handshake contained an invalid PID or port.".to_string());
    }
    Ok(handshake)
}

fn send_http_request(
    port: u16,
    method: &str,
    path: &str,
    token: Option<&str>,
    expected_body: Option<&str>,
) -> bool {
    let address = SocketAddr::V4(SocketAddrV4::new(Ipv4Addr::LOCALHOST, port));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_secs(1)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(1)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(1)));

    let authorization = token
        .map(|value| format!("Authorization: Bearer {value}\r\n"))
        .unwrap_or_default();
    let request = format!(
        "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n{authorization}Content-Length: 0\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }

    let mut response = Vec::with_capacity(512);
    if stream.take(4096).read_to_end(&mut response).is_err() {
        return false;
    }
    let response = String::from_utf8_lossy(&response);
    let successful = response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200");
    successful && expected_body.is_none_or(|expected| response.contains(expected))
}

fn wait_for_backend(app: AppHandle, shared: Arc<SharedRuntime>, token: String, expected_pid: u32) {
    let deadline = Instant::now() + BACKEND_START_TIMEOUT;
    let mut last_handshake_error = None;

    while Instant::now() < deadline {
        if shared.runtime_if_ready().is_some() {
            return;
        }
        if shared.terminated.lock().map(|value| *value).unwrap_or(true) {
            report_startup_failure(
                &app,
                &shared,
                "The backend process exited before it became ready.".to_string(),
            );
            return;
        }

        match read_handshake(&shared.runtime_path) {
            Ok(handshake) => {
                if handshake.pid != expected_pid {
                    last_handshake_error = Some(format!(
                        "The handshake PID {} did not match sidecar PID {expected_pid}.",
                        handshake.pid
                    ));
                    thread::sleep(HEALTH_RETRY_INTERVAL);
                    continue;
                }
                if send_http_request(
                    handshake.port,
                    "GET",
                    "/api/health",
                    None,
                    Some("\"status\":\"ok\""),
                ) {
                    shared.set_ready(BackendRuntime {
                        base_url: format!("http://127.0.0.1:{}", handshake.port),
                        token,
                    });
                    return;
                }
            }
            Err(error) => last_handshake_error = Some(error),
        }
        thread::sleep(HEALTH_RETRY_INTERVAL);
    }

    let detail = last_handshake_error
        .map(|error| format!(" Last handshake error: {error}"))
        .unwrap_or_default();
    report_startup_failure(
        &app,
        &shared,
        format!("The backend did not become healthy within 60 seconds.{detail}"),
    );
}

fn start_backend(app: &AppHandle, shared: Arc<SharedRuntime>) {
    let token = generate_runtime_token();
    let state_dir = app
        .path()
        .app_data_dir()
        .unwrap_or_else(|_| {
            shared
                .runtime_path
                .parent()
                .unwrap_or(Path::new("."))
                .to_path_buf()
        })
        .join("state");
    let _ = fs::create_dir_all(&state_dir);
    let _ = fs::remove_file(&shared.runtime_path);

    let mut environment = HashMap::new();
    environment.insert("RADIOLOGY_DESKTOP_RUNTIME", "true".to_string());
    environment.insert("RADIOLOGY_UI_TOKEN", token.clone());
    environment.insert(
        "RADIOLOGY_RUNTIME_FILE",
        shared.runtime_path.to_string_lossy().into_owned(),
    );
    environment.insert(
        "RADIOLOGY_LOG_FILE",
        shared.log_path.to_string_lossy().into_owned(),
    );
    environment.insert("RADIOLOGY_PARENT_PID", std::process::id().to_string());
    environment.insert("ALLOW_UNRESTRICTED_DATA_PATHS", "true".to_string());
    environment.insert("ALLOW_DATA_MUTATIONS", "false".to_string());
    environment.insert("WEBUI_STATE_DIR", state_dir.to_string_lossy().into_owned());
    environment.insert(
        "CORS_ORIGINS",
        "http://tauri.localhost,http://localhost:5173".to_string(),
    );
    environment.insert("PYTHONUNBUFFERED", "1".to_string());

    let sidecar = match app.shell().sidecar("radiology-backend") {
        Ok(command) => command.envs(environment),
        Err(error) => {
            report_startup_failure(
                app,
                &shared,
                format!("The backend sidecar could not be configured: {error}"),
            );
            return;
        }
    };

    let (mut receiver, child) = match sidecar.spawn() {
        Ok(result) => result,
        Err(error) => {
            report_startup_failure(
                app,
                &shared,
                format!("The backend sidecar could not be started: {error}"),
            );
            return;
        }
    };
    let expected_pid = child.pid();
    *shared
        .child
        .lock()
        .unwrap_or_else(|error| error.into_inner()) = Some(child);

    let monitor_app = app.clone();
    let monitor_state = shared.clone();
    let _monitor_task = tauri::async_runtime::spawn(async move {
        while let Some(event) = receiver.recv().await {
            match event {
                CommandEvent::Terminated(payload) => {
                    append_desktop_log(
                        &monitor_state.log_path,
                        &format!("desktop host: backend terminated: {payload:?}"),
                    );
                    monitor_state.mark_terminated();
                    if !monitor_state.shutdown_started.load(Ordering::SeqCst) {
                        report_startup_failure(
                            &monitor_app,
                            &monitor_state,
                            "The backend process stopped unexpectedly.".to_string(),
                        );
                    }
                    return;
                }
                CommandEvent::Error(message) => {
                    append_desktop_log(
                        &monitor_state.log_path,
                        &format!("desktop host: sidecar stream error: {message}"),
                    );
                }
                _ => {}
            }
        }
    });

    let readiness_app = app.clone();
    let _readiness_thread =
        thread::spawn(move || wait_for_backend(readiness_app, shared, token, expected_pid));
}

fn stop_backend(app: AppHandle, shared: Arc<SharedRuntime>, exit_code: i32) {
    if shared.shutdown_started.swap(true, Ordering::SeqCst) {
        return;
    }

    let _shutdown_thread = thread::spawn(move || {
        if let Some(runtime) = shared.runtime_if_ready() {
            let port = runtime
                .base_url
                .rsplit(':')
                .next()
                .and_then(|value| value.parse::<u16>().ok());
            if let Some(port) = port {
                let _ = send_http_request(
                    port,
                    "POST",
                    "/api/desktop/shutdown",
                    Some(&runtime.token),
                    None,
                );
            }
        }

        let child_to_kill = if shared.wait_for_termination(BACKEND_STOP_TIMEOUT) {
            None
        } else {
            shared
                .child
                .lock()
                .unwrap_or_else(|error| error.into_inner())
                .take()
        };
        if let Some(child) = child_to_kill {
            append_desktop_log(
                &shared.log_path,
                "desktop host: graceful shutdown timed out; terminating backend",
            );
            let _ = child.kill();
        }
        let _ = fs::remove_file(&shared.runtime_path);
        app.exit(exit_code);
    });
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            let runtime_ready = app
                .try_state::<DesktopState>()
                .and_then(|state| state.0.runtime_if_ready())
                .is_some();
            if let (true, Some(window)) = (runtime_ready, app.get_webview_window("main")) {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            get_backend_runtime,
            frontend_ready,
            browse_for_dataset_directory
        ])
        .setup(|app| {
            let app_data_dir = app.path().app_data_dir()?;
            let log_dir = app.path().app_log_dir()?;
            fs::create_dir_all(&app_data_dir)?;
            fs::create_dir_all(&log_dir)?;
            let shared = Arc::new(SharedRuntime::new(
                app_data_dir.join("backend-runtime.json"),
                log_dir.join("radiology-backend.log"),
            ));
            app.manage(DesktopState(shared.clone()));
            start_backend(app.handle(), shared);
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let state = window.state::<DesktopState>();
                stop_backend(window.app_handle().clone(), state.0.clone(), 0);
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Radiology Desktop");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_token_has_256_bits_encoded_as_hex() {
        let token = generate_runtime_token();
        assert_eq!(token.len(), 64);
        assert!(token.chars().all(|value| value.is_ascii_hexdigit()));
    }

    #[test]
    fn handshake_rejects_zero_pid_or_port() {
        let directory = std::env::temp_dir().join(format!(
            "radiology-desktop-test-{}",
            generate_runtime_token()
        ));
        fs::create_dir_all(&directory).unwrap();
        let path = directory.join("runtime.json");
        fs::write(&path, r#"{"pid":1,"port":0}"#).unwrap();
        assert!(read_handshake(&path).is_err());
        fs::remove_dir_all(directory).unwrap();
    }
}
