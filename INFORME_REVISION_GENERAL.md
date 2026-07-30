# Informe de revisión general — `pyweatherfiles`

> **Fecha de la revisión:** 2026-07-30
> **Alcance:** Revisión estática de todo el paquete `pyweatherfiles/` (9 módulos), `pyproject.toml`, scripts de la raíz, `analysis_scripts/`, `examples/`, documentación (`README.md`, `README_ES.md`, `AGENTS.md`, `TODO.md`) y estructura general del repositorio.
> **Método:** Lectura completa de los 9 módulos del paquete (~12.900 líneas de Python), búsquedas dirigidas (`grep`) de patrones duplicados, y comparación cruzada entre documentación y código real.
> **No incluido:** Ejecución de los scripts (no se han corrido pipelines reales ni se ha instalado el entorno), auditoría de seguridad, ni revisión de los notebooks/figuras generados.

---

## 1. Resumen ejecutivo

`pyweatherfiles` es un paquete maduro y funcionalmente muy rico (generación de TMY, conversión EPW/MET, grados-hora, análisis de tendencias climáticas, limpieza de series). El nivel de **documentación de docstrings y del `README.md`** es notablemente alto para un proyecto de este tamaño. Sin embargo, la revisión ha detectado varios problemas estructurales que conviene abordar antes de la publicación en PyPI (ya prevista en `TODO.md`):

| Categoría | Severidad | Resumen |
|---|---|---|
| **Duplicación de código entre convertidores EPW/MET** | 🔴 Alta | Al menos 4 bloques de lógica casi idéntica copiados entre `hourly_epw_converter.py` y `met_epw_converter.py` (presión barométrica, offset *point-in-time* de Ladybug, mapa de 15 campos EPW no usados, reconstrucción solar vía `Sunpath`). |
| **Ausencia total de tests automatizados** | 🔴 Alta | No existe carpeta `tests/`, ni `pytest`/`unittest` en `pyproject.toml`, ni CI. Toda la "validación" depende de ejecutar scripts manualmente y de los `validation_step*` en tiempo de ejecución. |
| **Archivos monolíticos ("God modules")** | 🟠 Media-Alta | `tmy.py` (4.102 líneas, 1 clase con ~70 métodos), `degree_hours.py` (2.616 líneas, 3 clases), `epw_trend_analyzer.py` (1.812 líneas). |
| **Documentación de agentes desactualizada** | 🟠 Media | `AGENTS.md` no menciona `epw_trend_analyzer`, `epw_comparator`, `epw_utils` ni el contenido real de `__init__.py`/`pyproject.toml` (el `README.md` sí está al día). |
| **Solapamiento funcional entre analizadores de tendencia** | 🟠 Media | `EpwTrendAnalyzer` (módulo propio) y `EpwGroupTrendAnalyzer` (dentro de `degree_hours.py`) reimplementan cada uno su propia lógica de descubrimiento de ficheros, regresión OLS por grupo/ciudad y *grid plots*, en vez de compartir una base común. |
| **Dependencias opcionales mal declaradas** | 🟡 Media-Baja | `pvlib` y `tabulate` se importan sin `try/except` (a diferencia de `ladybug-core`, `besos`, `eppy`), y ninguna de las 4 (+`accim`) figura como *extra* en `pyproject.toml`. |
| **Higiene de scripts de la raíz** | 🟡 Baja | `generating epws seville.py` contiene una ruta absoluta de usuario (`sys.path.extend(['D:\\Python\\pyweatherfiles'])`) y ~40 líneas de código comentado muerto. |
| **Consistencia de idioma/estilo** | 🟡 Baja | Docstrings en inglés, pero gran parte de los `print()` de diagnóstico están en español (sobre todo en `epw_comparator.py`, `met_epw_converter.py`, `degree_hours.py`). No es un bug, pero dificulta la consistencia si el proyecto se internacionaliza. |

**Buenas prácticas ya presentes que conviene preservar:** `session_manager.py` es un módulo transversal bien diseñado (persistencia `.pkl`/`.json` reutilizada por 6 módulos distintos sin duplicar lógica), los `validation_step*` dataframes dan trazabilidad excelente al pipeline de TMY, y el `README.md` es una referencia técnica completa y correcta.

---

## 2. Mapa del proyecto (inventario)

| Módulo | Líneas | Clases/funciones públicas principales | ¿Exportado en `__init__.py`? |
|---|---|---|---|
| `tmy.py` | 4.102 | `TMYGenerator` | ✅ |
| `degree_hours.py` | 2.616 | `DegreeHoursCalculator`, `EpwBatchAnalyzer`, `EpwGroupTrendAnalyzer` | ✅ (solo `DegreeHoursCalculator`) |
| `epw_trend_analyzer.py` | 1.812 | `EpwTrendAnalyzer`, `TrendConfig`, `OutputConfig`, `run_analysis` | ✅ |
| `hourly_epw_converter.py` | 1.023 | `HourlyEPWConverter`, `BatchHourlyEPWConverter` | ❌ (import explícito) |
| `met_epw_converter.py` | 755 | `convert_met_to_epw`, `convert_epw_to_met` | ❌ |
| `climate_processor.py` | 721 | `ClimateProcessor` | ❌ |
| `session_manager.py` | 564 | `save_object_session`, `save_function_session`, `load_session` | ❌ (import interno) |
| `epw_comparator.py` | 424 | `compare_epw_files`, `create_comparison_dataframe`, `create_comparison_hourly_dataframe`, `explore_epw_structure` | ❌ |
| `epw_utils.py` | 99 | `classify_epw_files` | ❌ (uso interno) |

**Total:** ~12.916 líneas de código en 9 módulos, **0 líneas de tests**.

### 2.1 Discrepancia detectada: `AGENTS.md` vs. realidad

`AGENTS.md` (el documento de contexto para agentes IA) afirma:

> *"The package API exported in `pyweatherfiles/__init__.py` is minimal: `TMYGenerator` and `DegreeHoursCalculator`"*
> *"`pyproject.toml` currently lists only pandas/numpy/scipy/matplotlib/openpyxl"*

Ambas afirmaciones están **desactualizadas**:

- `__init__.py` real también exporta `EpwTrendAnalyzer`, `TrendConfig`, `OutputConfig`.
- `pyproject.toml` real también incluye `seaborn`, `ladybug-core`, `pyyaml` como dependencias obligatorias, y no menciona `pvlib`/`tabulate`/`besos`/`eppy` como opcionales pese a que 3 módulos dependen de ellas.
- `AGENTS.md` tampoco menciona los módulos `epw_trend_analyzer.py`, `epw_comparator.py`, `epw_utils.py`.

El propio `README.md` (§1.2, §2, §11) **sí** documenta correctamente todo esto. Como `AGENTS.md` es justamente el documento que orienta a agentes/asistentes IA (incluyéndome a mí en esta sesión) sobre "qué hay en el repo", su desactualización es un riesgo real de que futuras contribuciones automatizadas trabajen con una imagen incorrecta del proyecto.

---

## 3. Duplicación de código y solapamiento funcional (hallazgo principal)

Esta sección responde directamente a la pregunta de si existen "ítems cuyas funciones se solapen". Se han encontrado **duplicaciones literales de lógica** (no solo solapamiento conceptual) entre `hourly_epw_converter.py` y `met_epw_converter.py`, ambos módulos "hoja" de conversión a EPW que evolucionaron en paralelo.

### 3.1 Duplicación literal de funciones físicas/EPW

| Función/bloque | Ubicación A | Ubicación B | Naturaleza |
|---|---|---|---|
| **Presión atmosférica barométrica** | `hourly_epw_converter.py::HourlyEPWConverter._calculate_atmos_pressure` (L.371-386, método de instancia, usa `self.elev`) | `met_epw_converter.py::_calculate_atmos_pressure` (L.208-233, función libre, parámetro `elevation_m`) | **Fórmula idéntica** (constantes `p0=101325, L=0.0065, T0=288.15, g=9.80665, M=0.0289644, R=8.31447` repetidas literalmente en ambos sitios). |
| **Corrección de offset *point-in-time* de Ladybug** | `hourly_epw_converter.py::HourlyEPWConverter._set_epw_values` (L.388-411) | `met_epw_converter.py::_set_epw_values` (L.281-309) | **Lógica idéntica** (`shifted = [new_vals[-1]] + list(new_vals[:-1])`). Además, `met_epw_converter.py` tiene también `_get_epw_values` (L.312-333, la operación inversa) que no existe en `hourly_epw_converter.py`, pese a que sería igual de útil ahí. |
| **Mapa de 15 campos EPW "no usados por EnergyPlus"** | `hourly_epw_converter.py::transform_to_epw` (`unused_fields_mapping`, L.575-591) | `met_epw_converter.py::convert_met_to_epw` (`unused_fields_mapping`, L.580-596) | **Diccionario y bucle de aplicación prácticamente idénticos** (mismos 15 campos, mismos valores "missing": `9999`, `999999`, `99`, `0.999`, etc.). |
| **Reconstrucción de radiación difusa/directa vía posición solar exacta** | `hourly_epw_converter.py` (cálculo de DHI desde GHI/DNI, `Sunpath`, evaluado en `hour + 0.5`, L.531-552) | `met_epw_converter.py` (cálculo de GHI/DNI desde componentes horizontales, `Sunpath`, evaluado en `hour - 0.5`, L.517-560) | **Mismo patrón** (zenith vía `Sunpath.calculate_sun`, `cos_zenith`, protección `cos_zenith <= 0.01`), aplicado en direcciones inversas. ⚠️ Nótese que el punto de evaluación horaria difiere (`+0.5` vs. `-0.5`) entre ambos módulos sin que quede documentado el motivo — **riesgo de inconsistencia silenciosa** si algún día deben unificarse. |

### 3.2 Familia de fórmulas psicrométricas dispersas (relacionadas, no idénticas)

Estas no son duplicados exactos, pero son variaciones de la **misma fórmula de Magnus** repartidas en 3 módulos sin un punto único de verdad:

- `hourly_epw_converter.py::_calculate_rh(tdb, tdp)` → RH desde T y T_rocío (constantes Magnus `6.112`, `17.67`, `243.5`).
- `met_epw_converter.py::_calculate_dew_point(temp_c, rh_percent)` → inversa (T_rocío desde T y RH, constantes Magnus `17.62`, `243.12` — **nótese que usa una variante de constantes ligeramente distinta a la anterior**).
- `met_epw_converter.py::_calculate_absolute_humidity(...)` (constantes `610.78`, `7.5`, `237.3` — **una tercera variante de constantes**).
- `climate_processor.py` reimplementa también RH vía Magnus para relleno de huecos (según el análisis, con sus propias constantes `17.625`/`243.04`).

El hecho de que **cuatro variantes distintas de las constantes de Magnus** convivan en el mismo paquete (aunque cada una sea válida dentro de su rango de aplicación) es un indicio claro de que falta un módulo `_psychrometrics.py` compartido.

### 3.3 Solapamiento conceptual: `EpwTrendAnalyzer` vs. `EpwGroupTrendAnalyzer`

Ambas clases resuelven el mismo problema general — *"analizar una colección de ficheros EPW anuales, clasificados por ciudad/año, y extraer tendencias interanuales por regresión lineal, nunca agrupando climas distintos"* — pero están implementadas de forma completamente independiente:

| Aspecto | `EpwTrendAnalyzer` (`epw_trend_analyzer.py`) | `EpwGroupTrendAnalyzer` (`degree_hours.py`) |
|---|---|---|
| Descubrimiento de ficheros | Reimplementa su propio `discover_files()` con `glob` + `filename_regex` propio | Usa el helper compartido `epw_utils.classify_epw_files()` |
| Métrica analizada | Temperatura (media, P95, olas de calor) | Grados-hora (requiere `setpoint_source`, IDF o dict) + variables EPW auxiliares |
| Regresión de tendencia | `fit_city_trends()` (por ciudad) **+ `fit_global_models()`** (modelo de efectos fijos global, panel data) | Solo `compute_trends()` (por grupo, independiente) — **no tiene equivalente al modelo global de efectos fijos** |
| Gráficos | `build_city_figure`, `build_global_adjusted_figure`, `build_boxplot_figure` | `plot_variable_grid`, `plot_overview_grid` |
| Exportación | CSV/XLSX + PNG + informe Markdown/texto | CSV/XLSX + PNG |

**Conclusión:** no es una duplicación de código línea a línea, pero sí una **duplicación de diseño**: dos "motores de tendencias sobre colecciones de EPW" evolucionando en paralelo, con `EpwTrendAnalyzer` más completo (modelo de efectos fijos) que `EpwGroupTrendAnalyzer`. El propio `README.md` (§6.6) reconoce la distinción de propósito, pero no hay ninguna clase base compartida ni reutilización del descubrimiento de ficheros por parte de `EpwTrendAnalyzer`.

### 3.4 Otras repeticiones de patrón (menor severidad)

- **Exportación a Excel repetida:** el patrón `with pd.ExcelWriter(path, engine='openpyxl') as writer: df.to_excel(writer, sheet_name=...)` se reimplementa de forma independiente en `climate_processor.py` (3 métodos `export_*`), `degree_hours.py` (`DegreeHoursCalculator.export_results`, `EpwBatchAnalyzer.export`, `EpwGroupTrendAnalyzer.export_results`) y `epw_trend_analyzer.py` (`export_outputs`). Ninguno es exactamente igual, pero todos podrían apoyarse en un pequeño helper común `export_frames_to_excel(dict_de_dataframes, path)`.
- **API "step" duplicada dentro de `tmy.py`:** los 4 métodos `step_1_load_and_prepare_data` … `step_4_create_and_smooth_tmy` son wrappers de compatibilidad que delegan en los `sandia_step_*` actuales (correcto como estrategia de *deprecation*), pero suman, junto con las 6 propiedades `validation_st2_*`/`validation_st3_*`/`validation_st4_*`, más de 100 líneas dedicadas exclusivamente a compatibilidad retroactiva dentro de un archivo ya muy extenso.

---

## 4. Arquitectura y mantenibilidad

### 4.1 Archivos monolíticos ("God modules")

- **`tmy.py` (4.102 líneas, 1 sola clase `TMYGenerator`)**: mezcla en la misma clase — carga de datos, cálculo estadístico (FS, proximidad, persistencia), ensamblado, suavizado, **8 métodos de `plot_*` con matplotlib**, métodos de validación/depuración, métodos de análisis y corrección (v4.09), y las propiedades de compatibilidad retroactiva. Es el ejemplo más claro de clase con demasiadas responsabilidades (viola SRP).
- **`degree_hours.py` (2.616 líneas, 3 clases)**: `DegreeHoursCalculator`, `EpwBatchAnalyzer` y `EpwGroupTrendAnalyzer` son conceptualmente independientes (una calcula grados-hora de un EPW, la segunda compara EPWs nombrados individualmente, la tercera analiza un directorio completo clasificado) pero conviven en un único archivo.
- **`epw_trend_analyzer.py` (1.812 líneas)**: mezcla configuración (`dataclasses`), cálculo de métricas, ajuste de modelos estadísticos (incluyendo álgebra matricial manual para el modelo de efectos fijos) y generación de figuras/informes en una sola clase `EpwTrendAnalyzer`.

Estos tamaños de archivo dificultan la navegación, aumentan el coste cognitivo de cualquier cambio, y elevan el riesgo de conflictos de merge en un equipo con más de una persona trabajando en paralelo.

### 4.2 Ausencia de tests automatizados

Confirmado por búsqueda de archivos (`**/test*.py` → 0 resultados) y por `AGENTS.md` ("There is no `tests/` directory or CI config in repo"). Las consecuencias concretas para este proyecto son:

- Cualquier refactor de las duplicaciones descritas en la §3 **no se puede validar automáticamente** hoy — solo hay verificación manual vía `analysis_scripts/verify_new_tmy.py` y comparación visual de figuras.
- Las fórmulas físicas puras (barométrica, Magnus, Stefan-Boltzmann, `_compute_cdf`, estadístico FS) son **triviales de testear unitariamente** (entrada/salida numérica determinista) y ya tienen ejemplos listos en los docstrings marcados `# doctest: +SKIP` — es decir, ya existe el material para escribir los primeros tests, solo falta activarlos.
- No hay CI (no existe `.github/workflows/`), por lo que nada impide subir una regresión a `main`/PyPI.

### 4.3 Gestión de dependencias opcionales inconsistente

| Dependencia | Módulo(s) que la usan | ¿Import protegido con `try/except`? | ¿Declarada en `pyproject.toml`? |
|---|---|---|---|
| `ladybug-core` | `hourly_epw_converter`, `met_epw_converter`, `degree_hours`, `epw_comparator` | ✅ Sí, con mensaje explicativo | ✅ Sí (obligatoria) |
| `besos` / `eppy` | `degree_hours` (extracción de setpoints desde IDF) | ✅ Sí (con *fallback* de `besos` a `eppy`) | ❌ No |
| `accim` | `degree_hours` (saneo de acentos en rutas IDF) | ✅ Sí | ❌ No |
| `pvlib` | `climate_processor` | ❌ **No** — `import pvlib` directo en cabecera | ❌ No |
| `tabulate` | `epw_comparator` | ❌ **No** — `from tabulate import tabulate` directo | ❌ No |
| `pyyaml` | `epw_trend_analyzer` (`from_yaml`) | ✅ Sí | ✅ Sí (obligatoria, aunque solo la necesita una función opcional) |

`pvlib` y `tabulate` provocarán un `ImportError` "crudo" (sin mensaje explicativo) en cuanto alguien importe `climate_processor` o `epw_comparator` sin tenerlas instaladas, rompiendo la consistencia con el resto del paquete. Esto ya está anotado como pendiente en `TODO.md` (tarea 2) de cara a la publicación en PyPI, pero conviene resolverlo antes de esa publicación, no durante.

### 4.4 Higiene de scripts y del repositorio

- `generating epws seville.py` (script de referencia real citado por `AGENTS.md`) contiene `sys.path.extend(['D:\\Python\\pyweatherfiles'])` — una ruta absoluta específica de un puesto de trabajo concreto — y ~40 líneas finales comentadas (bloques de `besos`/`eppy`/EnergyPlus muertos). Al ser el script "fast start" recomendado por `AGENTS.md`, cualquier persona/agente que lo copie literalmente arrastrará ese problema.
- La carpeta `onedrive_backup/` (correctamente excluida en `.gitignore`) contiene subcarpetas con nombres poco descriptivos (`260515/`, `SS/`, `testing_260202/`, `backup/`, `files to compare v4/`) que sugieren que se usa como zona de trabajo/experimentación no estructurada. No afecta al paquete distribuido, pero sí a la higiene general del entorno de desarrollo.
- No se han encontrado marcadores `TODO`/`FIXME`/`XXX` dentro del código fuente de `pyweatherfiles/` — la deuda técnica conocida está correctamente centralizada en `TODO.md`/`TODO_ES.md`, lo cual es una buena práctica que conviene mantener.

### 4.5 Consistencia de idioma y estilo de mensajes

Los docstrings están sistemáticamente en inglés (buena consistencia), pero los mensajes de diagnóstico por consola (`print(...)`) están mayoritariamente en español en `epw_comparator.py`, `met_epw_converter.py`, `climate_processor.py` y partes de `degree_hours.py`/`hourly_epw_converter.py`, mientras que `tmy.py` y `epw_trend_analyzer.py` los tienen en inglés. No es un defecto funcional, pero si el paquete se publica en PyPI para un público internacional (como sugiere `TODO.md`, tarea 2), esta mezcla puede resultar confusa para usuarios no hispanohablantes que solo lean la salida de consola.

---

## 5. Fortalezas a preservar

Para que el plan de mejoras no se perciba como una crítica desequilibrada, se destacan explícitamente los aciertos de diseño observados:

1. **`session_manager.py`** es un ejemplo correcto de módulo transversal: 6 módulos distintos reutilizan `save_object_session`/`save_function_session`/`load_session` sin duplicar lógica de serialización, *slugging* de nombres de archivo ni *hashing*.
2. **Trazabilidad del pipeline de TMY** vía los `validation_step*`: cada paso del método Sandia queda auditado en un DataFrame accesible, lo cual es un patrón de diseño valioso para reproducibilidad científica.
3. **`README.md`/`README_ES.md`** son documentación técnica de referencia excelente y, a diferencia de `AGENTS.md`, están sincronizados con el código real.
4. **Manejo cuidadoso de la retrocompatibilidad** en `tmy.py` (alias `'sawaqed'` → `'weighted'`, métodos `step_*` deprecados con `DeprecationWarning`) — la estrategia es correcta, aunque tiene coste de mantenimiento (§3.4).
5. **Separación de responsabilidades entre `TMYGenerator` y `HourlyEPWConverter`** en cuanto a unidades (el primero es *unit-agnostic*, el segundo hace las conversiones a SI): decisión arquitectónica documentada explícitamente y bien razonada (README §3.9, §13).

---

## 6. Plan de implementación de mejoras

Plan organizado en fases incrementales, ordenadas por relación esfuerzo/impacto. Cada fase es independiente y no bloquea a las siguientes salvo que se indique lo contrario.

### Fase 0 — Higiene rápida (esfuerzo: horas — 1 día)

| # | Acción | Archivos afectados |
|---|---|---|
| 0.1 | Actualizar `AGENTS.md` para reflejar el `__init__.py` real (incluir `EpwTrendAnalyzer`/`TrendConfig`/`OutputConfig`) y la lista real de dependencias de `pyproject.toml`, y mencionar `epw_trend_analyzer.py`, `epw_comparator.py`, `epw_utils.py` en "Main components". | `AGENTS.md` |
| 0.2 | Eliminar la ruta absoluta hardcodeada (`sys.path.extend([...])`) y el bloque de código comentado muerto en `generating epws seville.py`. | `generating epws seville.py` |
| 0.3 | Añadir `pvlib`, `tabulate`, `besos`, `eppy`, `accim` como *extras* opcionales en `pyproject.toml` (p. ej. `climate`, `energyplus`) y proteger sus imports en `climate_processor.py`/`epw_comparator.py` con `try/except ImportError` (igual que ya se hace con `ladybug-core`). | `pyproject.toml`, `climate_processor.py`, `epw_comparator.py` |

### Fase 1 — Eliminar la duplicación crítica EPW/MET (esfuerzo: 2-4 días)

1. Crear un nuevo módulo interno, p. ej. `pyweatherfiles/_epw_shared.py` (o ampliar `epw_utils.py`), con:
   - `calculate_atmos_pressure(elevation_m)` (fórmula barométrica única).
   - `set_epw_values(epw_obj, field_name, new_vals)` / `get_epw_values(epw_obj, field_name)` (compensación de offset *point-in-time*).
   - `UNUSED_EPW_FIELDS: dict` (los 15 campos con sus valores "missing" oficiales) + una función `neutralize_unused_epw_fields(epw_obj, n_rows, preserve=None)`.
   - Opcionalmente, `reconstruct_dhi_from_ghi_dni(...)` / `reconstruct_dni_from_horizontal(...)` parametrizando el desfase horario (`+0.5`/`-0.5`) explícitamente en vez de hardcodearlo en cada sitio.
2. Refactorizar `hourly_epw_converter.py` y `met_epw_converter.py` para importar y usar estas funciones, eliminando las copias locales.
3. **Antes de fusionar**, capturar un *snapshot* de salida (un EPW generado con cada convertidor, sobre datos de prueba pequeños) para poder comparar byte a byte que el refactor no altera el resultado (ver Fase 2 para convertir esto en un test real).
4. Documentar explícitamente en el docstring compartido *por qué* difiere el punto de evaluación horaria entre ambos flujos de conversión (o unificarlo si la diferencia no está justificada).

*(Opcional, mismo esfuerzo/impacto medio):* extraer un módulo `_psychrometrics.py` con las variantes de Magnus usadas en `hourly_epw_converter.py`, `met_epw_converter.py` y `climate_processor.py`, decidiendo un único juego de constantes salvo que exista una razón documentada para mantener variantes.

### Fase 2 — Tests automatizados (esfuerzo: 1-2 semanas, la de mayor prioridad estructural)

1. Crear carpeta `tests/` + añadir `pytest` (y `pytest-cov`) como dependencia de desarrollo (`[project.optional-dependencies].dev` o `[dependency-groups]` en `pyproject.toml`).
2. **Nivel 1 — funciones físicas puras** (coste bajo, alto retorno): convertir los ejemplos `# doctest: +SKIP` ya existentes en los docstrings de `met_epw_converter.py`/`hourly_epw_converter.py`/`climate_processor.py` en tests reales de `pytest` (barométrica, Magnus, Stefan-Boltzmann, `_compute_cdf`, estadístico FS).
3. **Nivel 2 — regresión de los refactors de la Fase 1**: test que genera un EPW de muestra con `HourlyEPWConverter` y con `convert_met_to_epw`, y compara sus campos numéricos frente a un *snapshot* de referencia.
4. **Nivel 3 — smoke test end-to-end** de `TMYGenerator.generate_tmy()` sobre el dataset sintético reproducible que ya existe para el tutorial (`examples/tutorial_pyweatherfiles.ipynb`, según `TODO.md` tarea 3) — reutilizarlo en vez de generar uno nuevo.
5. Añadir `session_manager` a los tests (guardar/cargar sesión y verificar *round-trip*).
6. Configurar un umbral mínimo de cobertura razonable (no 100%, pero sí que cubra al menos los módulos de la Fase 1).

### Fase 3 — Integración continua (esfuerzo: 2-3 días, depende de la Fase 2)

1. Añadir `.github/workflows/ci.yml`: matriz mínima (una versión de Python compatible con `requires-python = ">=3.7"` o revisar si conviene subir el mínimo), instala el paquete con extras de test, corre `pytest`.
2. Job adicional (opcional) que ejecute `python -m build` (reutilizando `dist_build_package.bat` como referencia) para detectar roturas de empaquetado en cada PR, antes de que sea necesario descubrirlas manualmente al publicar en PyPI (tarea 2 de `TODO.md`).

### Fase 4 — Reducir el solapamiento `EpwTrendAnalyzer` / `EpwGroupTrendAnalyzer` (esfuerzo: 3-5 días, requiere acuerdo de diseño)

1. Hacer que `EpwTrendAnalyzer.discover_files()` reutilice `epw_utils.classify_epw_files()` en vez de reimplementar su propio `glob`+regex (reduce una duplicación conceptual concreta y de bajo riesgo).
2. Evaluar si `compute_trends()` de `EpwGroupTrendAnalyzer` debería poder invocar también un ajuste de efectos fijos global (`fit_global_models`) reutilizando la implementación ya existente en `epw_trend_analyzer.py`, en lugar de quedarse solo con regresiones independientes por grupo.
3. Si se confirma que ambas clases deben seguir siendo independientes por sus públicos distintos (temperatura pura vs. grados-hora), documentar explícitamente en el docstring de cada una un enlace cruzado ("ver también") y añadir una tabla comparativa al `README.md` (ya existe parcialmente en §6.6, pero podría explicitar mejor cuándo usar una u otra).

### Fase 5 — Modularización de archivos monolíticos (esfuerzo: 2-4 semanas, alto riesgo — **ejecutar solo después de la Fase 2**)

> Estos cambios solo deben abordarse una vez exista una red de tests de regresión (Fase 2), dado que son refactors de gran superficie sobre un paquete sin cobertura automática actualmente.

1. **`tmy.py` → paquete `pyweatherfiles/tmy/`**: dividir manteniendo `TMYGenerator` como fachada pública sin cambios de API:
   - `_fs_selection.py` (Step 2), `_proximity.py` (Step 3), `_persistence.py` (Steps 4-5), `_assembly_smoothing.py` (Steps 6-7), `_plotting.py` (los ~8 métodos `plot_*`), `_validation.py` (métodos `validate_*`/`analyze_selection`/`generate_full_summary`), `_compat.py` (aliases `step_*` deprecados y propiedades `validation_st*`).
2. **`degree_hours.py` → paquete `pyweatherfiles/degree_hours/`**: separar `calculator.py` (`DegreeHoursCalculator`), `batch_analyzer.py` (`EpwBatchAnalyzer`), `group_trend_analyzer.py` (`EpwGroupTrendAnalyzer`), con un `__init__.py` que re-exporte las 3 clases para no romper `from pyweatherfiles.degree_hours import X`.
3. **`epw_trend_analyzer.py`**: separar configuración (`_config.py`, dataclasses), métricas (`_metrics.py`), modelos estadísticos (`_models.py`), figuras (`_plotting.py`) e informes (`_report.py`), manteniendo `EpwTrendAnalyzer` como orquestador.

### Fase 6 — Limpieza continua de deuda técnica menor (sin plazo fijo)

- Decidir y documentar una convención de idioma para mensajes de consola (p. ej. "docstrings en inglés, mensajes de usuario en inglés salvo excepción justificada") y aplicarla progresivamente.
- Revisar en una futura versión mayor (`v1.0`) si los alias `step_1_load_and_prepare_data`…`step_4_create_and_smooth_tmy` y `'sawaqed'` pueden retirarse definitivamente, con nota en el *changelog*.
- Extraer el patrón repetido de exportación a Excel (`pd.ExcelWriter` + `to_excel` por hoja) a un pequeño helper común en `session_manager.py` o un nuevo `_export_utils.py`.

---

## 7. Resumen de priorización

| Prioridad | Fase | Motivo |
|---|---|---|
| 1 | Fase 0 | Coste mínimo, corrige riesgos inmediatos de documentación/paquetado antes de seguir tocando código. |
| 2 | Fase 2 (tests) | Sin red de pruebas, cualquier refactor posterior (incluida la Fase 1) es más arriesgado de lo necesario. Se recomienda adelantar al menos el "Nivel 1" de la Fase 2 antes o en paralelo con la Fase 1. |
| 3 | Fase 1 | Elimina la duplicación de mayor severidad detectada (lógica EPW/MET), con alcance acotado y claramente delimitado. |
| 4 | Fase 3 | Consolida el beneficio de la Fase 2 impidiendo regresiones futuras. |
| 5 | Fase 4 | Mejora de diseño de valor medio, no urgente. |
| 6 | Fase 5 | Mayor beneficio a largo plazo para mantenibilidad, pero mayor riesgo — condicionada a tener tests. |
| Continua | Fase 6 | Mejora incremental sin bloquear el resto del roadmap (`TODO.md` ya cubre documentación/PyPI). |

Este plan es complementario, no sustitutivo, del `TODO.md`/`TODO_ES.md` ya existente (centrado en documentación Sphinx y publicación en PyPI): se recomienda ejecutar como mínimo la **Fase 0** y el **Nivel 1 de la Fase 2** antes de completar la tarea 2 de `TODO.md` ("Publicar en PyPI"), para no publicar con dependencias mal declaradas ni con cero cobertura de tests.

---

## 8. Anexo — Referencias exactas de las duplicaciones (para uso directo por quien implemente la Fase 1)

```text
_calculate_atmos_pressure:
  hourly_epw_converter.py  L.371-386  (método de instancia, self.elev)
  met_epw_converter.py     L.208-233  (función libre, elevation_m)

_set_epw_values:
  hourly_epw_converter.py  L.388-411
  met_epw_converter.py     L.281-309

_get_epw_values (solo existe en un lado):
  met_epw_converter.py     L.312-333

unused_fields_mapping (15 campos EPW "missing"):
  hourly_epw_converter.py  L.575-591  (dentro de transform_to_epw)
  met_epw_converter.py     L.580-596  (dentro de convert_met_to_epw)

Reconstrucción solar vía Sunpath (DHI <-> GHI/DNI):
  hourly_epw_converter.py  L.531-552  (evalúa en hour + 0.5)
  met_epw_converter.py     L.517-560  (evalúa en hour - 0.5)

Familia Magnus (RH <-> T_rocío), variantes de constantes:
  hourly_epw_converter.py::_calculate_rh          L.345-369  (6.112 / 17.67 / 243.5)
  met_epw_converter.py::_calculate_dew_point       L.180-205  (17.62 / 243.12)
  met_epw_converter.py::_calculate_absolute_humidity  L.258-278  (610.78 / 7.5 / 237.3)
  climate_processor.py (relleno de huecos de RH)  (17.625 / 243.04)
```

---

*Documento generado como parte de una revisión técnica solicitada por el equipo del proyecto. No modifica ningún archivo de código; todas las acciones descritas en la §6 quedan pendientes de implementación.*

