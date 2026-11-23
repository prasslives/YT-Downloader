#!/bin/bash
# OmniMedia launcher (macOS / Linux).
#  - creates .venv on first run
#  - updates yt-dlp at most once a day (YouTube changes constantly; stale
#    yt-dlp is the #1 cause of failed downloads)
#  - starts the app
set -u
cd "$(dirname "$0")" || exit 1

# Finder-launched apps get a minimal PATH. Prefer Homebrew over /usr/bin
# (/usr/bin/python3 is the Xcode stub and may refuse to run).
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.deno/bin:$PATH"

VENV=".venv"
PY="$VENV/bin/python"
STAMP="$VENV/.last-update"

fail() { echo "ERROR: $*" >&2; osascript -e "display alert \"OmniMedia\" message \"$*\"" >/dev/null 2>&1; exit 1; }

if [ ! -x "$PY" ]; then
  command -v python3 >/dev/null || fail "Python 3 not found. Install it with: brew install python"
  echo "Creating virtual environment…"
  python3 -m venv "$VENV" || fail "Could not create the Python virtual environment."
  "$PY" -m pip install -q --upgrade pip
  echo "Installing dependencies…"
  "$PY" -m pip install -q -e . || fail "Dependency installation failed. Check your internet connection."
  date +%Y-%m-%d > "$STAMP"
fi

if [ "$(cat "$STAMP" 2>/dev/null)" != "$(date +%Y-%m-%d)" ]; then
  echo "Checking for yt-dlp updates…"
  # Short timeout so an offline launch isn't blocked.
  if "$PY" -m pip install -q --upgrade --timeout 15 "yt-dlp[default]" "pywebview>=6.2"; then
    date +%Y-%m-%d > "$STAMP"
  else
    echo "Update skipped (offline?). Continuing with installed version."
  fi
fi

for tool in ffmpeg deno; do
  command -v "$tool" >/dev/null || echo "WARNING: '$tool' not found. Install it with: brew install $tool"
done

exec "$PY" -m omnimedia
