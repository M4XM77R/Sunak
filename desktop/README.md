# Sunak desktop (optional)

Sunak in its own window instead of the browser, built with [Tauri](https://tauri.app). It is a thin shell: it starts the normal Sunak server on a free local port (`sunak --no-browser --port N`), shows the unchanged interface and stops the server when you close the window. Your data stays in the usual Sunak folder, so the app and the browser version show the same chats.

**Sunak itself must be installed** (the one-line installer from the main README). Python is not bundled. If Sunak is missing the window says so. The app looks for the `sunak` command, then `python3 -m sunak`, `python -m sunak` (and `py -3` on Windows).

The normal installation does not change and needs no Rust. Only building the app yourself does.

## Get it

Packages for Windows (`.msi`/`.exe`), macOS (`.dmg`) and Linux (`.deb`/`.AppImage`) are built by the GitHub Actions workflow `desktop` (see [Releases](https://github.com/M4XM77R/Sunak/releases) after a tag `desktop-v*`, or run the workflow by hand under *Actions → desktop* and download the artifacts).

The packages are not code-signed. Windows SmartScreen and macOS Gatekeeper warn on the first start (macOS: right-click → Open). Linux needs WebKitGTK (`libwebkit2gtk-4.1`).

## Build it yourself

```bash
# needs Rust (rustup.rs), the Tauri prerequisites for your system and the Tauri CLI
cargo install tauri-cli --version "^2" --locked
cd desktop/src-tauri
cargo tauri icon ../../sunak/static/icon.svg   # once: creates the icons/ folder
cargo tauri dev                                 # run
cargo tauri build                               # packages in target/release/bundle
```

## How it works

`src-tauri/src/main.rs`: picks a free port, starts Sunak, waits for `/api/status`, then points the window at `http://127.0.0.1:PORT/`. On exit it sends `POST /api/shutdown` and kills the process if it does not stop. A second start only focuses the open window. `ui/index.html` is the loading and error page. The Sunak interface gets no Tauri permissions.
