#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    sync::{Arc, Mutex},
    thread,
    time::Duration,
};

use tauri::{Manager, RunEvent, State, WindowEvent};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

#[derive(Clone, Default)]
struct BackendState {
    backend_url: Arc<Mutex<Option<String>>>,
    child: Arc<Mutex<Option<CommandChild>>>,
}

impl BackendState {
    fn set_url(&self, url: String) {
        *self.backend_url.lock().expect("backend url lock poisoned") = Some(url);
    }

    fn get_url(&self) -> Option<String> {
        self.backend_url
            .lock()
            .expect("backend url lock poisoned")
            .clone()
    }

    fn set_child(&self, child: CommandChild) {
        *self.child.lock().expect("backend child lock poisoned") = Some(child);
    }

    fn kill_child(&self) {
        let mut guard = self.child.lock().expect("backend child lock poisoned");
        if let Some(child) = guard.take() {
            let _ = child.kill();
        }
    }
}

#[tauri::command]
fn get_backend_base_url(state: State<'_, BackendState>) -> Result<String, String> {
    for _ in 0..300 {
        if let Some(url) = state.get_url() {
            return Ok(url);
        }
        thread::sleep(Duration::from_millis(100));
    }
    Err("SuperCode backend did not become ready in time".to_string())
}

fn find_free_port() -> Result<u16, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|error| format!("failed to reserve local backend port: {error}"))?;
    listener
        .local_addr()
        .map(|addr| addr.port())
        .map_err(|error| format!("failed to read reserved local backend port: {error}"))
}

fn health_check(port: u16) -> bool {
    let address = format!("127.0.0.1:{port}");
    let Ok(mut stream) = TcpStream::connect_timeout(
        &address.parse().expect("valid loopback socket address"),
        Duration::from_millis(400),
    ) else {
        return false;
    };

    let request = b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    if stream.write_all(request).is_err() {
        return false;
    }

    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200")
}

fn wait_for_health(port: u16) -> bool {
    for _ in 0..60 {
        if health_check(port) {
            return true;
        }
        thread::sleep(Duration::from_millis(500));
    }
    false
}

fn start_backend(app: tauri::AppHandle, state: BackendState) -> Result<(), String> {
    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("failed to resolve app data directory: {error}"))?;
    std::fs::create_dir_all(&app_data_dir)
        .map_err(|error| format!("failed to create app data directory: {error}"))?;

    for attempt in 1..=3 {
        let port = find_free_port()?;
        let backend_url = format!("http://127.0.0.1:{port}");
        let state_dir = app_data_dir.to_string_lossy().to_string();
        let (mut events, child) = app
            .shell()
            .sidecar("supercode-backend")
            .map_err(|error| format!("failed to create backend sidecar command: {error}"))?
            .env("SUPERCODE_HOST", "127.0.0.1")
            .env("SUPERCODE_PORT", port.to_string())
            .env("SUPERCODE_STATE_DIR", state_dir)
            .env("SUPERCODE_PARENT_PID", std::process::id().to_string())
            .env("SUPERCODE_DESKTOP", "1")
            .spawn()
            .map_err(|error| format!("failed to spawn backend sidecar: {error}"))?;

        state.set_child(child);

        tauri::async_runtime::spawn(async move {
            while let Some(event) = events.recv().await {
                println!("[supercode-backend] {event:?}");
            }
        });

        if wait_for_health(port) {
            state.set_url(backend_url);
            return Ok(());
        }

        eprintln!("backend health check failed on attempt {attempt}; retrying");
        state.kill_child();
    }

    Err("backend failed health checks after 3 attempts".to_string())
}

fn main() {
    let backend_state = BackendState::default();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(backend_state.clone())
        .invoke_handler(tauri::generate_handler![get_backend_base_url])
        .setup(move |app| {
            let handle = app.handle().clone();
            let state = backend_state.clone();
            thread::spawn(move || {
                if let Err(error) = start_backend(handle, state.clone()) {
                    eprintln!("failed to start SuperCode backend: {error}");
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. }) {
                let state = window.state::<BackendState>();
                state.kill_child();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building SuperCode desktop shell")
        .run(|app_handle, event| {
            if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
                let state = app_handle.state::<BackendState>();
                state.kill_child();
            }
        });
}
