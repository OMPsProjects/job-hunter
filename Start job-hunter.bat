@echo off
rem job-hunter for Windows: double-click this file.
rem First time: sets job-hunter up (about a minute, needs internet). After that: opens the page.
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

rem --- started from inside the ZIP? ---------------------------------------------------------
rem Windows lets you open files inside a ZIP without extracting it, but then runs them from a
rem temporary copy that disappears. Ask for the extract instead of failing halfway.
set "CHK=%APP:.zip\=%"
if not "%CHK%"=="%APP%" goto in_zip
set "CHK=%APP:\AppData\Local\Temp\=%"
if not "%CHK%"=="%APP%" goto in_zip

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
echo  Setting up job-hunter. This happens once and takes about a minute.
echo.
rem uv (from Astral, the makers of the ruff tool) installs job-hunter and, if needed, its own copy
rem of Python. Both live inside this folder (.uv): nothing else on the computer changes, and
rem deleting this folder removes everything.
set "UVDIR=%APP%\.uv"
set "UV_PYTHON_INSTALL_DIR=%UVDIR%\python"
set "UV_PYTHON_PREFERENCE=only-managed"
set "UV=%UVDIR%\uv.exe"
if exist "%UV%" goto have_uv
echo  Getting the installer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:UV_UNMANAGED_INSTALL=$env:UVDIR; irm https://astral.sh/uv/install.ps1 | iex" >nul
if exist "%UV%" goto have_uv
echo  Couldn't get the installer; trying this computer's own Python instead.
goto try_python

:have_uv
echo  Getting Python and job-hunter's parts...
if exist "%VENV%" rmdir /s /q "%VENV%"
"%UV%" venv --quiet --python 3.12 "%VENV%" || goto try_python
"%UV%" pip install --quiet --python "%VENV%\Scripts\python.exe" -e "%APP%" || goto try_python
goto installed

:try_python
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
if defined PY goto have_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
if defined PY goto have_python
goto no_python

:have_python
echo  Using %PY%. Getting job-hunter's parts (this way takes a few minutes)...
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
rem the small, low-cost helper Claude uses to read LinkedIn in your browser
if not exist "%USERPROFILE%\.claude\agents" mkdir "%USERPROFILE%\.claude\agents"
copy /Y "%APP%\skills\job-hunter\agents\job-hunter-linkedin.md" "%USERPROFILE%\.claude\agents\job-hunter-linkedin.md" >nul
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

:in_zip
echo.
echo  job-hunter is still inside its ZIP file, so it can't set itself up.
echo.
echo  1. Close this window.
echo  2. Right-click the job-hunter ZIP file and choose "Extract All", then "Extract".
echo  3. In the folder that opens, double-click Start job-hunter.
echo.
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
