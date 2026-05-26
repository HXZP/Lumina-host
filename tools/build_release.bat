@echo off
set "TOOLS_DIR=%~dp0"
for %%I in ("%TOOLS_DIR%..") do set "APP_DIR=%%~fI"
cd /d "%APP_DIR%"

set "PYTHON_CMD="
set "PYTHON_SOURCE="
set "BUILD_ERR=1"

call :try_python_cmd "%APP_DIR%\.venv\Scripts\python.exe" "Lumina-host venv"
if not "%PYTHON_CMD%"=="" goto use_python_cmd
call :try_python_cmd "%APP_DIR%\..\monitor\.venv\Scripts\python.exe" "legacy monitor venv"
if not "%PYTHON_CMD%"=="" goto use_python_cmd
call :try_python_cmd "%APP_DIR%\..\.venv\Scripts\python.exe" "script venv"
if not "%PYTHON_CMD%"=="" goto use_python_cmd
call :try_python_cmd "%APP_DIR%\..\..\.venv\Scripts\python.exe" "project venv"
if not "%PYTHON_CMD%"=="" goto use_python_cmd
call :try_python_cmd "%APP_DIR%\..\..\..\.venv\Scripts\python.exe" "workspace project venv"
if not "%PYTHON_CMD%"=="" goto use_python_cmd
call :try_python_cmd "%APP_DIR%\..\..\..\..\.venv\Scripts\python.exe" "workspace venv"
if not "%PYTHON_CMD%"=="" goto use_python_cmd

where py >nul 2>&1
if %errorlevel%==0 goto use_py
where python >nul 2>&1
if %errorlevel%==0 goto use_python

echo [ERROR] Neither py nor python is in PATH.
echo Install Python from python.org and tick Add python.exe to PATH.
goto end

:use_python_cmd
echo Running PyInstaller via %PYTHON_SOURCE% ...
if exist build\Lumina rmdir /s /q build\Lumina
if exist dist_release\Lumina rmdir /s /q dist_release\Lumina
"%PYTHON_CMD%" -c "import PyInstaller, pystray, PIL.Image, hid, win32com.client; print('dependency_check_ok')"
if errorlevel 1 goto build_fail
"%PYTHON_CMD%" -c "import sys; sys.path.insert(0, r'src'); import auto_dim_screen as m; m.write_tray_icon_to_ico(r'assets\Lumina.ico')"
if errorlevel 1 goto build_fail
"%PYTHON_CMD%" -m PyInstaller --clean --noconfirm --distpath dist_release tools\Lumina.spec
set BUILD_ERR=%ERRORLEVEL%
if not "%BUILD_ERR%"=="0" goto after_build
"%PYTHON_CMD%" tools\write_release_readme.py
set BUILD_ERR=%ERRORLEVEL%
goto after_build

:use_py
echo Running PyInstaller via py -3 ...
if exist build\Lumina rmdir /s /q build\Lumina
if exist dist_release\Lumina rmdir /s /q dist_release\Lumina
py -3 -c "import PyInstaller, pystray, PIL.Image, hid, win32com.client; print('dependency_check_ok')"
if errorlevel 1 goto build_fail
py -3 -c "import sys; sys.path.insert(0, r'src'); import auto_dim_screen as m; m.write_tray_icon_to_ico(r'assets\Lumina.ico')"
if errorlevel 1 goto build_fail
py -3 -m PyInstaller --clean --noconfirm --distpath dist_release tools\Lumina.spec
set BUILD_ERR=%ERRORLEVEL%
if not "%BUILD_ERR%"=="0" goto after_build
py -3 tools\write_release_readme.py
set BUILD_ERR=%ERRORLEVEL%
goto after_build

:use_python
echo Running PyInstaller via python ...
if exist build\Lumina rmdir /s /q build\Lumina
if exist dist_release\Lumina rmdir /s /q dist_release\Lumina
python -c "import PyInstaller, pystray, PIL.Image, hid, win32com.client; print('dependency_check_ok')"
if errorlevel 1 goto build_fail
python -c "import sys; sys.path.insert(0, r'src'); import auto_dim_screen as m; m.write_tray_icon_to_ico(r'assets\Lumina.ico')"
if errorlevel 1 goto build_fail
python -m PyInstaller --clean --noconfirm --distpath dist_release tools\Lumina.spec
set BUILD_ERR=%ERRORLEVEL%
if not "%BUILD_ERR%"=="0" goto after_build
python tools\write_release_readme.py
set BUILD_ERR=%ERRORLEVEL%
goto after_build

:after_build
if not "%BUILD_ERR%"=="0" goto build_fail
echo.
echo Done. Output folder:
echo %APP_DIR%\dist_release\Lumina
goto end

:build_fail
set BUILD_ERR=1
echo.
echo BUILD FAILED.
echo Install deps with: pip install -r requirements.txt
echo If access is denied, close running Lumina.exe and all Explorer windows opened in dist.

:end
echo.
pause
exit /b %BUILD_ERR%

:try_python_cmd
if not exist "%~1" exit /b 0
"%~1" -c "import PyInstaller, pystray, PIL.Image, hid, win32com.client" >nul 2>&1
if errorlevel 1 (
    echo Skipping %~2: missing build dependencies.
    exit /b 0
)
set "PYTHON_CMD=%~1"
set "PYTHON_SOURCE=%~2"
exit /b 0
