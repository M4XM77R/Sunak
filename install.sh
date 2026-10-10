#!/usr/bin/env bash
# Sunak installer for Linux and macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/M4XM77R/sunak/main/install.sh | bash
#
# Options (append after "bash -s --" when piping, or pass directly):
#   --yes          answer yes to every question (unattended)
#   --no-ollama    do not install Ollama
#   --no-start     do not start Sunak after installing
#   --no-shortcut  do not create a desktop icon
#   --autostart    start Sunak in the background at every login (otherwise you are asked)
#   --desktop      also install the optional desktop app (also SUNAK_DESKTOP=1; otherwise you are asked, default no)
set -euo pipefail

REPO="${SUNAK_REPO:-M4XM77R/sunak}"
BRANCH="${SUNAK_BRANCH:-main}"
HOME_DIR="${SUNAK_HOME:-$HOME/.sunak}"
APP_DIR="$HOME_DIR/app"
BIN_DIR="$HOME/.local/bin"
YES=0; NO_OLLAMA=0; NO_START=0; AUTOSTART=""; NO_SHORTCUT=0; DESKTOP=""; [ "${SUNAK_DESKTOP:-}" = 1 ] && DESKTOP=1
for a in "$@"; do
  case "$a" in
    --yes|-y) YES=1 ;;
    --no-ollama) NO_OLLAMA=1 ;;
    --no-start) NO_START=1 ;;
    --autostart) AUTOSTART=1 ;;
    --no-shortcut) NO_SHORTCUT=1 ;;
    --desktop) DESKTOP=1 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done

if [ -t 1 ]; then P=$'\033[38;5;205m'; B=$'\033[1m'; R=$'\033[0m'; else P=""; B=""; R=""; fi
say()  { printf '%s⛵%s %s\n' "$P" "$R" "$*"; }
warn() { printf '%s!%s %s\n' "$P" "$R" "$*" >&2; }
die()  { warn "$*"; exit 1; }
has_tty() { { : </dev/tty; } 2>/dev/null; }  # a terminal we can really read from (not just a /dev/tty node)
ask() {  # ask "Question" -> 0 for yes
  [ "$YES" = 1 ] && return 0
  local ans=""
  if has_tty; then read -r -p "$1 [Y/n] " ans </dev/tty || true; else return 0; fi
  case "$ans" in [nN]*) return 1 ;; *) return 0 ;; esac
}
ask_no() {  # like ask, but the default (and --yes) is no
  [ "$YES" = 1 ] && return 1
  local ans=""
  if has_tty; then read -r -p "$1 [y/N] " ans </dev/tty || true; else return 1; fi
  case "$ans" in [yY]*) return 0 ;; *) return 1 ;; esac
}
SUDO=""; [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null && SUDO="sudo"

printf '\n  %s%sSunak%s – your private AI workspace\n\n' "$B" "$P" "$R"

# 1. Python 3.9+ ---------------------------------------------------------
py_ok() { command -v python3 >/dev/null && python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; }
if ! py_ok; then
  say "Python 3.9+ is needed. Installing it…"
  if command -v apt-get >/dev/null; then $SUDO apt-get update -qq && $SUDO apt-get install -y -qq python3
  elif command -v dnf >/dev/null; then $SUDO dnf install -y -q python3
  elif command -v pacman >/dev/null; then $SUDO pacman -Sy --noconfirm python
  elif command -v zypper >/dev/null; then $SUDO zypper -n install python3
  elif command -v brew >/dev/null; then brew install python
  elif [ "$(uname)" = Darwin ]; then xcode-select --install 2>/dev/null || true; die "Finish the Apple developer tools install, then run this installer again."
  fi
  py_ok || die "Could not install Python automatically. Install Python 3.9+ from https://python.org and run again."
fi
say "Python $(python3 -c 'import platform; print(platform.python_version())') ✓"

# 2. Get the app -----------------------------------------------------------
SRC=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/sunak/server.py" ]; then
  SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
mkdir -p "$HOME_DIR"
if [ -n "$SRC" ] && [ "$SRC" != "$APP_DIR" ]; then
  say "Installing from $SRC"
  rm -rf "$APP_DIR.new" && mkdir -p "$APP_DIR.new"
  (cd "$SRC" && tar cf - --exclude=.git --exclude=data --exclude='__pycache__' .) | (cd "$APP_DIR.new" && tar xf -)
  git -C "$SRC" rev-parse HEAD > "$APP_DIR.new/.commit" 2>/dev/null || rm -f "$APP_DIR.new/.commit"  # for the update check
  rm -rf "$APP_DIR" && mv "$APP_DIR.new" "$APP_DIR"
  # remember the clone, so "sunak update" can pull it (also works for private repositories)
  if [ -d "$SRC/.git" ]; then echo "$SRC" > "$HOME_DIR/source"; else rm -f "$HOME_DIR/source"; fi
elif [ -d "$APP_DIR/.git" ]; then
  say "Updating existing install…"
  git -C "$APP_DIR" pull --ff-only -q
elif [ -z "$SRC" ]; then
  say "Downloading Sunak…"
  rm -f "$HOME_DIR/source"  # no clone to update from
  if command -v git >/dev/null && git clone -q --depth 1 -b "$BRANCH" "https://github.com/$REPO.git" "$APP_DIR.new" 2>/dev/null; then :
  else
    rm -rf "$APP_DIR.new" && mkdir -p "$APP_DIR.new"
    curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" | tar xz -C "$APP_DIR.new" --strip-components 1 \
      || die "Download failed. If the repository is private, clone it yourself and run ./install.sh inside it."
  fi
  rm -rf "$APP_DIR" && mv "$APP_DIR.new" "$APP_DIR"
fi
say "App installed in $APP_DIR ✓"

# 3. Launcher command ------------------------------------------------------
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/sunak" <<EOF
#!/usr/bin/env bash
# Sunak launcher.
#   sunak [--port N] [--host 0.0.0.0] [--no-browser]   start (or open the running Sunak)
#   sunak stop | status | version | gpu | shortcut | autostart on|off | update | uninstall   (all: sunak -h)
APP_DIR="$APP_DIR"
export PYTHONPATH="\$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
case "\${1:-}" in
  uninstall) cd "\$HOME" && exec python3 -m sunak "\$@" ;;  # keeps your data unless you say otherwise
  update)
    case "\${2:-}" in -h|--help) exec python3 -m sunak help update ;; esac
    ask="--confirm"; case "\${2:-}" in -y|--yes) ask="--confirm --yes" ;; esac
    python3 -m sunak changelog \$ask; [ \$? -eq 3 ] && exit 0  # shows what is new and asks (3 = declined)
    export SUNAK_HOME="$HOME_DIR" SUNAK_REPO="$REPO" SUNAK_BRANCH="$BRANCH"  # reinstall into the same place
    old=\$(python3 -m sunak version)
    src=\$(cat "$HOME_DIR/source" 2>/dev/null)
    if [ -d "\$APP_DIR/.git" ]; then
      git -C "\$APP_DIR" pull --ff-only -q || exit 1
      python3 -m sunak desktop update --auto || true  # the other routes reinstall, and the installer does this (a problem here never fails the update)
    elif [ -n "\$src" ] && [ -d "\$src/.git" ]; then
      echo "Updating from \$src"
      git -C "\$src" pull --ff-only -q && bash "\$src/install.sh" --yes --no-ollama --no-start --no-shortcut >/dev/null || exit 1
    else
      script=\$(curl -fsSL https://raw.githubusercontent.com/$REPO/$BRANCH/install.sh) || {
        echo "Download failed. For a private repository: git pull in your clone, then run ./install.sh there."; exit 1; }
      bash -c "\$script" -s --yes --no-ollama --no-start --no-shortcut || exit 1
    fi
    new=\$(python3 -m sunak version)
    if [ "\$old" = "\$new" ]; then echo "Sunak \$new: latest code installed ✓"; else echo "Updated Sunak \$old → \$new ✓"; fi
    if python3 -m sunak status | grep -q "is running"; then
      python3 -m sunak stop >/dev/null && echo "Sunak was running and has been stopped. Start it again with: sunak"
    fi
    exit ;;
esac
exec python3 -m sunak "\$@"
EOF
chmod +x "$BIN_DIR/sunak"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    # bash reads .bashrc (Linux) or .bash_profile (macOS login shells); zsh (macOS default) reads .zshrc
    for rc in "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.zshrc"; do
      want=0
      [ -f "$rc" ] && want=1
      [ "$rc" = "$HOME/.bashrc" ] && [ "$(uname)" != Darwin ] && want=1
      [ "$rc" = "$HOME/.zshrc" ] && { [ "$(uname)" = Darwin ] || [ "${SHELL##*/}" = zsh ]; } && want=1
      if [ "$want" = 1 ]; then
        grep -qs 'sunak PATH' "$rc" || printf '\nexport PATH="%s:$PATH"  # sunak PATH\n' "$BIN_DIR" >> "$rc"
      fi
    done
    export PATH="$BIN_DIR:$PATH"
    ;;
esac
say "Command ${B}sunak${R} installed ✓"

# Desktop icon (Linux: app menu + desktop, macOS: ~/Applications/Sunak.app) and autostart
if [ "$NO_SHORTCUT" = 0 ] && ask "Create a Sunak icon on your desktop?"; then
  (cd "$APP_DIR" && python3 -m sunak shortcut >/dev/null) && say "Desktop icon ✓"
fi
if [ "$AUTOSTART" = 1 ] || ask_no "Start Sunak automatically in the background when you log in?"; then
  (cd "$APP_DIR" && python3 -m sunak autostart on >/dev/null) && say "Autostart ✓ (turn off with: sunak autostart off)"
fi

# 4. Ollama (local models) -----------------------------------------------
# Ollama uses a GPU on its own (CUDA, ROCm, Metal); its installer sets up what the GPU needs.
(cd "$APP_DIR" && python3 -m sunak gpu 2>/dev/null) | while IFS= read -r line; do say "$line"; done || true
if [ "$NO_OLLAMA" = 0 ] && ! command -v ollama >/dev/null; then
  if ask "Install Ollama to run AI models on this computer? (recommended)"; then
    if [ "$(uname)" = Darwin ]; then
      if command -v brew >/dev/null; then brew install --cask ollama && open -a Ollama || true
      else warn "Download Ollama from https://ollama.com/download/mac and open it once."; fi
    else
      curl -fsSL https://ollama.com/install.sh | sh || warn "Ollama install failed – see https://ollama.com/download"
    fi
  else
    say "Skipping Ollama. You can add an API key (OpenAI, OpenRouter, Groq…) in Settings."
  fi
fi
command -v ollama >/dev/null && say "Ollama ✓"

# 5. Desktop app (optional, opt-in) --------------------------------------
# `sunak desktop install` downloads the finished package from the newest GitHub release "desktop-v*" (no Rust).
# A failure is only a hint: the normal installation is already complete.
if [ "$DESKTOP" = 1 ] || ask_no "Also install the desktop app (Sunak in its own window)?"; then
  (cd "$APP_DIR" && SUNAK_HOME="$HOME_DIR" SUNAK_REPO="$REPO" python3 -m sunak desktop install) \
    || warn "Desktop app not installed. Sunak itself is ready; try later: sunak desktop install"
else  # an installed app is renewed when a newer desktop release exists (nothing happens if it is not installed)
  (cd "$APP_DIR" && SUNAK_HOME="$HOME_DIR" SUNAK_REPO="$REPO" python3 -m sunak desktop update --auto) || true
fi

printf '\n  %sDone!%s Start Sunak any time with: %ssunak%s\n' "$B" "$R" "$P" "$R"
printf '  On first start it suggests a model that fits your computer.\n\n'

if [ "$NO_START" = 0 ]; then
  if has_tty; then exec "$BIN_DIR/sunak" </dev/tty; else exec "$BIN_DIR/sunak"; fi
fi
