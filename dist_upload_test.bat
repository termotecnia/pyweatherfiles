@echo off
REM dist_upload_test.bat
REM Este script sube las distribuciones del paquete al repositorio de PRUEBAS (TestPyPI).
REM Asume que el archivo .pypirc está correctamente configurado.

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

ECHO --- [Paso 1 de 2] Verificando que el directorio 'dist' existe...
IF NOT EXIST dist (
    ECHO ERROR: El directorio 'dist' no fue encontrado.
    ECHO Por favor, construye el paquete primero ejecutando: dist_build_package.bat
    PAUSE
    EXIT /B 1
)

dir /b dist\* >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO ERROR: El directorio 'dist' no contiene artefactos para subir.
    ECHO Por favor, ejecuta primero: dist_build_package.bat
    PAUSE
    EXIT /B 1
)

%PYTHON_CMD% -m twine --version >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO ERROR: El modulo 'twine' no esta instalado en este interprete.
    ECHO Sugerencia: %PYTHON_CMD% -m pip install --upgrade twine
    PAUSE
    EXIT /B 1
)

ECHO.
ECHO --- [Paso 2 de 2] Subiendo distribuciones a TestPyPI...
%PYTHON_CMD% -m twine upload --repository testpypi --skip-existing dist/* --verbose
IF ERRORLEVEL 1 (
    ECHO ERROR: La subida a TestPyPI fallo.
    PAUSE
    EXIT /B 1
)

ECHO.
ECHO --- Proceso completado ---
ECHO Revisa tu paquete en: https://test.pypi.org/project/pyweatherfiles/
PAUSE