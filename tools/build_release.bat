@echo off
setlocal EnableExtensions

set "TOOLS_DIR=%~dp0"
for %%I in ("%TOOLS_DIR%..") do set "APP_DIR=%%~fI"
cd /d "%APP_DIR%"
if errorlevel 1 goto build_fail

set "BUILD_ERR=1"
set "PYTHON_CMD="
set "PYTHON_SOURCE="
set "BASE_PYTHON_CMD="
set "BASE_PYTHON_SOURCE="
set "TEMP_DIR=%APP_DIR%\.tmp"
set "VENV_DIR=%APP_DIR%\.venv_release"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

if not exist "%TEMP_DIR%" mkdir "%TEMP_DIR%"
set "TEMP=%TEMP_DIR%"
set "TMP=%TEMP_DIR%"
set "TMPDIR=%TEMP_DIR%"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PIP_REQUIRE_VIRTUALENV=1"

call :select_python
if not "%PYTHON_CMD%"=="" goto python_selected

call :install_python_313
if errorlevel 1 goto no_python

call :select_python
if "%PYTHON_CMD%"=="" goto no_python

:python_selected
set "BASE_PYTHON_CMD=%PYTHON_CMD%"
set "BASE_PYTHON_SOURCE=%PYTHON_SOURCE%"

echo Using %BASE_PYTHON_SOURCE%:
echo %BASE_PYTHON_CMD%

call :ensure_release_venv "%BASE_PYTHON_CMD%"
if errorlevel 1 goto dependency_fail

set "PYTHON_CMD=%VENV_PYTHON%"
set "PYTHON_SOURCE=release virtual environment"

echo Using %PYTHON_SOURCE%:
echo %PYTHON_CMD%

call :ensure_build_dependencies "%PYTHON_CMD%"
if errorlevel 1 goto dependency_fail

call :run_build "%PYTHON_CMD%"
set "BUILD_ERR=%ERRORLEVEL%"
if not "%BUILD_ERR%"=="0" goto build_fail

echo.
echo Done. Output folder:
echo %APP_DIR%\dist_release\Lumina
goto end

:no_python
echo [ERROR] No supported Python runtime was found.
echo Automatic Python 3.13 installation failed or was unavailable.
echo Install Python 3.13 or Python 3.12 from python.org, then run this script again.
goto build_fail

:dependency_fail
set "BUILD_ERR=1"
echo.
echo BUILD FAILED.
echo Could not prepare build dependencies automatically.
echo Check network access, Python pip installation, and Windows security software.
goto end

:build_fail
set "BUILD_ERR=1"
echo.
echo BUILD FAILED.
echo If access is denied, close running Lumina.exe and all Explorer windows opened in dist_release.
echo If Python is missing, install Python 3.13 or Python 3.12 from python.org.

:end
echo.
if not "%BUILD_RELEASE_NO_PAUSE%"=="1" pause
exit /b %BUILD_ERR%

:select_python
call :try_py_launcher 3.13 "Python 3.13"
if not "%PYTHON_CMD%"=="" exit /b 0

call :try_py_launcher 3.12 "Python 3.12"
if not "%PYTHON_CMD%"=="" exit /b 0

call :try_python_path "%LocalAppData%\Python\pythoncore-3.13-64\python.exe" "Python 3.13 user install"
if not "%PYTHON_CMD%"=="" exit /b 0

call :try_python_path "%LocalAppData%\Programs\Python\Python313\python.exe" "Python 3.13 user install"
if not "%PYTHON_CMD%"=="" exit /b 0

call :try_python_path "%ProgramFiles%\Python313\python.exe" "Python 3.13 machine install"
if not "%PYTHON_CMD%"=="" exit /b 0

call :try_python_path "%ProgramFiles(x86)%\Python313\python.exe" "Python 3.13 machine install"
if not "%PYTHON_CMD%"=="" exit /b 0

call :try_python_path "%LocalAppData%\Python\pythoncore-3.12-64\python.exe" "Python 3.12 user install"
if not "%PYTHON_CMD%"=="" exit /b 0

call :try_python_path "%LocalAppData%\Programs\Python\Python312\python.exe" "Python 3.12 user install"
if not "%PYTHON_CMD%"=="" exit /b 0

call :try_python_path "%ProgramFiles%\Python312\python.exe" "Python 3.12 machine install"
if not "%PYTHON_CMD%"=="" exit /b 0

call :try_python_path "%ProgramFiles(x86)%\Python312\python.exe" "Python 3.12 machine install"
if not "%PYTHON_CMD%"=="" exit /b 0

call :try_python_command python "python on PATH"
if not "%PYTHON_CMD%"=="" exit /b 0

call :try_python_command python3 "python3 on PATH"
exit /b 0

:try_py_launcher
set "CANDIDATE_PYTHON="
for /f "delims=" %%P in ('py -%~1 -c "import sys; print(sys.executable)" 2^>nul') do set "CANDIDATE_PYTHON=%%P"
if "%CANDIDATE_PYTHON%"=="" exit /b 0

call :check_python_compatible "%CANDIDATE_PYTHON%"
if errorlevel 1 exit /b 0

set "PYTHON_CMD=%CANDIDATE_PYTHON%"
set "PYTHON_SOURCE=%~2"
exit /b 0

:try_python_path
if not exist "%~1" exit /b 0

call :check_python_compatible "%~1"
if errorlevel 1 exit /b 0

set "PYTHON_CMD=%~1"
set "PYTHON_SOURCE=%~2"
exit /b 0

:try_python_command
set "CANDIDATE_PYTHON="
for /f "delims=" %%P in ('%~1 -c "import sys; v=sys.version_info; ok=(v.major == 3 and v.minor in (12, 13)); print(sys.executable) if ok else sys.exit(1)" 2^>nul') do set "CANDIDATE_PYTHON=%%P"
if "%CANDIDATE_PYTHON%"=="" exit /b 0

set "PYTHON_CMD=%CANDIDATE_PYTHON%"
set "PYTHON_SOURCE=%~2"
exit /b 0

:check_python_compatible
"%~1" -c "import sys; v=sys.version_info; sys.exit(0 if (v.major == 3 and v.minor in (12, 13)) else 1)" >nul 2>&1
exit /b %ERRORLEVEL%

:install_python_313
echo No supported Python runtime was found.
echo Trying to install Python 3.13 with winget ...

where winget >nul 2>&1
if errorlevel 1 (
    echo [ERROR] winget is not available on this computer.
    exit /b 1
)

call winget install --id Python.Python.3.13 --source winget --scope user --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 exit /b 1

exit /b 0

:ensure_release_venv
if exist "%VENV_PYTHON%" (
    call :check_python_compatible "%VENV_PYTHON%"
    if not errorlevel 1 exit /b 0

    echo Removing incompatible release virtual environment ...
    rmdir /s /q "%VENV_DIR%"
    if errorlevel 1 exit /b 1
)

echo Creating release virtual environment ...
"%~1" -m venv "%VENV_DIR%"
if errorlevel 1 exit /b 1

"%VENV_PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip is not available in the release virtual environment.
    exit /b 1
)

exit /b 0

:ensure_build_dependencies
"%~1" -c "import PyInstaller, pystray, PIL.Image, hid, win32com.client; print('dependency_check_ok')" >nul 2>&1
if not errorlevel 1 exit /b 0

echo Installing build dependencies from requirements.txt ...
"%~1" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip is not available for the selected Python.
    echo Reinstall Python and keep the pip option enabled.
    exit /b 1
)

"%~1" -m pip install --upgrade -r requirements.txt
if errorlevel 1 exit /b 1

"%~1" -c "import PyInstaller, pystray, PIL.Image, hid, win32com.client; print('dependency_check_ok')"
exit /b %ERRORLEVEL%

:run_build
echo Running PyInstaller ...
if exist build\Lumina rmdir /s /q build\Lumina
if exist dist_release\Lumina rmdir /s /q dist_release\Lumina

"%~1" -c "import sys; sys.path.insert(0, r'src'); import auto_dim_screen as m; m.write_tray_icon_to_ico(r'assets\Lumina.ico')"
if errorlevel 1 exit /b 1

"%~1" -m PyInstaller --clean --noconfirm --distpath dist_release tools\Lumina.spec
if errorlevel 1 exit /b 1

"%~1" tools\write_release_readme.py
exit /b %ERRORLEVEL%
