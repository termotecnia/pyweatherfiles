@echo off
REM dist_upload.bat
REM Este script sube las distribuciones del paquete al repositorio OFICIAL de PyPI.
REM Asume que el archivo .pypirc está correctamente configurado.

ECHO --- [Paso 1 de 2] Verificando que el directorio 'dist' existe...
IF NOT EXIST dist (
    ECHO ERROR: El directorio 'dist' no fue encontrado.
    ECHO Por favor, construye el paquete primero ejecutando: dist_build_package.bat
    PAUSE
    EXIT /B 1
)

ECHO.
ECHO --- [Paso 2 de 2] Subiendo distribuciones a PyPI...
REM Al no especificar --repository, twine usa la configuración 'pypi' por defecto.
twine upload dist/*

ECHO.
ECHO --- Proceso completado ---
ECHO ¡Tu paquete debería estar disponible públicamente en PyPI!
PAUSE