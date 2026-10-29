#!/bin/bash
# job-hunter for macOS: double-click this file (the first time, right-click it and choose Open).
# Linux: run ./start.sh, which is the same script.
# First time: sets job-hunter up (about a minute, needs internet). After that: opens the page.
# job-hunter then runs in the background; use Quit on the page to stop it (it also stops by
# itself when no job-hunter page has been open for 10 minutes).
# Your own files (profile, resume, results) go in ~/Documents/job-hunter, so a new version of
# job-hunter never touches them. Set JOBHUNTER_HOME to use another folder.
set -u
APP="$(cd "$(dirname "$0")" && pwd)"
VENV="$APP/.venv"
JH="$VENV/bin/job-hunter"

fail() {
  echo
  echo " Setup didn't finish. The lines above say what went wrong. Check your internet connection"
  echo " and run Start job-hunter again. If it keeps failing, delete $VENV and try again."
  read -r -p " Press Enter to close." _ || true
  exit 1
}

# --- where your files live ------------------------------------------------------------------
if [ -n "${JOBHUNTER_HOME:-}" ]; then
  DATA="$JOBHUNTER_HOME"
elif [ -f "$APP/profile.yaml" ]; then  # already set up inside this folder (older versions did that)
  DATA="$APP"
elif [ -d "$HOME/Documents" ]; then
  DATA="$HOME/Documents/job-hunter"
else
  DATA="$HOME/job-hunter"
fi

# --- first run: install -----------------------------------------------------------------------
if [ ! -x "$JH" ]; then
  echo
  echo " Setting up job-hunter. This happens once and takes about a minute."
  echo
  # uv (from Astral) installs job-hunter and, if needed, its own copy of Python. Both live inside
  # this folder (.uv): nothing else on the computer changes, and deleting the folder removes it all.
  UVDIR="$APP/.uv"
  export UV_PYTHON_INSTALL_DIR="$UVDIR/python" UV_PYTHON_PREFERENCE=only-managed
  UV="$UVDIR/uv"
  installed=no
  if [ ! -x "$UV" ]; then
    echo " Getting the installer..."
    curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$UVDIR" sh >/dev/null 2>&1 || true
  fi
  if [ -x "$UV" ]; then
    echo " Getting Python and job-hunter's parts..."
    rm -rf "$VENV"
    "$UV" venv --quiet --python 3.12 "$VENV" && "$UV" pip install --quiet --python "$VENV/bin/python" -e "$APP" \
      && installed=yes
  fi
  if [ "$installed" = no ]; then
    echo " Couldn't use the installer; trying this computer's own Python instead."
    PY=""
    for c in python3.13 python3.12 python3.11 python3.10 python3; do
      p="$(command -v "$c" 2>/dev/null)" || continue
      # On a Mac without developer tools, /usr/bin/python3 is a stub that pops up an installer.
      if [ "$p" = /usr/bin/python3 ] && [ "$(uname)" = Darwin ] && ! xcode-select -p >/dev/null 2>&1; then continue; fi
      if "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then PY="$p"; break; fi
    done
    if [ -z "$PY" ]; then
      echo " This computer has no Python 3.10 or newer. Install it from https://www.python.org/downloads/"
      echo " and run Start job-hunter again."
      fail
    fi
    echo " Using $("$PY" --version) (this way takes a few minutes)..."
    rm -rf "$VENV"
    "$PY" -m venv "$VENV" || fail
    "$VENV/bin/python" -m pip install --quiet --upgrade pip
    "$VENV/bin/python" -m pip install --quiet -e "$APP" || fail
  fi
  [ -x "$JH" ] || fail
  echo
  echo " Done."
  echo
fi

# The Claude Code skill (tailoring resumes, filling applications), kept current with this version,
# if Claude Code is on this computer.
if [ -d "$HOME/.claude" ]; then
  [ -f "$HOME/.claude/skills/job-hunter/SKILL.md" ] || echo " Adding the job-hunter skill to Claude Code."
  mkdir -p "$HOME/.claude/skills/job-hunter" && cp -R "$APP/skills/job-hunter/." "$HOME/.claude/skills/job-hunter/"
fi

# --- every run: open the page ---------------------------------------------------------------------
( umask 077 && mkdir -p "$DATA" )  # your files: readable by your account only
cd "$DATA" || fail
# Tells Claude Code (and you) where the job-hunter command is, since it isn't on PATH.
printf '%s\n' "$JH" > .job-hunter-command
echo
echo " Your job-hunter files are in $DATA"
# Runs in the background, so this window can be closed. A copy that's already running is reused.
nohup "$JH" ui --quit-when-idle >"$DATA/.job-hunter.log" 2>&1 &
disown 2>/dev/null || true
for _ in $(seq 1 30); do  # wait for it to answer (up to 30 seconds)
  if [ -f "$DATA/open-job-hunter.html" ]; then
    echo " job-hunter is open in your browser. You can close this window."
    exit 0
  fi
  sleep 1
done
echo
echo " job-hunter didn't start in the background. Here's what it said:"
cat "$DATA/.job-hunter.log"
read -r -p " Press Enter to close." _ || true
exit 1
