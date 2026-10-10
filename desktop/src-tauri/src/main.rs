// Sunak desktop: a window around the normal Sunak server.
// It starts `sunak` (or `python -m sunak`) on a local port, shows the web interface and stops the server again
// when the app closes. A Sunak that already runs (autostart, browser) is used as it is and left running.
// Python is not bundled; Sunak must be installed.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{Manager, RunEvent, WindowEvent};

/// The app owns the server it started; a Sunak that was already running is only borrowed.
struct Server {
    child: Mutex<Option<Child>>,
    port: Mutex<u16>,
    owned: Mutex<bool>,
}

struct Launcher {
    program: String,
    pre: Vec<String>,
    pythonpath: Option<PathBuf>,
}

fn user_home() -> PathBuf {
    PathBuf::from(std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" }).unwrap_or_default())
}

/// Where the installers put Sunak (`SUNAK_HOME`, else %LOCALAPPDATA%\sunak or ~/.sunak).
fn sunak_home() -> PathBuf {
    if let Some(h) = std::env::var_os("SUNAK_HOME") {
        return PathBuf::from(h);
    }
    if cfg!(windows) {
        if let Some(l) = std::env::var_os("LOCALAPPDATA") {
            return PathBuf::from(l).join("sunak");
        }
    }
    user_home().join(".sunak")
}

/// Launchers to try, in order. A GUI app has a minimal PATH, so the installed launcher comes by absolute path first;
/// the Python fallbacks get PYTHONPATH pointing at the installed copy.
fn launchers() -> Vec<Launcher> {
    let home = sunak_home();
    let script = if cfg!(windows) { home.join("sunak.cmd") } else { user_home().join(".local").join("bin").join("sunak") };
    let app = home.join("app");
    let pythonpath = if app.exists() { Some(app) } else { None };
    let mut v = Vec::new();
    if script.exists() {
        v.push(Launcher { program: script.to_string_lossy().into_owned(), pre: vec![], pythonpath: None });
    }
    v.push(Launcher { program: "sunak".into(), pre: vec![], pythonpath: None });
    let m = || vec!["-m".to_string(), "sunak".to_string()];
    v.push(Launcher { program: "python3".into(), pre: m(), pythonpath: pythonpath.clone() });
    v.push(Launcher { program: "python".into(), pre: m(), pythonpath: pythonpath.clone() });
    if cfg!(windows) {
        v.push(Launcher { program: "py".into(), pre: vec!["-3".into(), "-m".into(), "sunak".into()], pythonpath });
    }
    v
}

fn command(l: &Launcher) -> Command {
    let mut c = Command::new(&l.program);
    c.args(&l.pre);
    if let Some(p) = &l.pythonpath {
        let mut path = p.clone().into_os_string();
        if let Some(old) = std::env::var_os("PYTHONPATH") {
            path.push(if cfg!(windows) { ";" } else { ":" });
            path.push(old);
        }
        c.env("PYTHONPATH", path);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        c.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    c.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    c
}

/// A fixed port keeps the address (and with it the browser storage of the window: theme, language, drafts) the same
/// at every start. Another port only when this one is taken.
fn preferred_port() -> u16 {
    for base in (17000u16..17100).step_by(10) {
        if (base..base + 10).all(|p| TcpListener::bind(("127.0.0.1", p)).is_ok()) {
            return base;
        }
    }
    TcpListener::bind("127.0.0.1:0").ok().and_then(|l| l.local_addr().ok()).map_or(17000, |a| a.port())
}

fn http(port: u16, method: &str, path: &str) -> Option<String> {
    let addr: SocketAddr = ([127, 0, 0, 1], port).into();
    let mut s = TcpStream::connect_timeout(&addr, Duration::from_millis(500)).ok()?;
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

fn is_sunak(port: u16) -> bool {
    http(port, "GET", "/api/status").map_or(false, |r| r.to_lowercase().contains("server: sunak/") && r.contains(" 200 "))
}

/// A Sunak that already runs on one of the usual ports 7000-7009.
fn running_sunak() -> Option<u16> {
    (7000u16..7010).find(|p| is_sunak(*p))
}

/// True while the child process still runs.
fn alive(child: &mut Option<Child>) -> bool {
    match child {
        Some(c) => matches!(c.try_wait(), Ok(None)),
        None => false,
    }
}

enum Wait {
    Ready(u16),
    Exited,
    Timeout,
}

/// Waits until our child answers. Sunak moves up to 9 ports on when its port is busy, so all of them are looked at.
fn wait_ready(state: &Server, first: u16, limit: Duration) -> Wait {
    let t0 = Instant::now();
    while t0.elapsed() < limit {
        if !alive(&mut state.child.lock().unwrap()) {
            return Wait::Exited;
        }
        if let Some(p) = (first..first + 10).find(|p| is_sunak(*p)) {
            return Wait::Ready(p);
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    Wait::Timeout
}

fn kill_child(state: &Server) {
    if let Some(mut c) = state.child.lock().unwrap().take() {
        let _ = c.kill();
        let _ = c.wait();
    }
}

/// Stops the server we started. The clean way is the HTTP call: with a .cmd launcher, kill() would only end cmd.
fn stop_server(state: &Server) {
    if !*state.owned.lock().unwrap() {
        return; // somebody else's Sunak keeps running
    }
    let port = *state.port.lock().unwrap();
    if port != 0 {
        let _ = http(port, "POST", "/api/shutdown");
    }
    let t0 = Instant::now();
    while t0.elapsed() < Duration::from_secs(5) {
        {
            let mut guard = state.child.lock().unwrap();
            if !alive(&mut guard) {
                guard.take();
                return;
            }
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    kill_child(state);
}

fn start(handle: &tauri::AppHandle, win: &tauri::WebviewWindow) {
    let state = handle.state::<Server>();
    let go = |port: u16| {
        *state.port.lock().unwrap() = port;
        if let Ok(url) = format!("http://127.0.0.1:{port}/").parse() {
            let _ = win.navigate(url);
        }
    };
    if let Some(p) = running_sunak() {
        *state.owned.lock().unwrap() = false;
        return go(p);
    }
    *state.owned.lock().unwrap() = true;
    let first = preferred_port();
    let mut spawned = false;
    for l in launchers() {
        let mut c = command(&l);
        c.args(["--no-browser", "--port", &first.to_string(), "--host", "127.0.0.1"]);
        let Ok(child) = c.spawn() else { continue };
        spawned = true;
        *state.child.lock().unwrap() = Some(child); // stored at once, so a closing window never leaves an orphan
        match wait_ready(&state, first, Duration::from_secs(40)) {
            Wait::Ready(p) => return go(p),
            Wait::Exited => {
                kill_child(&state);
                continue; // this launcher did not work (not found, broken); try the next
            }
            Wait::Timeout => {
                kill_child(&state);
                return fail(win, "timeout");
            }
        }
    }
    fail(win, if spawned { "timeout" } else { "missing" });
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .manage(Server { child: Mutex::new(None), port: Mutex::new(0), owned: Mutex::new(false) })
        .setup(|app| {
            let win = app.get_webview_window("main").expect("main window");
            let handle = app.handle().clone();
            std::thread::spawn(move || start(&handle, &win));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Sunak desktop");

    app.run(|handle, event| match event {
        // closing the window ends the app on every system (macOS would otherwise keep it, and the server, running)
        RunEvent::WindowEvent { event: WindowEvent::CloseRequested { .. }, .. } => handle.exit(0),
        RunEvent::Exit => stop_server(&handle.state::<Server>()),
        _ => {}
    });
}

fn fail(win: &tauri::WebviewWindow, kind: &str) {
    let _ = win.eval(&format!("showError('{kind}')"));
}
