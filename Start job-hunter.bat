@echo off
rem job-hunter for Windows: double-click this file.
rem First time: sets job-hunter up (2-5 minutes, needs internet). After that: opens the page.
rem job-hunter then runs in the background; use Quit on the page to stop it (it also stops by
rem itself when no job-hunter page has been open for 10 minutes).
rem Your own files (profile, resume, results) go in Documents\job-hunter, so a new version of
rem job-hunter never touches them. Set JOBHUNTER_HOME to use another folder.
setlocal EnableExtensions
title job-hunter
cd /d "%~dp0"
set "APP=%~dp0"
set "APP=%APP:~0,-1%"
set "VENV=%APP%\.venv"
set "JH=%VENV%\Scripts\job-hunter.exe"

rem --- where your files live -----------------------------------------------------------------
rem (No parenthesized blocks around paths in this file: a folder named like "job-hunter (1)"
rem would end the block early. Plain lines and goto instead.)
set "DATA=%JOBHUNTER_HOME%"
if defined JOBHUNTER_HOME goto data_set
rem Already set up inside this folder (older versions did that)? Keep using it.
set "DATA=%APP%"
if exist "%APP%\profile.yaml" goto data_set
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('MyDocuments')"`) do set "DOCS=%%D"
if not defined DOCS set "DOCS=%USERPROFILE%\Documents"
set "DATA=%DOCS%\job-hunter"
:data_set

if exist "%JH%" goto run

rem --- first run: install -------------------------------------------------------------------
echo.
echo  Setting up job-hunter. This happens once and takes 2-5 minutes.
echo.
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
if defined PY goto have_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
if defined PY goto have_python

rem No Python 3.10+. uv (from Astral, the makers of the ruff tool) installs one just for job-hunter,
rem without admin rights and without changing the rest of your computer.
where uv >nul 2>nul && goto have_uv
if not exist "%USERPROFILE%\.local\bin\uv.exe" goto ask_uv
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
goto have_uv
:ask_uv
echo  This computer doesn't have Python 3.10 or newer, so job-hunter is downloading a private copy
echo  just for itself (about 40 MB, using the uv installer from astral.sh). Nothing else changes.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul || goto no_python
:have_uv
echo  Getting Python and job-hunter's parts...
if exist "%VENV%" rmdir /s /q "%VENV%"
uv venv --python 3.12 "%VENV%" || goto fail
uv pip install --python "%VENV%\Scripts\python.exe" -e "%APP%" || goto fail
goto installed

:have_python
echo  Using %PY%. Getting job-hunter's parts...
if exist "%VENV%" rmdir /s /q "%VENV%"
%PY% -m venv "%VENV%" || goto fail
"%VENV%\Scripts\python.exe" -m pip install --quiet --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install --quiet -e "%APP%" || goto fail

:installed
if not exist "%JH%" goto fail
echo.
echo  Done.
echo.
rem A desktop shortcut, so next time you don't need this folder.
powershell -NoProfile -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'job-hunter.lnk')); $s.TargetPath=(Join-Path $env:APP 'Start job-hunter.bat'); $s.WorkingDirectory=$env:APP; $s.WindowStyle=7; $s.Save()" && echo  Added a job-hunter shortcut to your desktop.

rem --- every run: open the page ---------------------------------------------------------------
:run
rem The Claude Code skill (tailoring resumes, filling applications), kept current with this
rem version, if Claude Code is on this computer.
if not exist "%USERPROFILE%\.claude" goto skill_done
if not exist "%USERPROFILE%\.claude\skills\job-hunter\SKILL.md" echo  Adding the job-hunter skill to Claude Code.
xcopy /E /I /Q /Y "%APP%\skills\job-hunter" "%USERPROFILE%\.claude\skills\job-hunter" >nul
:skill_done
if not exist "%DATA%" mkdir "%DATA%"
cd /d "%DATA%"
rem Tells Claude Code (and you) where the job-hunter command is, since it isn't on PATH.
> ".job-hunter-command" <nul set /p "=%JH%"
echo.
echo  Your job-hunter files are in "%DATA%"
echo  Opening job-hunter in your browser. This window closes by itself.
rem Runs in the background (no window to keep open). A copy that's already running is reused.
powershell -NoProfile -Command "Start-Process -WindowStyle Hidden -FilePath $env:JH -ArgumentList 'ui','--quit-when-idle' -WorkingDirectory $env:DATA"
rem Wait for it to answer (up to 30 seconds), then this window can go. (A goto loop, not a
rem ( ) block: see the note at the top about folder names with brackets.)
set /a WAITED=0
:wait_start
if exist "%DATA%\open-job-hunter.html" exit /b 0
if %WAITED% GEQ 30 goto start_failed
ping -n 2 127.0.0.1 >nul
set /a WAITED+=1
goto wait_start
:start_failed
echo.
echo  job-hunter didn't start in the background. Starting it here so you can see why:
echo.
"%JH%" ui
pause
exit /b 1

:no_python
echo.
echo  Install Python from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo  then double-click Start job-hunter again.
pause
exit /b 1

:fail
echo.
echo  Setup didn't finish. The lines above say what went wrong. Check your internet connection
echo  and double-click Start job-hunter to try again. If it keeps failing, delete the .venv folder
echo  inside "%APP%" first, then try again.
pause
exit /b 1
