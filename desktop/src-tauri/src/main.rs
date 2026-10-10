// Sunak desktop: a window around the normal Sunak server.
// It starts `sunak` (or `python -m sunak`) on a free local port, shows the web interface and stops
// the server again when the window closes. Python is not bundled; Sunak must be installed.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{Manager, RunEvent};

struct Server {
    child: Mutex<Option<Child>>,
    port: Mutex<u16>,
}

fn command(program: &str, pre: &[&str]) -> Command {
    let mut c = Command::new(program);
    c.args(pre);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        c.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    c.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    c
}

/// Launchers to try, in order: the `sunak` command, then Python with the sunak module.
fn launchers() -> Vec<(&'static str, Vec<&'static str>)> {
    let mut v = vec![("sunak", vec![]), ("python3", vec!["-m", "sunak"]), ("python", vec!["-m", "sunak"])];
    if cfg!(windows) {
        v.push(("py", vec!["-3", "-m", "sunak"]));
    }
    v
}

fn free_port() -> Option<u16> {
    TcpListener::bind("127.0.0.1:0").ok()?.local_addr().ok().map(|a| a.port())
}

/// Spawn Sunak; the first launcher that starts and does not exit right away wins.
fn start_server(port: u16) -> Option<Child> {
    let p = port.to_string();
    for (prog, pre) in launchers() {
        let mut c = command(prog, &pre);
        c.args(["--no-browser", "--port", &p, "--host", "127.0.0.1"]);
        if let Ok(mut child) = c.spawn() {
            std::thread::sleep(Duration::from_millis(700));
            if matches!(child.try_wait(), Ok(None)) {
                return Some(child);
            }
        }
    }
    None
}

fn http(port: u16, method: &str, path: &str) -> Option<String> {
    let addr: SocketAddr = ([127, 0, 0, 1], port).into();
    let mut s = TcpStream::connect_timeout(&addr, Duration::from_millis(800)).ok()?;
    s.set_read_timeout(Some(Duration::from_secs(2))).ok()?;
    let body = if method == "POST" { "{}" } else { "" };
    let req = format!(
        "{method} {path} HTTP/1.0\r\nHost: 127.0.0.1\r\nX-Requested-With: sunak\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{body}",
        body.len()
    );
    s.write_all(req.as_bytes()).ok()?;
    let mut out = String::new();
    s.read_to_string(&mut out).ok()?;
    Some(out)
}

fn wait_ready(port: u16, child: &mut Child, limit: Duration) -> bool {
    let t0 = Instant::now();
    while t0.elapsed() < limit {
        if !matches!(child.try_wait(), Ok(None)) {
            return false; // server exited (e.g. port taken, broken install)
        }
        if http(port, "GET", "/api/status").map_or(false, |r| r.contains("Sunak/") && r.contains(" 200 ")) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    false
}

fn stop_server(state: &Server) {
    let port = *state.port.lock().unwrap();
    if port != 0 {
        let _ = http(port, "POST", "/api/shutdown"); // clean stop first
    }
    if let Some(mut child) = state.child.lock().unwrap().take() {
        let t0 = Instant::now();
        while t0.elapsed() < Duration::from_secs(3) {
            if !matches!(child.try_wait(), Ok(None)) {
                return;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .manage(Server { child: Mutex::new(None), port: Mutex::new(0) })
        .setup(|app| {
            let win = app.get_webview_window("main").expect("main window");
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let state = handle.state::<Server>();
                let port = match free_port() {
                    Some(p) => p,
                    None => return fail(&win, "timeout"),
                };
                let mut child = match start_server(port) {
                    Some(c) => c,
                    None => return fail(&win, "missing"),
                };
                if !wait_ready(port, &mut child, Duration::from_secs(40)) {
                    let _ = child.kill();
                    let _ = child.wait();
                    return fail(&win, "timeout");
                }
                *state.port.lock().unwrap() = port;
                *state.child.lock().unwrap() = Some(child);
                if let Ok(url) = format!("http://127.0.0.1:{port}/").parse() {
                    let _ = win.navigate(url);
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Sunak desktop");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            stop_server(&handle.state::<Server>());
        }
    });
}

fn fail(win: &tauri::WebviewWindow, kind: &str) {
    let _ = win.eval(&format!("showError('{kind}')"));
}
