@echo off
REM ============================================================
REM   RGSSA Catalog Tool — one-click build
REM   Produces:  dist\RGSSA Catalog Tool.exe  (single file)
REM ============================================================
setlocal
cd /d "%~dp0"

echo [1/3] Ensuring build tools + dependencies...
python -m pip install --quiet --upgrade pyinstaller PySide6 dashscope openpyxl Pillow
if errorlevel 1 ( echo FAILED installing deps & pause & exit /b 1 )

echo [2/3] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo [3/3] Building exe (this takes a few minutes)...
python -m PyInstaller --noconfirm "RGSSA_Catalog.spec"

REM NOTE: PyInstaller may exit non-zero with a 'set_exe_build_timestamp'
REM PermissionError. That is a HARMLESS Windows Defender file-lock on the
REM freshly-built exe — the exe itself is already complete. So we judge
REM success by whether the exe actually exists, not by the exit code.
if exist "dist\RGSSA Catalog Tool.exe" (
    echo.
    echo ============================================================
    echo   DONE.  Your app is:
    echo   "%~dp0dist\RGSSA Catalog Tool.exe"
    echo   Double-click it to run. No Python needed on the target PC.
    echo   ^(Any 'set_exe_build_timestamp' warning above is harmless.^)
    echo ============================================================
    REM Auto-sign if Azure Trusted Signing is configured locally.
    if exist "signing.config.bat" (
        echo.
        echo [*] signing.config.bat found — signing the exe...
        call "sign.bat"
    ) else (
        echo.
        echo [i] Not signed. To remove McAfee/SmartScreen blocks, set up
        echo     Azure Trusted Signing ^(see README^) then run sign.bat.
    )
) else (
    echo.
    echo BUILD FAILED — no exe produced.  See messages above.
)
pause
