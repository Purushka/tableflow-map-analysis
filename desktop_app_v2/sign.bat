@echo off
REM ============================================================
REM   Sign  dist\RGSSA Catalog Tool.exe  with Azure Trusted Signing
REM   Prereqs (one-time): see README_打包与使用.md  "Azure 签名设置"
REM ============================================================
setlocal
cd /d "%~dp0"

set "EXE=dist\RGSSA Catalog Tool.exe"
set "SIGN=%USERPROFILE%\.dotnet\tools\sign.exe"

if not exist "%EXE%" ( echo [x] No exe found. Run build.bat first. & pause & exit /b 1 )
if not exist "signing.config.bat" (
    echo [x] signing.config.bat not found.
    echo     Copy signing.config.example.bat to signing.config.bat and fill it in.
    pause & exit /b 1
)
if not exist "%SIGN%" (
    echo [*] Installing the 'sign' tool ^(one-time^)...
    dotnet tool install --global sign --prerelease
)

call "signing.config.bat"
echo [*] Account=%TS_ACCOUNT%  Profile=%TS_PROFILE%
echo [*] Endpoint=%TS_ENDPOINT%
echo.

REM Auth: the 'sign' tool uses Azure DefaultAzureCredential.
REM Easiest interactive path: run `az login` first (see README).
REM CI path: set AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET.

"%SIGN%" code trusted-signing "%EXE%" ^
    --trusted-signing-endpoint "%TS_ENDPOINT%" ^
    --trusted-signing-account "%TS_ACCOUNT%" ^
    --trusted-signing-certificate-profile "%TS_PROFILE%" ^
    --description "RGSSA Catalog Tool" ^
    --description-url "https://www.rgssa.org.au/"

if errorlevel 1 ( echo. & echo [x] SIGNING FAILED — see messages above. & pause & exit /b 1 )

echo.
echo [*] Verifying signature...
set "SIGNTOOL="
for /f "delims=" %%i in ('dir /b /s /a-d "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe" 2^>nul') do set "SIGNTOOL=%%i"
if defined SIGNTOOL (
    "%SIGNTOOL%" verify /pa /v "%EXE%"
) else (
    echo [i] signtool.exe not found — skipping verify ^(signing still succeeded^).
)

echo.
echo ============================================================
echo   SIGNED OK:  %~dp0%EXE%
echo ============================================================
pause
