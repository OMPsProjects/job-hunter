#!/bin/bash
# job-hunter for macOS: double-click this file (the first time, right-click it and choose Open).
# Linux: run ./start.sh, which is the same script.
# First time: sets job-hunter up (2-5 minutes, needs internet). After that: opens the page.
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
  echo " Setting up job-hunter. This happens once and takes 2-5 minutes."
  echo
  PY=""
  for c in python3.13 python3.12 python3.11 python3.10 python3; do
    p="$(command -v "$c" 2>/dev/null)" || continue
    # On a Mac without developer tools, /usr/bin/python3 is a stub that pops up an installer.
    if [ "$p" = /usr/bin/python3 ] && [ "$(uname)" = Darwin ] && ! xcode-select -p >/dev/null 2>&1; then continue; fi
    if "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then PY="$p"; break; fi
  done
  installed=no
  if [ -n "$PY" ]; then
    echo " Using $("$PY" --version). Getting job-hunter's parts..."
    rm -rf "$VENV"
    if "$PY" -m venv "$VENV" >/dev/null 2>&1; then
      "$VENV/bin/python" -m pip install --quiet --upgrade pip
      "$VENV/bin/python" -m pip install --quiet -e "$APP" && installed=yes
    fi
    [ "$installed" = yes ] || { echo " That Python couldn't set up job-hunter; trying a private copy instead."; rm -rf "$VENV"; }
  fi
  if [ "$installed" = no ]; then
    # No usable Python 3.10+. uv (from Astral) installs one just for job-hunter, without admin
    # rights and without changing the rest of your computer.
    if ! command -v uv >/dev/null 2>&1 && [ -x "$HOME/.local/bin/uv" ]; then PATH="$HOME/.local/bin:$PATH"; fi
    if ! command -v uv >/dev/null 2>&1; then
      echo " This computer doesn't have Python 3.10 or newer, so job-hunter is downloading a private"
      echo " copy just for itself (about 40 MB, using the uv installer from astral.sh). Nothing else changes."
      echo
      curl -LsSf https://astral.sh/uv/install.sh | sh || fail
      PATH="$HOME/.local/bin:$PATH"
      command -v uv >/dev/null 2>&1 || fail
    fi
    echo " Getting Python and job-hunter's parts..."
    rm -rf "$VENV"
    uv venv --python 3.12 "$VENV" || fail
    uv pip install --python "$VENV/bin/python" -e "$APP" || fail
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
