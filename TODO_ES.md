# TODO.md

Documento para registrar las tareas pendientes del proyecto `pyweatherfiles`. Marcar con `[x]` cuando se complete una tarea y mover el detalle relevante a `README.md`/`README_ES.md` si procede.

> 🇬🇧 English version: [`TODO.md`](TODO.md).

---

## Pendientes

### 1. [ ] Integrar el módulo de obtención de datos climáticos (pendiente de recibir)

- **Estado:** bloqueado — a la espera de recibir el módulo/código externo.
- **Contexto:** el repo ya tiene `pyweatherfiles/climate_processor.py` con dependencia opcional en `pvlib`. Habrá que valorar si el nuevo módulo lo sustituye, lo complementa o vive como archivo nuevo (p.ej. `pyweatherfiles/climate_data_fetcher.py`).
- **Pasos previstos una vez llegue el módulo:**
  - [ ] Revisar el código recibido (fuente de datos, formato de salida, dependencias).
  - [ ] Decidir su ubicación final dentro del paquete y su relación con `climate_processor.py`.
  - [ ] Adaptarlo a las convenciones del repo: mapeos explícitos de columnas (`datetime_col`, `col_temp`, etc.), uso de `session_manager` para persistencia si aplica, diagnósticos por consola si es coherente con el resto del paquete.
  - [ ] Añadir/actualizar dependencias en `pyproject.toml` (con manejo de `ImportError` en runtime si es una dependencia opcional, como se hace con `pvlib`, `tabulate`, `besos`, `eppy`).
  - [ ] Exponer en `pyweatherfiles/__init__.py` solo si debe formar parte de la API pública mínima.
  - [ ] Añadir un ejemplo de uso en `examples/`.
  - [ ] Documentar el flujo de datos (entrada/salida) en la documentación del punto 3.

### 2. [ ] Publicar `pyweatherfiles` en PyPI cuando todo esté listo

- **Estado:** pendiente — condicionado a cerrar los puntos 1 y 3 (o al menos dejar claro qué queda fuera del primer release).
- **Contexto:** ya existen los scripts `dist_build_package.bat`, `dist_upload_test.bat` y `dist_upload.bat`.
- **Pasos previstos:**
  - [ ] Revisar `pyproject.toml`: número de versión, lista de dependencias (incluir las que falten: `ladybug-core` es dependencia dura de varios módulos y no aparece listada; valorar `pvlib`, `tabulate`, `besos`, `eppy` como extras opcionales), clasificadores, URLs del proyecto, licencia.
  - [ ] Ejecutar `dist_build_package.bat` (limpia `dist/`, `build/`, `*.egg-info` y corre `python -m build`).
  - [ ] Publicar en TestPyPI con `dist_upload_test.bat` y validar instalación en un entorno virtual limpio (`pip install -i https://test.pypi.org/simple/ pyweatherfiles`).
  - [ ] Probar los ejemplos de `examples/` contra el paquete instalado desde TestPyPI (no desde el repo local).
  - [ ] Publicar en PyPI con `dist_upload.bat` (requiere `.pypirc`).
  - [ ] Crear el tag de versión en git y, si procede, notas de la release.

### 3. [x] Hacer la documentación del software, incluyendo un tutorial en `.ipynb`

- **Estado:** hecho (salvo el punto condicionado a la tarea 1, que sigue bloqueada).
- **Contexto:** `dist_build_docs.bat` ya asumía Sphinx (`sphinx-apidoc` + `make.bat html`); se ha recreado la carpeta `docs/` exactamente acorde a eso.
- **Lo realizado:**
  - [x] Se eligió **Sphinx** (+ `myst-nb` para páginas Markdown *y* para renderizar el notebook tutorial, + tema Furo), coherente con lo que `dist_build_docs.bat` ya esperaba. Se recrearon `docs/source/conf.py`, `docs/Makefile`, `docs/make.bat`, y el árbol de páginas (`index.md`, `installation.md`, `quickstart.md`, `tutorial.md`). Se añadió un extra `docs` en `pyproject.toml` (`pip install -e ".[docs]"`). `docs/source/api/` y `docs/build/` se generan automáticamente con el script y están excluidos de git.
  - [x] Se documentó la API pública principal: el `README.md`/`README_ES.md` ya exhaustivo (todos los módulos/clases/métodos/fórmulas) se reutiliza como páginas de "referencia completa" en el sitio Sphinx (`full_reference_en.md` / `full_reference_es.md`), más una referencia de API real generada con `autodoc`/`sphinx-apidoc` a partir de los docstrings reales (`autodoc_mock_imports` cubre las dependencias pesadas opcionales `pvlib`/`tabulate`/`besos`/`eppy`/`accim` para que la doc compile sin ellas instaladas). Se corrigieron varios docstrings mal formados (`tmy.py`, `degree_hours.py`, `epw_trend_analyzer.py`) que generaban warnings de Sphinx/docutils; el sitio ahora compila con **cero warnings**.
  - [x] Las convenciones del flujo TMY (mapeo de columnas, `data_frequency`/`cdf_method`, métodos de normalización de proximidad, alias obsoleto `'sawaqed'`) ya estaban cubiertas en el §3 del README y ahora también forman parte de la referencia Sphinx.
  - [x] Se creó `examples/tutorial_pyweatherfiles.ipynb`: cubre `TMYGenerator` → `HourlyEPWConverter` → `DegreeHoursCalculator` → `EpwBatchAnalyzer` → `EpwTrendAnalyzer`, usando un **dataset horario sintético reproducible** (semilla aleatoria fija, mismos nombres de columna que el fichero real de Sevilla) más los ficheros IDF/EPW reales ya versionados en el repo (`SF_Detached_D_min_South.idf`, `longterm_epw/*.epw`) — ejecutable íntegramente desde un clon nuevo, sin datos externos/no versionados. Ejecutado de principio a fin con `nbconvert` (0 errores) y guardado con salidas/gráficos reales incrustados.
  - [x] El notebook ahora se **renderiza directamente dentro del sitio Sphinx** (no solo como enlace de descarga): `docs/source/conf.py` copia `examples/tutorial_pyweatherfiles.ipynb` a `docs/source/` en tiempo de build (la fuente única de verdad sigue en `examples/`) y `myst-nb` lo renderiza con `nb_execution_mode="off"`, reutilizando las salidas/gráficos ya guardados en el notebook en vez de re-ejecutar el pipeline completo en cada build de la doc.
  - [x] Se añadió `.readthedocs.yaml` (configuración de Sphinx en `docs/source/conf.py`, instala el paquete con el extra `docs`) para poder construir el sitio en [Read the Docs](https://readthedocs.org/); se añadió el badge de RTD + enlace en `README.md`/`README_ES.md` (el proyecto aún debe *importarse* en readthedocs.org por un administrador de la organización de GitHub para quedar publicado en `https://pyweatherfiles.readthedocs.io/`).
  - [x] Se enlazó la documentación y el tutorial desde `README.md` y `README_ES.md` (banner superior).
  - [ ] Módulo climático de la tarea 1: sigue bloqueado (tarea 1 no iniciada); no hay nada que documentar hasta que se integre.
- **Correcciones colaterales realizadas de paso (ver `pyweatherfiles/degree_hours.py`):** se sustituyeron varios `print()` que usaban la flecha Unicode `→`, la cual provocaba `UnicodeEncodeError` en consolas Windows con la página de códigos `cp1252` (detectado al validar el notebook del tutorial).

### 4. [ ] Si se integra el módulo climático de la tarea 1, ampliar la documentación/tutorial en consecuencia

- **Estado:** aplazado — depende íntegramente de la tarea 1 (sigue bloqueada, módulo externo no recibido).
- **Pasos previstos una vez se desbloquee la tarea 1:** añadir el nuevo módulo a la referencia de API de Sphinx (autodoc lo detectará automáticamente en cuanto exista), documentar su flujo de datos, y añadir una sección/celda al notebook `examples/tutorial_pyweatherfiles.ipynb` si procede.

---

## Notas de uso de este documento

- Añadir nuevas tareas con una fecha y, si aplica, referencias a archivos/módulos afectados.
- Al completar una tarea, marcar la casilla principal `[ ]` → `[x]` y las subtareas correspondientes.
- Si una tarea pendiente deja de ser relevante, no borrarla: tacharla o moverla a una sección "Descartadas" con el motivo.

---

*Última actualización: 2026-07-19*


