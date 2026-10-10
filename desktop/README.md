# Sunak desktop (optional)

Sunak in its own window instead of the browser, built with [Tauri](https://tauri.app). It is a thin shell: it starts the normal Sunak server on a free local port (`sunak --no-browser --port N`), shows the unchanged interface and stops the server when you close the window. Your data stays in the usual Sunak folder, so the app and the browser version show the same chats.

**Sunak itself must be installed** (the one-line installer from the main README). Python is not bundled. If Sunak is missing the window says so. The app looks for the `sunak` command, then `python3 -m sunak`, `python -m sunak` (and `py -3` on Windows).

The normal installation does not change and needs no Rust. Only building the app yourself does.

## Get it

Packages for Windows (`.msi`/`.exe`), macOS (`.dmg`) and Linux (`.deb`/`.AppImage`) are built by the GitHub Actions workflow `desktop` (see [Releases](https://github.com/M4XM77R/Sunak/releases) after a tag `desktop-v*`, or run the workflow by hand under *Actions → desktop* and download the artifacts).

The packages are not code-signed. Windows SmartScreen and macOS Gatekeeper warn on the first start (macOS: right-click → Open). Linux needs WebKitGTK (`libwebkit2gtk-4.1`).

**Via the installer (opt-in):** `install.sh --desktop` / `$env:SUNAK_DESKTOP="1"` (or answer yes to the last question) downloads the package for your system from the newest `desktop-v*` release: AppImage on Linux x86_64 (app-menu entry, needs FUSE), `Sunak Desktop.app` in `~/Applications` on macOS (Apple silicon only), the setup `.exe` on Windows. No release yet or a failed download only prints a hint; the normal installation is not affected.

**Updating:** `sunak update` renews an installed app too when a newer `desktop-v*` release exists (compared with the tag recorded in `desktop-version` in the Sunak folder, checked with SHA256SUMS). An open app is never replaced; close it and run `sunak desktop update`. The window only shows your installed Sunak, so the app itself rarely needs an update. Apps installed with 1.1.0 have no recorded tag and are renewed once. Nothing happens if the app is not installed.

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

`src-tauri/src/main.rs`: if a Sunak already runs on 7000-7009 it uses that one and leaves it running when the window closes. Otherwise it starts Sunak (the installed launcher by absolute path, then `sunak`, then Python with `PYTHONPATH` set) on the fixed port 17000 (so the address and the window's saved settings stay the same; another free block only if that is taken), waits for `/api/status`, then points the window at it. On exit it sends `POST /api/shutdown` and kills the process only if that does not work. Closing the window ends the app on every system. A second start only focuses the open window. `ui/index.html` is the loading and error page. The Sunak interface gets no Tauri permissions.
