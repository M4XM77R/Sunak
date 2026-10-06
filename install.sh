#!/usr/bin/env bash
# Sunak installer for Linux and macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/M4XM77R/sunak/main/install.sh | bash
#
# Options (append after "bash -s --" when piping, or pass directly):
#   --yes          answer yes to every question (unattended)
#   --no-ollama    do not install Ollama
#   --no-start     do not start Sunak after installing
set -euo pipefail

REPO="${SUNAK_REPO:-M4XM77R/sunak}"
BRANCH="${SUNAK_BRANCH:-main}"
HOME_DIR="${SUNAK_HOME:-$HOME/.sunak}"
APP_DIR="$HOME_DIR/app"
BIN_DIR="$HOME/.local/bin"
YES=0; NO_OLLAMA=0; NO_START=0
for a in "$@"; do
  case "$a" in
    --yes|-y) YES=1 ;;
    --no-ollama) NO_OLLAMA=1 ;;
    --no-start) NO_START=1 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done

if [ -t 1 ]; then P=$'\033[38;5;205m'; B=$'\033[1m'; R=$'\033[0m'; else P=""; B=""; R=""; fi
say()  { printf '%s⛵%s %s\n' "$P" "$R" "$*"; }
warn() { printf '%s!%s %s\n' "$P" "$R" "$*" >&2; }
die()  { warn "$*"; exit 1; }
ask() {  # ask "Question" -> 0 for yes
  [ "$YES" = 1 ] && return 0
  local ans=""
  if [ -r /dev/tty ]; then read -r -p "$1 [Y/n] " ans </dev/tty || true; else return 0; fi
  case "$ans" in [nN]*) return 1 ;; *) return 0 ;; esac
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
  rm -rf "$APP_DIR" && mv "$APP_DIR.new" "$APP_DIR"
elif [ -d "$APP_DIR/.git" ]; then
  say "Updating existing install…"
  git -C "$APP_DIR" pull --ff-only -q
elif [ -z "$SRC" ]; then
  say "Downloading Sunak…"
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
# Sunak launcher. Usage: sunak [--port N] [--host 0.0.0.0] [--no-browser] | update | uninstall
APP_DIR="$APP_DIR"
case "\${1:-}" in
  update)
    if [ -d "\$APP_DIR/.git" ]; then git -C "\$APP_DIR" pull --ff-only && echo "Updated ✓"
    else curl -fsSL https://raw.githubusercontent.com/$REPO/$BRANCH/install.sh | bash -s -- --no-ollama --no-start; fi
    exit ;;
  uninstall)
    read -r -p "Remove Sunak and ALL its data in $HOME_DIR? [y/N] " a
    case "\$a" in [yY]*) rm -rf "$HOME_DIR" "$BIN_DIR/sunak" "\$HOME/.local/share/applications/sunak.desktop"; echo "Removed.";; esac
    exit ;;
esac
export PYTHONPATH="\$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m sunak "\$@"
EOF
chmod +x "$BIN_DIR/sunak"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
      if [ -f "$rc" ] || [ "$rc" = "$HOME/.bashrc" ]; then
        grep -qs 'sunak PATH' "$rc" || printf '\nexport PATH="%s:$PATH"  # sunak PATH\n' "$BIN_DIR" >> "$rc"
      fi
    done
    export PATH="$BIN_DIR:$PATH"
    ;;
esac
say "Command ${B}sunak${R} installed ✓"

# Linux app-menu entry
if [ "$(uname)" = Linux ] && [ -d "$HOME/.local/share" ]; then
  mkdir -p "$HOME/.local/share/applications"
  cat > "$HOME/.local/share/applications/sunak.desktop" <<EOF
[Desktop Entry]
Name=Sunak
Comment=Private AI workspace
Exec=$BIN_DIR/sunak
Icon=$APP_DIR/sunak/static/icon.svg
Terminal=true
Type=Application
Categories=Utility;
EOF
fi

# 4. Ollama (local models) -----------------------------------------------
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

printf '\n  %sDone!%s Start Sunak any time with: %ssunak%s\n' "$B" "$R" "$P" "$R"
printf '  On first start it suggests a model that fits your computer.\n\n'

if [ "$NO_START" = 0 ]; then
  if [ -r /dev/tty ]; then exec "$BIN_DIR/sunak" </dev/tty; else exec "$BIN_DIR/sunak"; fi
fi
