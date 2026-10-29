#!/bin/bash
# job-hunter for macOS: double-click this file (the first time, right-click it and choose Open).
# Linux: run ./start.sh, which is the same script.
# First time: sets job-hunter up (2-5 minutes, needs internet). After that: opens the page.
# Your own files (profile, resume, results) go in ~/Documents/job-hunter, so a new version of
# job-hunter never touches them. Set JOBHUNTER_HOME to use another folder.
set -u
APP="$(cd "$(dirname "$0")" && pwd)"
VENV="$APP/.venv"
JH="$VENV/bin/job-hunter"

ask() {  # ask "question" -> 0 for yes
  local a
  read -r -p " $1 [y/n] " a || return 1
  [[ "$a" =~ ^[Yy] ]]
}
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
      echo " job-hunter needs Python 3.10 or newer, and this computer doesn't have a usable one."
      echo " It can download a private copy for job-hunter now (about 40 MB, using the uv installer"
      echo " from astral.sh). Or say no and install Python yourself from https://www.python.org/downloads/"
      echo
      if ! ask "Download it now?"; then
        echo " Install Python 3.10 or newer, then run Start job-hunter again."
        exit 1
      fi
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
  # The Claude Code skill (tailoring resumes, filling applications), if Claude Code is installed.
  if [ -d "$HOME/.claude" ] && [ ! -f "$HOME/.claude/skills/job-hunter/SKILL.md" ]; then
    if ask "Claude Code is installed. Add the job-hunter skill to it?"; then
      mkdir -p "$HOME/.claude/skills" && cp -R "$APP/skills/job-hunter" "$HOME/.claude/skills/" && echo " Skill added."
    fi
  fi
fi

# --- every run: open the page ---------------------------------------------------------------------
( umask 077 && mkdir -p "$DATA" )  # your files: readable by your account only
cd "$DATA" || fail
# Tells Claude Code (and you) where the job-hunter command is, since it isn't on PATH.
printf '%s\n' "$JH" > .job-hunter-command
echo
echo " Your job-hunter files are in $DATA"
echo " Keep this window open while you use job-hunter. Close it (or press Ctrl+C) to stop."
echo
"$JH" ui
