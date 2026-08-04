@echo off
REM git_push_external.bat
REM Pushes the current branch to 'origin' using a plain external terminal
REM (not the IDE). JetBrains IDEs run git with '-c credential.helper=',
REM which bypasses the system-wide Git Credential Manager and relies on the
REM IDE's own internal OAuth session instead. After transferring a repo to a
REM different GitHub account/organization, that cached IDE session can go
REM stale and push fails with a misleading "remote: Repository not found",
REM even though the same user has correct write access. Running the push
REM from here forces a fresh Git Credential Manager browser login and avoids
REM the issue entirely.
REM
REM Usage:
REM   git_push_external.bat                 -> pushes the current branch
REM   git_push_external.bat some-branch-name -> pushes that branch explicitly

cd /d "%~dp0"

set "BRANCH_NAME=%~1"

if "%BRANCH_NAME%"=="" (
    for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set "BRANCH_NAME=%%b"
)

if "%BRANCH_NAME%"=="" (
    ECHO ERROR: Could not determine the current branch. Are you inside a git repository?
    PAUSE
    EXIT /B 1
)

if "%BRANCH_NAME%"=="HEAD" (
    ECHO ERROR: You are in a detached HEAD state, not on a branch.
    ECHO Checkout a branch first, or pass one explicitly:
    ECHO   git_push_external.bat branch-name
    PAUSE
    EXIT /B 1
)

ECHO ==========================================================
ECHO Pushing branch '%BRANCH_NAME%' to origin
ECHO ==========================================================
ECHO This runs a plain 'git push' from outside the IDE, using the system-wide
ECHO Git Credential Manager instead of the IDE's internal OAuth integration.
ECHO If a browser window opens, complete the GitHub login there.
ECHO.

git push origin %BRANCH_NAME%
IF ERRORLEVEL 1 (
    ECHO.
    ECHO ERROR: git push failed. See the message above for details.
    PAUSE
    EXIT /B 1
)

ECHO.
ECHO --- Push completed successfully ---
PAUSE

