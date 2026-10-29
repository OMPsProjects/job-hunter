@echo off
rem job-hunter for Windows: double-click this file.
rem First time: sets job-hunter up (2-5 minutes, needs internet). After that: opens the page.
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
echo  job-hunter needs Python 3.10 or newer, and this computer doesn't have it.
echo  It can download a private copy for job-hunter now (about 40 MB, using the uv installer
echo  from astral.sh). Or say no and install Python yourself from https://www.python.org/downloads/
echo.
choice /C YN /M " Download it now"
if errorlevel 2 goto no_python
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul || goto fail
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
rem A desktop shortcut, if they want one.
choice /C YN /M " Put a job-hunter shortcut on your desktop"
if errorlevel 2 goto skip_shortcut
powershell -NoProfile -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'job-hunter.lnk')); $s.TargetPath=(Join-Path $env:APP 'Start job-hunter.bat'); $s.WorkingDirectory=$env:APP; $s.Save()"
:skip_shortcut
rem The Claude Code skill (tailoring resumes, filling applications), if Claude Code is installed.
if not exist "%USERPROFILE%\.claude" goto run
if exist "%USERPROFILE%\.claude\skills\job-hunter\SKILL.md" goto run
choice /C YN /M " Claude Code is installed. Add the job-hunter skill to it"
if errorlevel 2 goto run
xcopy /E /I /Q /Y "%APP%\skills\job-hunter" "%USERPROFILE%\.claude\skills\job-hunter" >nul && echo  Skill added.

rem --- every run: open the page ---------------------------------------------------------------
:run
if not exist "%DATA%" mkdir "%DATA%"
cd /d "%DATA%"
rem Tells Claude Code (and you) where the job-hunter command is, since it isn't on PATH.
> ".job-hunter-command" <nul set /p "=%JH%"
echo.
echo  Your job-hunter files are in "%DATA%"
echo  Keep this window open while you use job-hunter. Close it to stop.
echo.
"%JH%" ui
echo.
pause
exit /b 0

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
