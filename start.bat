@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "PS_SCRIPT=%ROOT_DIR%scripts\quick-start.ps1"

if not exist "%PS_SCRIPT%" (
    echo Cannot find script: %PS_SCRIPT%
    pause
    exit /b 1
)

echo.
echo SuperCode Quick Start
echo.
echo 1. Install frontend and backend dependencies
echo 2. Install dependencies and start frontend + backend
echo 3. Prepare backend only
echo 4. Prepare frontend only
echo 5. Auto-install missing tools, then install dependencies
echo 6. Auto-install missing tools, then install and start all
echo 0. Exit
echo.

choice /c 1234560 /n /m "Select an option: "
set "CHOICE=%errorlevel%"

if "%CHOICE%"=="1" goto install
if "%CHOICE%"=="2" goto install_and_start
if "%CHOICE%"=="3" goto backend_only
if "%CHOICE%"=="4" goto frontend_only
if "%CHOICE%"=="5" goto autoinstall
if "%CHOICE%"=="6" goto autoinstall_and_start
if "%CHOICE%"=="7" goto end

echo.
echo Invalid option.
pause
exit /b 1

:install
powershell -ExecutionPolicy Bypass -File "%PS_SCRIPT%" -InstallOnly
goto done

:install_and_start
powershell -ExecutionPolicy Bypass -File "%PS_SCRIPT%" -StartBackend -StartFrontend
goto done

:backend_only
powershell -ExecutionPolicy Bypass -File "%PS_SCRIPT%" -BackendOnly -InstallOnly
goto done

:frontend_only
powershell -ExecutionPolicy Bypass -File "%PS_SCRIPT%" -FrontendOnly -InstallOnly
goto done

:autoinstall
powershell -ExecutionPolicy Bypass -File "%PS_SCRIPT%" -AutoInstallTools -InstallOnly
goto done

:autoinstall_and_start
powershell -ExecutionPolicy Bypass -File "%PS_SCRIPT%" -AutoInstallTools -StartBackend -StartFrontend
goto done

:done
echo.
echo Finished.
pause
exit /b %errorlevel%

:end
endlocal
exit /b 0
