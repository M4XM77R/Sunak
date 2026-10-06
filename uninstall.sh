#!/usr/bin/env bash
# Remove Sunak from Linux or macOS. Your chats, settings and keys are kept unless you say otherwise.
#
#   curl -fsSL https://raw.githubusercontent.com/M4XM77R/sunak/main/uninstall.sh | bash
#
# Options (append after "bash -s --" when piping, or pass directly):
#   --yes          no questions: remove the program, keep your data, Ollama and its models
#   --purge        also delete your data
#   --with-ollama  also uninstall Ollama (otherwise you are asked; the default keeps it)
#   --with-models  also delete the downloaded Ollama models (otherwise you are asked)
# The same as "sunak uninstall".
set -uo pipefail

REPO="${SUNAK_REPO:-M4XM77R/sunak}"
BRANCH="${SUNAK_BRANCH:-main}"
HOME_DIR="${SUNAK_HOME:-$HOME/.sunak}"
LAUNCHER="$HOME/.local/bin/sunak"
for a in "$@"; do
  case "$a" in --yes|-y|--purge|--with-ollama|--with-models) ;;
    *) echo "Unknown option: $a (use --yes, --purge, --with-ollama, --with-models)" >&2; exit 2 ;; esac
done
command -v python3 >/dev/null || { echo "Python 3 is not installed, so Sunak cannot be either. Your data (if any) is in $HOME_DIR."; exit 0; }

# The uninstaller is part of Sunak: use this clone, else the installed app, else download it.
has_uninstaller() { [ -n "$1" ] && [ -f "$1/sunak/uninstall.py" ]; }
src=""
if [ -n "${BASH_SOURCE[0]:-}" ] && has_uninstaller "$(dirname "${BASH_SOURCE[0]}")"; then
  src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
if [ -z "$src" ] && [ -f "$LAUNCHER" ]; then
  app=$(sed -n 's/^APP_DIR="\(.*\)"$/\1/p' "$LAUNCHER" | head -n 1)
  has_uninstaller "$app" && src="$app"
fi
[ -z "$src" ] && has_uninstaller "$HOME_DIR/app" && src="$HOME_DIR/app"
tmp=""
if [ -z "$src" ]; then  # an older Sunak without the uninstaller, or nothing installed
  tmp=$(mktemp -d)
  if curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" | tar xz -C "$tmp" --strip-components 1 2>/dev/null \
      && has_uninstaller "$tmp"; then
    src="$tmp"
  else
    rm -rf "$tmp"
    echo "Could not download the uninstaller. Remove Sunak by hand: $HOME_DIR/app, $LAUNCHER and the line marked"
    echo "'# sunak PATH' in ~/.bashrc or ~/.zshrc. Your data is in $HOME_DIR."
    exit 1
  fi
fi

cd "$HOME" || exit 1
# questions need the terminal, also when this script comes through a pipe
if { : </dev/tty; } 2>/dev/null; then
  PYTHONPATH="$src" python3 -m sunak uninstall "$@" </dev/tty
else
  PYTHONPATH="$src" python3 -m sunak uninstall "$@" </dev/null
fi
code=$?
[ -n "$tmp" ] && rm -rf "$tmp"
exit $code
