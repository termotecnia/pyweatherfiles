@echo off
REM build.bat
REM This script cleans old artifacts and builds the package for distribution.

set "PYTHON_CMD="
where py >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py"

if not defined PYTHON_CMD (
    where python >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    ECHO ERROR: No se encontro un interprete Python en PATH ^(ni 'py' ni 'python'^).
    PAUSE
    EXIT /B 1
)

ECHO --- [Step 1 of 3] Cleaning previous build artifacts...
REM Delete the contents of old build folders to ensure a clean build.
REM The /s flag is for subdirectories, and /q is for quiet mode (no confirmation).
IF EXIST dist rmdir /s /q dist
IF EXIST build rmdir /s /q build
FOR /d %%d IN (*.egg-info) DO rmdir /s /q "%%d"

ECHO.
ECHO --- [Step 2 of 3] Building the package using 'python -m build'...
%PYTHON_CMD% -m build --version >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO El modulo 'build' no esta instalado en este interprete. Instalando...
    %PYTHON_CMD% -m pip install build
    IF ERRORLEVEL 1 (
        ECHO ERROR: No se pudo instalar el modulo 'build'.
        ECHO Sugerencia: ejecuta manualmente '%PYTHON_CMD% -m pip install --upgrade pip build'
        PAUSE
        EXIT /B 1
    )
)

%PYTHON_CMD% -m build
IF ERRORLEVEL 1 (
    ECHO ERROR: El comando de build fallo.
    PAUSE
    EXIT /B 1
)

ECHO.
ECHO --- [Step 3 of 3] Verifying build results...
IF NOT EXIST dist (
    ECHO ERROR: The 'dist' directory was not created. The build may have failed.
    PAUSE
    EXIT /B 1
)

ECHO.
ECHO --- Process complete ---
ECHO The distribution files have been successfully created in the 'dist' directory.
PAUSE