@echo off
rem Double-click to open the GuiAutomation builder.
rem
rem The first run on a computer creates .venv and installs the pinned packages.
rem Later runs start straight away, and reinstall only when pyproject.toml has
rem changed or the environment no longer works (for example after the folder
rem was moved). Pass --setup-only to prepare the environment without opening
rem the builder.
setlocal EnableExtensions DisableDelayedExpansion
title GuiAutomation
pushd "%~dp0"
if errorlevel 1 goto fail_folder

set "VENV_PY=.venv\Scripts\python.exe"
set "STAMP=.venv\installed-pyproject.toml"
set "SETUP_ONLY="
if /i "%~1"=="--setup-only" set "SETUP_ONLY=1"

if not exist "%VENV_PY%" goto create_venv
"%VENV_PY%" -c "import sys" >nul 2>&1
if errorlevel 1 goto create_venv
goto check_install

:create_venv
echo Setting up GuiAutomation on this computer. This takes a minute or two.
set "BASE_PY="
call :try_python py -3.13
if not defined BASE_PY call :try_python py -3
if not defined BASE_PY call :try_python python
if not defined BASE_PY goto fail_no_python
echo Creating .venv using "%BASE_PY%"
%BASE_PY% -m venv --clear .venv
if errorlevel 1 goto fail_venv
goto install

:check_install
fc /b pyproject.toml "%STAMP%" >nul 2>&1
if errorlevel 1 goto install
"%VENV_PY%" -c "import guiautomation" >nul 2>&1
if errorlevel 1 goto install
goto run

:install
echo Installing packages
if exist "%STAMP%" del "%STAMP%"
"%VENV_PY%" -m pip install --disable-pip-version-check -e ".[dev]"
if errorlevel 1 goto fail_install
copy /y pyproject.toml "%STAMP%" >nul
echo Setup finished.
goto run

:run
if defined SETUP_ONLY goto done
"%VENV_PY%" -m guiautomation gui %*
if errorlevel 1 goto fail_run
goto done

rem Sets BASE_PY to the given command if it is Python 3.13 or newer with
rem tkinter and venv. The minimum matches requires-python in pyproject.toml.
:try_python
%* -c "import sys, tkinter, venv; sys.exit(sys.version_info < (3, 13))" >nul 2>&1
if not errorlevel 1 set "BASE_PY=%*"
exit /b 0

:fail_folder
echo Could not open the folder this file is in: "%~dp0"
goto fail

:fail_no_python
echo.
echo Python 3.13 or newer was not found on this computer.
echo Install it from https://www.python.org/downloads/ with the default options,
echo or run this in a terminal:
echo     winget install Python.Python.3.13
echo Then double-click this file again.
goto fail

:fail_venv
echo.
echo Could not create the .venv folder. Close any program using it and try again.
goto fail

:fail_install
echo.
echo Installing packages failed. Check the internet connection and the messages
echo above, then double-click this file again.
goto fail

:fail_run
echo.
echo GuiAutomation stopped with an error. See the messages above.
goto fail

:fail
popd
pause
exit /b 1

:done
popd
exit /b 0
