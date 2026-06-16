@echo off
REM ============================================================
REM   Azure Trusted Signing — your account settings
REM
REM   1) Copy this file to:  signing.config.bat
REM   2) Fill in the three values below (from Azure portal).
REM   These three are NOT secrets — they're just names/URLs.
REM   The actual login secret is handled separately (see README).
REM ============================================================

REM Region endpoint of your Trusted Signing account.
REM e.g. East US -> https://eus.codesigning.azure.net/
REM      West US3 -> https://wus3.codesigning.azure.net/
REM      West Europe -> https://weu.codesigning.azure.net/
set "TS_ENDPOINT=https://eus.codesigning.azure.net/"

REM The Trusted Signing *account* name you created in Azure.
set "TS_ACCOUNT=your-trusted-signing-account"

REM The *certificate profile* name under that account.
set "TS_PROFILE=your-certificate-profile"
