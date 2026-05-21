@echo off
REM build_docs.bat
REM Este script automatiza la generación de la documentación de pyweatherfiles.
REM Debe ser ejecutado desde la raíz del proyecto.

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

IF NOT EXIST docs (
	ECHO ERROR: No existe el directorio 'docs'.
	ECHO Modo estricto activo: no se puede continuar sin documentacion configurada.
	PAUSE
	EXIT /B 1
)

IF NOT EXIST docs\make.bat (
	ECHO ERROR: No existe 'docs\make.bat'.
	ECHO Verifica que Sphinx este inicializado en el directorio docs.
	PAUSE
	EXIT /B 1
)

%PYTHON_CMD% -m sphinx --version >nul 2>&1
IF ERRORLEVEL 1 (
	ECHO ERROR: Sphinx no esta instalado en este interprete.
	ECHO Sugerencia: %PYTHON_CMD% -m pip install --upgrade sphinx
	PAUSE
	EXIT /B 1
)

ECHO --- [Paso 1 de 3] Limpiando compilaciones anteriores...
REM Borra el contenido de la carpeta de salida para asegurar una compilación limpia.
REM El flag /Q ejecuta el borrado sin pedir confirmación.
IF EXIST docs\build rmdir /s /q docs\build

ECHO.
ECHO --- [Paso 2 de 3] Generando archivos .rst de la API con sphinx-apidoc...
REM Ejecuta sphinx-apidoc para generar/actualizar los archivos .rst desde el código fuente.
REM -o docs\source\api: Directorio de salida para los archivos .rst.
REM pyweatherfiles: Ruta al paquete que se va a documentar.
REM --force: Sobrescribe los archivos existentes.
%PYTHON_CMD% -m sphinx.ext.apidoc --force -o docs\source\api pyweatherfiles
IF ERRORLEVEL 1 (
	ECHO ERROR: Fallo la generacion de archivos .rst con sphinx-apidoc.
	PAUSE
	EXIT /B 1
)

ECHO.
ECHO --- [Paso 3 de 3] Construyendo la documentación HTML con Sphinx...
REM Cambia al directorio 'docs' y ejecuta el comando 'make html'.
cd docs
IF ERRORLEVEL 1 (
	ECHO ERROR: No se pudo entrar en el directorio docs.
	PAUSE
	EXIT /B 1
)

call make.bat html
IF ERRORLEVEL 1 (
	ECHO ERROR: Fallo la construccion HTML con Sphinx.
	cd ..
	PAUSE
	EXIT /B 1
)

cd ..

ECHO.
ECHO --- Proceso completado ---
ECHO La documentacion HTML ha sido generada en: docs\build\html\index.html
PAUSE