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

> ✅ **Actualización (Fase 1 completada):** las 3 primeras duplicaciones de la tabla siguiente ya se han extraído a un módulo compartido, `pyweatherfiles/epw_field_utils.py` (`calculate_atmos_pressure`, `set_epw_values`/`get_epw_values`, `UNUSED_EPW_FIELDS`/`neutralize_unused_epw_fields`). Ambos convertidores lo usan ahora; se mantienen wrappers delgados de compatibilidad (`_calculate_atmos_pressure`, `_set_epw_values`, `_get_epw_values`) que delegan en él. Verificado con una prueba de regresión manual (generación real de un EPW desde `HourlyEPWConverter` y desde `convert_met_to_epw` sobre un `.met` sintético) — ver commit correspondiente en la rama `chore/general-review-improvements`. La 4ª fila (desfase `+0.5`/`-0.5`) se dejó documentada in-situ (no se unificó) porque, tras revisión, la diferencia es **correcta e intencional** (ver nota añadida en el código y en README §4.3/§5.2): responde a que los CSV/XLSX horarios indexan `hour` 0-23 como *inicio* del intervalo, mientras que `.met` indexa `Hour` 1-24 como *fin* del intervalo.

### 3.1 Duplicación literal de funciones físicas/EPW

| Función/bloque | Ubicación A | Ubicación B | Naturaleza |
|---|---|---|---|
| **Presión atmosférica barométrica** | `hourly_epw_converter.py::HourlyEPWConverter._calculate_atmos_pressure` (L.371-386, método de instancia, usa `self.elev`) | `met_epw_converter.py::_calculate_atmos_pressure` (L.208-233, función libre, parámetro `elevation_m`) | **Fórmula idéntica** (constantes `p0=101325, L=0.0065, T0=288.15, g=9.80665, M=0.0289644, R=8.31447` repetidas literalmente en ambos sitios). ✅ Resuelto: ambas delegan en `epw_field_utils.calculate_atmos_pressure`. |
| **Corrección de offset *point-in-time* de Ladybug** | `hourly_epw_converter.py::HourlyEPWConverter._set_epw_values` (L.388-411) | `met_epw_converter.py::_set_epw_values` (L.281-309) | **Lógica idéntica** (`shifted = [new_vals[-1]] + list(new_vals[:-1])`). Además, `met_epw_converter.py` tiene también `_get_epw_values` (L.312-333, la operación inversa) que no existe en `hourly_epw_converter.py`, pese a que sería igual de útil ahí. ✅ Resuelto: ambas delegan en `epw_field_utils.set_epw_values`/`get_epw_values`. |
| **Mapa de 15 campos EPW "no usados por EnergyPlus"** | `hourly_epw_converter.py::transform_to_epw` (`unused_fields_mapping`, L.575-591) | `met_epw_converter.py::convert_met_to_epw` (`unused_fields_mapping`, L.580-596) | **Diccionario y bucle de aplicación prácticamente idénticos** (mismos 15 campos, mismos valores "missing": `9999`, `999999`, `99`, `0.999`, etc.). ✅ Resuelto: ambas usan `epw_field_utils.UNUSED_EPW_FIELDS`/`neutralize_unused_epw_fields`. |
| **Reconstrucción de radiación difusa/directa vía posición solar exacta** | `hourly_epw_converter.py` (cálculo de DHI desde GHI/DNI, `Sunpath`, evaluado en `hour + 0.5`, L.531-552) | `met_epw_converter.py` (cálculo de GHI/DNI desde componentes horizontales, `Sunpath`, evaluado en `hour - 0.5`, L.517-560) | **Mismo patrón** (zenith vía `Sunpath.calculate_sun`, `cos_zenith`, protección `cos_zenith <= 0.01`), aplicado en direcciones inversas. ✅ Aclarado (no unificado): el desfase `+0.5`/`-0.5` es correcto para la convención horaria de cada formato de origen (ver comentarios añadidos en ambos módulos). |

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

### Fase 1 — Eliminar la duplicación crítica EPW/MET (esfuerzo: 2-4 días) — ✅ COMPLETADA

1. [x] Crear un nuevo módulo interno, `pyweatherfiles/epw_field_utils.py`, con:
   - [x] `calculate_atmos_pressure(elevation_m)` (fórmula barométrica única).
   - [x] `set_epw_values(epw_obj, field_name, new_vals)` / `get_epw_values(epw_obj, field_name)` (compensación de offset *point-in-time*).
   - [x] `UNUSED_EPW_FIELDS: dict` (los 15 campos con sus valores "missing" oficiales) + `neutralize_unused_epw_fields(epw_obj, num_rows, skip_fields=None)`.
   - [ ] No se extrajo un helper genérico de reconstrucción DHI/DNI vía `Sunpath`: tras revisar el desfase `+0.5`/`-0.5`, se concluyó que responde a una diferencia real de convención horaria entre formatos de origen (ver punto 4), por lo que se dejó la lógica en cada módulo con un comentario explicativo cruzado, en vez de forzar una abstracción común que ocultaría esa diferencia.
2. [x] Refactorizar `hourly_epw_converter.py` y `met_epw_converter.py` para usar `epw_field_utils`, manteniendo wrappers delgados de compatibilidad (`_calculate_atmos_pressure`, `_set_epw_values`, `_get_epw_values`) que delegan en el módulo compartido.
3. [x] Verificado mediante prueba de regresión manual (no automatizada — pendiente de la Fase 2): generación real de un EPW con `HourlyEPWConverter` sobre el dataset de Sevilla del repo, y de otro con `convert_met_to_epw` sobre un `.met` sintético de 8760 h; se confirmaron valores de temperatura/presión/DHI/GHI razonables y la correcta neutralización de los 15 campos no usados (p. ej. `global_horizontal_illuminance == 999999`).
4. [x] Documentado in-situ (comentarios en ambos módulos + README §4.3/§5.2) *por qué* difiere el punto de evaluación horaria: los CSV/XLSX horarios usan `hour` 0-23 como inicio de intervalo (`hour + 0.5`), mientras que `.met` usa `Hour` 1-24 como fin de intervalo (`Hour - 0.5`). No se unificó porque ambos son correctos para su convención respectiva.

*(Pendiente, no abordado en esta pasada — mismo esfuerzo/impacto medio):* extraer un módulo `_psychrometrics.py` con las variantes de Magnus usadas en `hourly_epw_converter.py`, `met_epw_converter.py` y `climate_processor.py` (§3.2), decidiendo un único juego de constantes salvo que exista una razón documentada para mantener variantes.

### Fase 2 — Tests automatizados (esfuerzo: 1-2 semanas, la de mayor prioridad estructural) — 🟡 EN PROGRESO

1. [x] Crear carpeta `tests/` + añadir `pytest`/`pytest-cov` como extra opcional `test` en `pyproject.toml` (`pip install -e ".[test]"`, configuración en `[tool.pytest.ini_options]`).
2. [x] **Nivel 1 — funciones físicas puras** (coste bajo, alto retorno): 35 tests en `tests/test_epw_field_utils.py`, `tests/test_met_epw_converter_physics.py`, `tests/test_hourly_epw_converter_physics.py` cubriendo `calculate_atmos_pressure`, `set_epw_values`/`get_epw_values`, `UNUSED_EPW_FIELDS`/`neutralize_unused_epw_fields`, `_calculate_dew_point`, `_calculate_sky_temperature`, `_calculate_absolute_humidity`, `_calculate_variable_pressure_from_met`, `_calculate_rh`. **Efecto secundario real:** el propio proceso de escribir estos tests detectó y corrigió un error tipográfico preexistente en el docstring de `_calculate_dew_point` (`13.86` documentado vs. `13.85` real). Pendiente: `climate_processor.py` (Magnus/clear-sky) y `_compute_cdf`/estadístico FS de `tmy.py` aún sin tests.
3. [x] **Nivel 2 — regresión de los refactors de la Fase 1**: `tests/test_regression_epw_pipeline.py` genera un EPW base 100% sintético en memoria (`ladybug.epw.EPW.from_missing_values()`, sin depender de archivos externos no versionados como los de `onedrive_backup/`) y ejecuta el pipeline completo de `HourlyEPWConverter.process()` y `convert_met_to_epw()` sobre datos horarios/`.met` sintéticos generados en el propio test, verificando rangos físicos plausibles y la correcta neutralización de campos EPW no usados. 2/2 tests en verde.
4. [ ] **Nivel 3 — smoke test end-to-end de `TMYGenerator.generate_tmy()`**: pendiente.
5. [ ] Tests de `session_manager` (round-trip guardar/cargar sesión): pendiente.
6. [ ] Umbral mínimo de cobertura configurado en CI: pendiente (bloqueado además por un problema de compatibilidad `pytest-cov`/`numpy` observado en Python 3.14 en este entorno — a revisar al configurar la Fase 3).
7. [x] **Cobertura de `epw_comparator.py` (0% → 82%)**: tras completar la Fase 5 y la Fase 6, se ejecutó `pytest --cov=pyweatherfiles --cov-report=term-missing` para identificar los huecos de cobertura más críticos restantes. `epw_comparator.py` destacaba con **0% de cobertura absoluta** (150 statements, ninguno cubierto) pese a ser uno de los módulos modificados en la Fase 6 (traducción de mensajes). Se añadió `tests/test_epw_comparator.py` (12 tests) cubriendo las 4 funciones públicas contra EPWs sintéticos deterministas (`ladybug.epw.EPW.from_missing_values()`), incluyendo el caso de archivo inexistente para cada una.
   - **Efecto secundario real — 3 bugs de producción preexistentes detectados y corregidos** (ninguno introducido por este proyecto; se manifiestan con la versión de `ladybug-core` actualmente instalada):
     1. `create_comparison_dataframe()`: su `get_header_name()` interno buscaba el nombre de cada variable en `header['name']`, pero la versión instalada de `ladybug-core` anida ese dato un nivel más adentro, en `header['data_type']['name']`. Esto hacía que la función devolviera **siempre un DataFrame completamente vacío (0 filas, 0 columnas)**, sin ningún error visible — un fallo silencioso severo para una función cuyo propósito es precisamente producir esas columnas. Corregido probando primero `header['data_type']['name']` con *fallback* al comportamiento anterior.
     2. La misma función: una vez corregido (1), el índice de tiempo tampoco se construía (cae al *fallback* numérico con advertencia) porque la búsqueda de columnas `year`/`month`/`day`/`hour` era sensible a mayúsculas, mientras que los nombres reales son `Year`/`Month`/`Day`/`Hour`. Corregido con una búsqueda insensible a mayúsculas (mismo patrón ya usado para el resto de columnas de la función).
     3. La misma función: al corregir (2) y empezar a construirse un `DatetimeIndex` real, se expuso un tercer bug — las columnas de datos se asignaban con `df_final[col] = df_base[col_base]` (una `Series` con su propio `RangeIndex` original), lo que pandas alinea automáticamente contra el nuevo `DatetimeIndex` de `df_final`, produciendo **todo NaN**. Corregido asignando `.values` en vez de la `Series`, para una copia posicional sin alineación por índice.
     4. `compare_epw_files()`: `ladybug.epw.EPW()` es de carga perezosa (el constructor nunca falla; el error real solo aparece al acceder a un atributo como `.location`), por lo que el `try/except` alrededor de `EPW(path)` nunca capturaba nada con un archivo inexistente, y la construcción posterior de `header_data` (sin protección) propagaba la excepción sin control, rompiendo la función. Corregido forzando el acceso a `.location` dentro del mismo bloque `try` para adelantar la detección del error.
   - **Estado real tras esta pasada: 109/109 tests en verde** (97 previos + 12 de `epw_comparator`). Cobertura total del proyecto: 55% → 58%. `epw_comparator.py` pasa de 0% a 82%.
8. [x] **Cobertura de `degree_hours/_helpers.py` (35% → 100%) y `degree_hours/calculator.py` (24% → 59%)**: siguiente hueco de cobertura más severo tras el punto 7. Se añadieron dos archivos: `tests/test_degree_hours_helpers.py` (16 tests unitarios para las funciones puras `until_to_hour`, `build_24h_profile`, `idf_objects` y las constantes `EP_DAYTYPE_WEEKDAYS`/`WEEKDAILY_FIELD`, con *fakes* ligeros que imitan un objeto `besos.Building`/eppy `IDF` sin necesitar las dependencias reales) y `tests/test_degree_hours_calculator_idf.py` (13 tests) que reutiliza como *fixture* el IDF real ya versionado en la raíz del repo (`SF_Detached_D_min_South.idf`, citado por `AGENTS.md` como script de referencia) en vez de construir uno sintético desde cero, ya que ya contiene exactamente los objetos EnergyPlus más complejos de parsear: `SCHEDULE:COMPACT` con rangos de fecha anidados, `ZoneControl:Thermostat` + `ThermostatSetpoint:DualSetpoint`, y `ZoneHVAC:IdealLoadsAirSystem` con disponibilidad estacional. Cubre `extract_setpoints_from_idf()` (valores exactos de consigna conocidos del IDF — 17/20 °C calefacción, 27/25 °C refrigeración —, disponibilidad variable a lo largo del año, incluyendo un test que confirma que los grados-hora son **exactamente cero** en los meses sin disponibilidad pese a una temperatura muy extrema, y el caso de zona inexistente), y los 3 tipos de configuración por diccionario de `_setpoints_from_dict()` que no tenían ningún test previo (`'daily'`, `'weekly'`, `'hourly_weekly'`; solo `'constant'` estaba cubierto en `test_degree_hours_package.py`). Ambos archivos usan `pytest.importorskip("besos")`/`("eppy")` para saltarse automáticamente si esas dependencias opcionales no están instaladas.
   - **Estado real tras esta pasada: 138/138 tests en verde** (109 previos + 29 nuevos). Cobertura total del proyecto: 58% → 63%. `degree_hours/_helpers.py` pasa de 35% a 100%; `degree_hours/calculator.py` pasa de 24% a 59% (el ~40% restante es mayoritariamente el método `plot()` de matplotlib, líneas 1136-1276, de menor prioridad que la lógica de cálculo).
9. [x] **Cobertura de `session_manager.py` (50% → 89%)**: módulo transversal reutilizado por `tmy`, `degree_hours`, `hourly_epw_converter`, `met_epw_converter` y `epw_comparator`, siguiente hueco relevante tras el punto 8. `tests/test_session_manager.py` (44 tests) cubre exhaustivamente todas las funciones internas y públicas: `_sanitize` (slugs de nombre de archivo), `_make_hash` (determinismo, independencia del orden de claves), `generate_session_filename`, `_infer_output_dir`, `_to_json_safe` (todos los tipos manejados: primitivos, escalares numpy, `DataFrame`/`Series`/`ndarray` resumidos, dict/list anidados, truncamiento de listas largas, `datetime`/`date`, *fallback* a `str()`), `_object_to_json_dict` (solo atributos públicos, atributo que lanza excepción al leerse), `_pickle_obj` (objeto picklable normal vs. *fallback* a estado parcial con un atributo no picklable) y el *round-trip* completo de `save_object_session`/`save_function_session`/`load_session` (incluyendo inferencia de directorio, creación de directorio si no existe, y `FileNotFoundError` al cargar una ruta inexistente).
   - **Nota metodológica real:** los dos primeros intentos de test de *round-trip* de pickle fallaron porque las clases de prueba se definieron **dentro** del método de test (clases anidadas en una función); Python nunca puede *picklear* una clase local de ese tipo (`Can't pickle local object`), lo que activaba siempre el *fallback* de estado parcial de `_pickle_obj` en vez de probar también el camino directo. Corregido definiendo las clases de ayuda (`_PicklableDummy`, `_NonPicklableDummy`) a nivel de módulo del propio archivo de test.
   - **Estado real tras esta pasada: 182/182 tests en verde** (138 previos + 44 nuevos). Cobertura total del proyecto: 63% → 64%. `session_manager.py` pasa de 50% a 89% (el resto son ramas de manejo de errores de I/O de disco poco realistas de simular en un test, p. ej. fallo de escritura tras haber comprobado que el directorio existe).
10. [x] **Cobertura de `tmy/_data_loading.py` (40% → 98%)**: Step 1 del flujo Sandia — el smoke test de `tests/test_tmy_package.py` solo ejercitaba el camino más simple (CSV horario con GHI presente); quedaban sin cubrir la carga desde Excel, la validación de `years_to_include`, los *placeholders* de GHI/DNI faltante, el recorte de valores negativos, **toda** la rama `data_frequency='daily'` y **toda** la rama de archivo horario separado (`hourly_file_path`). `tests/test_tmy_data_loading.py` (18 tests) instancia `TMYGenerator` real con datasets CSV/XLSX sintéticos generados en el propio test y llama a `sandia_step_1_load_and_prepare()` directamente (sin ejecutar el resto del pipeline), cubriendo cada una de esas ramas, incluyendo un caso que confirma que el archivo horario separado se recorta correctamente a los meses/años presentes en el archivo diario (con seguimiento en `excluded_months_initial`).
    - **Nota menor (no corregida, solo documentada):** al ejercitar por primera vez la rama de archivo horario separado aparece un `UserWarning` de pandas preexistente ("Converting to PeriodArray/Index representation will drop timezone information") en las 3 llamadas a `.to_period('M')` de `_data_loading.py` sobre un índice con timezone. No es un error funcional (el resultado es correcto), solo un aviso cosmético; se deja anotado como posible micro-mejora futura (`tz_localize(None)` antes de `.to_period()`), sin prioridad.
    - **Estado real tras esta pasada: 200/200 tests en verde** (182 previos + 18 nuevos). Cobertura total del proyecto: 64% → 65%. `tmy/_data_loading.py` pasa de 40% a 98%.
11. [x] **Cobertura de `hourly_epw_converter.py` (55% → 91%)**: siguiente hueco relevante tras el punto 10, y el más bajo de los dos conversores EPW/MET (el otro, `met_epw_converter.py`, seguía en 64%). `tests/test_hourly_epw_converter_extra.py` (23 tests) complementa el único test de regresión existente (`tests/test_regression_epw_pipeline.py`, que solo ejercita el camino más simple: un año no bisiesto, con RH/presión/DHI reconstruidos, sin archivo horario separado y sin `BatchHourlyEPWConverter`). Cubre el manejo de errores de `__init__` (parámetros geográficos no determinables ni explícita ni desde la plantilla EPW, y el caso en que se dan explícitamente saltándose la extracción), lectura desde `.xlsx`, conversión de unidades de viento (km/h → m/s), año no disponible en `get_year_data()`, las columnas EPW opcionales de `transform_to_epw()` (dirección de viento presente/ausente, cobertura de nubes + IRH con `preserve_extra=True`, humedad relativa cuando la columna existe en la fuente), año bisiesto (`remove_leap_day=True/False`), `process()` multi-año (años no disponibles omitidos, patrón de nombre de archivo con clave desconocida cayendo al nombre por defecto, persistencia de sesión), y la clase completa `BatchHourlyEPWConverter` (claves obligatorias, configuración vía `DataFrame`, `suggest_config()` con y sin coincidencia, `process_all()` con varias ciudades, entrada sin clave obligatoria, persistencia de sesión de lote).
    - **Efecto secundario real — 1 bug de producción corregido:** `transform_to_epw()` cargaba la plantilla con `EPW(base_epw_path)` dentro de un `try/except`, pero `ladybug.epw.EPW()` es de carga perezosa (el constructor nunca falla; el error real por archivo inexistente/corrupto solo aparece al acceder después a un atributo como `.location`), por lo que una plantilla inválida pasada específicamente a esta llamada (parámetro `base_epw_path` de `transform_to_epw()`, distinto del usado en `__init__`) no se detectaba aquí sino más abajo, sin protección — el mismo patrón de bug ya identificado y corregido en `epw_comparator.py` (punto 7). Corregido forzando `_ = epw_data.location` dentro del mismo bloque `try`.
    - **Nota metodológica:** `ladybug.sunpath.Sunpath.calculate_sun()` no admite años bisiestos (usa internamente un año de calendario fijo no bisiesto), por lo que el test de `remove_leap_day=False` provee explícitamente una columna de radiación difusa horizontal para que el 29 de febrero no dispare la reconstrucción vía posición solar exacta; documentado en el propio test como limitación de la librería externa, no un bug de este proyecto.
    - **Estado real tras esta pasada: 223/223 tests en verde** (200 previos + 23 nuevos). Cobertura total del proyecto: 65% → 68%. `hourly_epw_converter.py` pasa de 55% a 91% (el resto son ramas de manejo de errores de E/S en disco y algunos `except Exception` genéricos, poco realistas de forzar en un test).

**Estado real tras esta pasada:** 37/37 tests en verde (`python -m pytest tests/`). Cobertura: módulo `epw_field_utils.py` (nuevo, Fase 1) y las funciones físicas puras de `met_epw_converter.py`/`hourly_epw_converter.py`. **Sin cubrir todavía:** `tmy.py` (el módulo más grande y crítico), `degree_hours.py`, `epw_trend_analyzer.py`, `climate_processor.py`, `epw_comparator.py`, `session_manager.py`.

> Nota (tras Fase 5/6): la lista de "sin cubrir todavía" de arriba quedó muy desactualizada — ver los puntos 7-10 justo arriba para el estado real y más reciente. Cobertura por módulo restante con mayor hueco tras esta pasada (de mayor a menor): `tmy/_plotting.py` 23%, `degree_hours/group_trend_analyzer.py` 46%, `tmy/_validation.py` 49%, `hourly_epw_converter.py` 55%, `degree_hours/batch_analyzer.py` 59%, `degree_hours/calculator.py` 59%, `met_epw_converter.py` 64% — candidatos naturales para continuar esta fase en el futuro, sin urgencia (todos tienen ya al menos cobertura indirecta vía los smoke tests end-to-end de sus respectivos paquetes).

### Fase 3 — Integración continua (esfuerzo: 2-3 días, depende de la Fase 2) — ✅ COMPLETADA

1. [x] Añadido `.github/workflows/ci.yml`: matriz de `pytest` en Ubuntu (Python 3.10, 3.11, 3.12, 3.13, `fail-fast: false`) más un job en Windows (3.12, dado que el desarrollo real ocurre en Windows y ya hubo al menos un bug específico de esa plataforma — ver `TODO.md`, `UnicodeEncodeError` con `cp1252`). Se ejecuta en cada push a `main` y en cada *pull request*. Instala el paquete con el extra `test` (`pip install -e ".[test]"`) y corre `pytest tests/ --cov=pyweatherfiles`. Se sube el reporte de cobertura (`coverage.xml`) como artefacto en el job de Ubuntu 3.12.
2. [x] Job adicional `build`: ejecuta `python -m build` (sdist + wheel), replicando `dist_build_package.bat`, y sube los artefactos generados — validado también localmente antes del commit (build exitoso).
3. [x] **Efecto secundario real:** al preparar la matriz de CI se detectó que `requires-python = ">=3.7"` estaba obsoleto (Python 3.7 EOL desde 2023-06, incompatible con las versiones actuales de `pandas`/`numpy` ya fijadas como dependencias). Se subió a `>=3.10` y se añadieron los `classifiers` de versión de Python correspondientes en `pyproject.toml`.
4. [ ] No resuelto (anotado, no bloqueante): el problema de compatibilidad `pytest-cov`/`numpy` observado localmente en Windows + Python 3.14 (ver Fase 2 punto 6) no se ha podido reproducir/diagnosticar en un entorno de CI real todavía, porque la matriz de CI no incluye Python 3.14 (deliberadamente, por ser una versión demasiado reciente para tener *wheels* binarias garantizadas de todas las dependencias en el momento de escribir esto). Revisar si el problema persiste cuando 3.14 esté más consolidada.

### Fase 4 — Reducir el solapamiento `EpwTrendAnalyzer` / `EpwGroupTrendAnalyzer` (esfuerzo: 3-5 días, requiere acuerdo de diseño) — ✅ COMPLETADA

1. [x] `EpwTrendAnalyzer.discover_files()` refactorizado para reutilizar `epw_utils.classify_epw_files()` en vez de reimplementar su propio `glob`+regex. Se extendió `classify_epw_files()` para aceptar también un grupo de regex nombrado `city` (además del `group` original de `EpwGroupTrendAnalyzer`), con orden de resolución `group` → `city` → nombre de fichero sin extensión. Comportamiento preservado al 100% (minúsculas, orden, mensaje de `FileNotFoundError`), validado con tests de integración usando EPWs sintéticos (`ladybug.epw.EPW.from_missing_values()`).
2. [x] Extraído un nuevo módulo `pyweatherfiles/trend_stats.py` con el estimador de efectos fijos globales (`FixedEffectResult`, `build_fixed_effects_design`, `fit_fixed_effects_model`), parametrizando el nombre de la columna de agrupación (`group_col`, antes hardcodeada a `"city"`). `EpwTrendAnalyzer._build_fe_design`/`_fit_global_fixed_effect` ahora son *wrappers* delgados sobre él (cero cambio de comportamiento, mismos nombres de campo `slope_c_per_year`/`n_cities` para no romper los ~9 usos existentes en `epw_trend_analyzer.py`). Añadido el nuevo método `EpwGroupTrendAnalyzer.fit_global_trend(value_col)` en `degree_hours.py`, que reutiliza exactamente el mismo estimador con `group_col='group'` — cierra la brecha detectada (antes `EpwGroupTrendAnalyzer` solo podía ajustar regresiones independientes por grupo vía `compute_trends()`, sin equivalente al modelo de efectos fijos global).
3. [x] Añadida una tabla comparativa explícita "`EpwTrendAnalyzer` vs. `EpwGroupTrendAnalyzer` — cuál usar" en `README.md`/`README_ES.md` §7.4, más enlaces cruzados ("ver también") en los docstrings de ambas clases y en los nuevos módulos compartidos (`epw_utils.py`, `trend_stats.py`).

**Verificación:** 21 tests nuevos (`tests/test_trend_stats.py`, `tests/test_epw_utils.py`, `tests/test_fase4_trend_overlap_reduction.py`), incluyendo un caso que recupera exactamente la pendiente común conocida de un dataset sintético de 2 grupos, y un caso que confirma que `EpwGroupTrendAnalyzer.fit_global_trend()` coincide bit a bit con llamar a `fit_fixed_effects_model()` directamente. Suite completa: 58/58 tests en verde.

### Fase 5 — Modularización de archivos monolíticos (esfuerzo: 2-4 semanas, alto riesgo — **ejecutar solo después de la Fase 2**) — ✅ COMPLETADA

> Estos cambios solo deben abordarse una vez exista una red de tests de regresión (Fase 2), dado que son refactors de gran superficie sobre un paquete sin cobertura automática actualmente. Orden elegido: se empezó por el módulo de **menor riesgo** (`degree_hours.py`, 3 clases ya independientes), luego `epw_trend_analyzer.py`, y se dejó para el final `tmy.py` (una única clase monolítica de 4.100 líneas, sin ningún test previo) — abordado con más cautela, añadiendo primero un smoke test end-to-end antes de mover una sola línea, tal como recomendaba la pasada anterior de este informe.

1. [x] **`tmy.py` → paquete `pyweatherfiles/tmy/`**: completado. Mismo patrón de *mixins* usado en las dos migraciones anteriores, un módulo por paso Sandia más los transversales: `_data_loading.py` (`_DataLoadingMixin`, Step 1: `sandia_step_1_load_and_prepare` + `_load_and_prepare_real_data`), `_fs_selection.py` (`_FsSelectionMixin`, Step 2: `sandia_step_2_select_candidates_fs`, `_calculate_fs_statistic`, `_compute_cdf`/`_compute_interpolated_cdf`), `_proximity.py` (`_ProximityMixin`, Step 3: `sandia_step_3_proximity_ranking` y la validación/resolución de `normalization_method`/`normalization_weights`), `_persistence.py` (`_PersistenceMixin`, Steps 4-5: `sandia_step_4_and_5_apply_persistence`, exclusión secuencial de 3 pasadas y método por *score*), `_assembly_smoothing.py` (`_AssemblySmoothingMixin`, Steps 6-7: `sandia_step_6_assemble_tmy`, `sandia_step_7_smooth_junctions`, incluida la persistencia de sesión vía `session_manager`), `_validation.py` (`_ValidationMixin`: los `validate_*`, `summarize_fs_results`, `check_input_expectations` y los métodos de análisis/corrección v4.09 — `get_candidate_stats`, `generate_full_summary`, `analyze_selection`, `correct_selection_by_temperature`), `_plotting.py` (`_PlottingMixin`: los 12 métodos `plot_*`/`compare_tmy_versions`), `_compat.py` (`_CompatMixin`: alias `step_1_*`...`step_4_*` deprecados y las 6 propiedades `validation_st2_*`/`validation_st3_*`/`validation_st4_*`), `_core.py` (`class TMYGenerator(_DataLoadingMixin, _FsSelectionMixin, _ProximityMixin, _PersistenceMixin, _AssemblySmoothingMixin, _ValidationMixin, _PlottingMixin, _CompatMixin)` con `__init__`/`generate_tmy`/`export_tmy`). `__init__.py` re-exporta `TMYGenerator`; `from pyweatherfiles import TMYGenerator` y `from pyweatherfiles import tmy` (-> `tmy.TMYGenerator`) siguen funcionando sin cambios para quien los use. El archivo original `tmy.py` (4.102 líneas) fue eliminado tras verificar la migración línea a línea de los ~70 métodos/propiedades.
   - **Red de seguridad añadida primero, tal como se recomendaba:** `tests/test_tmy_package.py` (13 tests), con un generador de datos horarios 100% sintéticos y determinista (6 años, ciclo estacional de temperatura/GHI + ruido con semilla fija, sin dependencia de archivos externos no versionados) que ejercita el pipeline **completo** `generate_tmy()` de extremo a extremo con ambos métodos de persistencia (`'sequential'` y `'score'`), sin persistencia, exportación (`export_tmy` + relectura), los métodos de análisis v4.09 (`get_candidate_stats`, `generate_full_summary`, `analyze_selection`), dos métodos de `plot_*` (con `matplotlib.use("Agg")` vía `conftest.py`), y los 4 alias deprecados `step_1_*`...`step_4_*` (confirmando que emiten `DeprecationWarning` y delegan correctamente) más las propiedades `validation_st2_*`/`validation_st4_*` de compatibilidad.
   - **Verificación:** 83/83 tests en verde (70 previos + 13 nuevos de `tmy`), sin ninguna regresión. Se confirmó también que `TMYGenerator.__module__ == "pyweatherfiles.tmy._core"` y que `pyweatherfiles.tmy.TMYGenerator is TMYGenerator` (mismas comprobaciones de ruta de import ya usadas para `degree_hours`/`epw_trend_analyzer`).
2. [x] **`degree_hours.py` → paquete `pyweatherfiles/degree_hours/`**: completado. `calculator.py` (`DegreeHoursCalculator`), `batch_analyzer.py` (`EpwBatchAnalyzer`), `group_trend_analyzer.py` (`EpwGroupTrendAnalyzer`), `_helpers.py` (parseo de *schedules* IDF, antes funciones sueltas a nivel de módulo). `__init__.py` re-exporta las 3 clases; `from pyweatherfiles.degree_hours import X` y `from pyweatherfiles import degree_hours` siguen funcionando sin cambios para quien los use. El archivo original `degree_hours.py` fue eliminado tras verificar la migración. `glob`/`re` (código muerto detectado por el linter, ya sin uso desde la Fase 4) se omitieron al copiar. Verificado con 6 tests nuevos de humo end-to-end (`tests/test_degree_hours_package.py`, incluyendo un `EpwGroupTrendAnalyzer.run()`/`EpwBatchAnalyzer.run()` completos sobre EPWs sintéticos) + los 58 tests previos, todos en verde.
3. [x] **`epw_trend_analyzer.py` → paquete `pyweatherfiles/epw_trend_analyzer/`**: completado, mismo patrón de *mixins* usado para preservar la API pública sin cambios: `_config.py` (`TrendConfig`/`OutputConfig`), `_metrics.py` (`_MetricsMixin`: descubrimiento + métricas anuales/olas de calor), `_models.py` (`_ModelsMixin`: regresión OLS por ciudad + modelo de efectos fijos global), `_plotting.py` (`_PlottingMixin`: las 3 figuras + boxplots), `_report.py` (`_ReportMixin`: informe de texto/Markdown), `_core.py` (`class EpwTrendAnalyzer(_MetricsMixin, _ModelsMixin, _PlottingMixin, _ReportMixin)` con `__init__`/`from_dict`/`from_json`/`from_yaml`/`export_outputs`/`run`/`get_results`/`to_json` + `run_analysis`). `__init__.py` re-exporta `EpwTrendAnalyzer`/`TrendConfig`/`OutputConfig`/`FixedEffectResult`/`run_analysis`; `from pyweatherfiles import EpwTrendAnalyzer, TrendConfig, OutputConfig` y `from pyweatherfiles.epw_trend_analyzer import ...` siguen funcionando sin cambios. El archivo original se eliminó tras confirmar la migración.
   - **Verificación:** 6 tests nuevos de humo end-to-end (`tests/test_epw_trend_analyzer_package.py`), incluyendo un `EpwTrendAnalyzer.run()` completo (`discover_files` → `compute_metrics` → `fit_city_trends` → `fit_global_models` → `export_outputs`, con figuras/informes) sobre un dataset sintético con una **tendencia de calentamiento conocida y determinista** (+0.5 °C/año); el modelo de efectos fijos global recupera exactamente esa pendiente (`slope_c_per_year == 0.5`, verificado con `pytest.approx`), confirmando que el refactor no altera el resultado estadístico. Se generaron correctamente las 13 salidas configuradas (CSVs, XLSX, 5 PNG, 2 informes, snapshot JSON).
   - **Efecto secundario real:** al ejecutar este test se detectó que `matplotlib` podía seleccionar un backend interactivo (`TkAgg`) roto en este entorno (instalación de Tcl/Tk incompleta en Python 3.14), haciendo fallar intermitentemente los tests de figuras según el orden de ejecución. Corregido de forma permanente forzando `matplotlib.use("Agg")` en `tests/conftest.py` (mismo backend ya forzado en CI vía `MPLBACKEND=Agg`, Fase 3) — un problema de infraestructura de tests, no del código modularizado.

**Estado de la Fase 5 tras esta pasada: COMPLETADA.** Los 3 archivos monolíticos identificados en la revisión original (`degree_hours.py`, `epw_trend_analyzer.py`, `tmy.py`) están ahora modularizados en paquetes con el mismo patrón de *mixins*, preservando al 100% la API pública y sin ninguna regresión detectada. Suite completa: **83/83 tests en verde**. No queda ningún archivo monolítico pendiente de esta lista; el siguiente trabajo natural (no bloqueante) sería ampliar la cobertura de tests de `tmy/` más allá del smoke test (p. ej. tests unitarios de `_calculate_fs_statistic`/`_apply_persistence_sequential_exclusion` con casos borde específicos) y abordar la Fase 6.

### Fase 6 — Limpieza continua de deuda técnica menor (sin plazo fijo) — 🟡 EN PROGRESO

1. [x] **Decidir y documentar una convención de idioma para mensajes de consola** y aplicarla. Convención documentada en `AGENTS.md` ("Language convention (Fase 6)"): docstrings en inglés (ya consistente en todo el código), y mensajes de consola (`print(...)`), mensajes de excepción, comentarios de código y cualquier texto generado por el software visible para el usuario (p. ej. etiquetas de leyenda de matplotlib, metadatos `comments_1`/`comments_2` escritos en los EPW resultantes) también en inglés, salvo excepción documentada y deliberada. **Aplicada de forma completa** (no solo documentada) a los 8 módulos identificados con mensajes en español: `epw_comparator.py`, `hourly_epw_converter.py`, `met_epw_converter.py`, `degree_hours/calculator.py`, `degree_hours/batch_analyzer.py`, `degree_hours/group_trend_analyzer.py`, `session_manager.py` y partes de `tmy/` (`_assembly_smoothing.py`, `_plotting.py`) — confirmado con una búsqueda exhaustiva de caracteres acentuados en todo `pyweatherfiles/`, que tras la pasada solo deja las 2 menciones legítimas de `Author: Daniel Sánchez-García` (nombre propio real, no traducible). Excepciones documentadas y preservadas deliberadamente: los nombres de columna en español que forman parte del contrato público documentado de `epw_comparator.create_comparison_dataframe` (sufijos `_Base`/`_Generado`, `column_map` con nombres cortos como `TempBulboSeco`) — renombrarlos rompería la API para quien ya dependa de esos nombres de columna.
   - **Verificación:** suite completa (83 tests previos a esta fase) sin regresiones tras cada módulo traducido; se confirmó explícitamente que ningún test hace *pattern-matching* sobre el texto literal en español de ningún mensaje (solo `test_epw_utils.py` verifica la subcadena genérica `"WARNING"`, no afectada).
   - **Efecto secundario real:** al hacer esta pasada se detectaron y corrigieron **dos bugs preexistentes no relacionados con el idioma**: (a) un `except Exception as e:` con el cuerpo vacío en `hourly_epw_converter.py` (`HourlyEPWConverter.__init__`) causado por una edición previa de esta misma sesión que se perdió parcialmente por una limitación de la herramienta de edición al aplicar varias sustituciones en paralelo sobre el mismo archivo — detectado por `IndentationError` al recolectar los tests, corregido de inmediato; (b) el propio `AGENTS.md` tenía 3 de 4 actualizaciones de la Fase 5 sin aplicar por el mismo motivo (seguía describiendo `tmy.py` como monolítico y "70 tests" pese a que la Fase 5 ya estaba completa) — corregido en esta pasada. **Lección operativa:** no aplicar más de una sustitución de texto en paralelo sobre el mismo archivo; hacerlo secuencialmente y verificar con una búsqueda posterior.
2. [ ] Revisar en una futura versión mayor (`v1.0`) si los alias `step_1_load_and_prepare_data`…`step_4_create_and_smooth_tmy` y `'sawaqed'` pueden retirarse definitivamente, con nota en el *changelog*. Sin cambios — deliberadamente pospuesto (no es una acción de esta fase, sino una decisión a tomar en una futura versión mayor).
3. [x] **Extraer el patrón repetido de exportación a Excel** a un helper común. Creado `pyweatherfiles/_export_utils.py` con `export_frames_to_excel(sheets, path, index=True, skip_empty=True, engine="openpyxl")`: recorre un `dict[str, DataFrame]`, omite automáticamente entradas `None` o vacías (configurable), trunca nombres de hoja al límite de 31 caracteres de Excel, y admite `index` como booleano global o como `dict` granular por hoja (necesario porque los 6 puntos de uso originales mezclaban `index=True`/`index=False` según la hoja). Refactorizados los 6 puntos de uso identificados: `climate_processor.py` (`export_annual_statistics`, `export_complete_report`), `degree_hours/calculator.py` (`export_results`, que además tenía un mensaje de error en español corregido de paso: `"No hay resultados para exportar..."` → `"No results to export..."`), `degree_hours/batch_analyzer.py` (`export`, el caso más dinámico — hojas generadas programáticamente por frecuencia/EPW, adaptado construyendo el `dict` de hojas antes de llamar al helper), `degree_hours/group_trend_analyzer.py` (`export_results`) y `epw_trend_analyzer/_core.py` (`export_outputs`).
   - **Verificación:** 9 tests nuevos en `tests/test_export_utils.py` (una hoja por DataFrame, `index` global/por-hoja, entradas `None`/vacías omitidas, `skip_empty=False`, truncado de nombre de hoja, valor de retorno). Además, tests de regresión reales para **todos** los métodos `export_*` refactorizados que no tenían cobertura previa: `tests/test_climate_processor.py` (2 tests, requiere el extra opcional `pvlib` — se salta automáticamente con `pytest.importorskip` si no está instalado; instalado y verificado en verde en esta pasada) y 3 tests nuevos añadidos a `tests/test_degree_hours_package.py` (`DegreeHoursCalculator.export_results`, `EpwBatchAnalyzer.export`, `EpwGroupTrendAnalyzer.export_results`). Solo `epw_trend_analyzer._core.export_outputs` ya tenía cobertura indirecta previa (vía el smoke test de `EpwTrendAnalyzer.run()`).
   - **Estado real tras esta pasada: 97/97 tests en verde** (83 previos + 9 de `_export_utils` + 2 de `climate_processor` + 3 de `degree_hours` export). Build del paquete (`python -m build`) verificado con el nuevo módulo incluido correctamente en el wheel.

**Estado de la Fase 6 tras esta pasada:** puntos 1 y 3 completados (con verificación real, no solo documentación); punto 2 deliberadamente pospuesto a una futura versión mayor, tal como especifica su propio enunciado. Como esta fase es explícitamente "de limpieza continua, sin plazo fijo", queda abierta para futuras mejoras incrementales menores (p. ej. ampliar la cobertura de tests de `tmy/` más allá del smoke test, ver nota de cierre de la Fase 5).

---

## 7. Resumen de priorización

| Prioridad | Fase | Estado | Motivo |
|---|---|---|---|
| 1 | Fase 0 | ✅ Completada (rama `chore/general-review-improvements`) | Coste mínimo, corrige riesgos inmediatos de documentación/paquetado antes de seguir tocando código. |
| 2 | Fase 2 (tests) | 🟡 En progreso (70 tests, crecidos orgánicamente en cada fase posterior) | Sin red de pruebas, cualquier refactor posterior (incluida la Fase 1) es más arriesgado de lo necesario. Se recomienda adelantar al menos el "Nivel 1" de la Fase 2 antes o en paralelo con la Fase 1. Nota: la Fase 1 ya se ejecutó igualmente, verificada solo con pruebas manuales de regresión (ver §6 Fase 1, punto 3) a falta de la suite automatizada en ese momento. |
| 3 | Fase 1 | ✅ Completada (misma rama), verificación manual + tests posteriores | Elimina la duplicación de mayor severidad detectada (lógica EPW/MET), con alcance acotado y claramente delimitado. |
| 4 | Fase 3 | ✅ Completada (`.github/workflows/ci.yml`) | Consolida el beneficio de la Fase 2 impidiendo regresiones futuras. |
| 5 | Fase 4 | ✅ Completada (`trend_stats.py`, `classify_epw_files` extendido, `fit_global_trend`) | Mejora de diseño de valor medio, no urgente. |
| 6 | Fase 5 | ✅ Completada (`degree_hours/`, `epw_trend_analyzer/` y `tmy/` completados) | Mayor beneficio a largo plazo para mantenibilidad. Ejecutada con red de tests: smoke test de `TMYGenerator.generate_tmy()` añadido antes del refactor, 83/83 tests en verde. |
| Continua | Fase 6 | 🟡 En progreso (convención de idioma aplicada al 100%; helper de exportación a Excel completado; solo queda pospuesto deliberadamente el punto 2 a v1.0) | Mejora incremental sin bloquear el resto del roadmap (`TODO.md` ya cubre documentación/PyPI). 97/97 tests en verde. |

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

