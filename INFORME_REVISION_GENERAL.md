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

**Estado real tras esta pasada:** 37/37 tests en verde (`python -m pytest tests/`). Cobertura: módulo `epw_field_utils.py` (nuevo, Fase 1) y las funciones físicas puras de `met_epw_converter.py`/`hourly_epw_converter.py`. **Sin cubrir todavía:** `tmy.py` (el módulo más grande y crítico), `degree_hours.py`, `epw_trend_analyzer.py`, `climate_processor.py`, `epw_comparator.py`, `session_manager.py`.

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

| Prioridad | Fase | Estado | Motivo |
|---|---|---|---|
| 1 | Fase 0 | ✅ Completada (rama `chore/general-review-improvements`) | Coste mínimo, corrige riesgos inmediatos de documentación/paquetado antes de seguir tocando código. |
| 2 | Fase 2 (tests) | 🟡 En progreso (37 tests, Niveles 1-2 de 6 pasos) | Sin red de pruebas, cualquier refactor posterior (incluida la Fase 1) es más arriesgado de lo necesario. Se recomienda adelantar al menos el "Nivel 1" de la Fase 2 antes o en paralelo con la Fase 1. Nota: la Fase 1 ya se ejecutó igualmente, verificada solo con pruebas manuales de regresión (ver §6 Fase 1, punto 3) a falta de la suite automatizada. |
| 3 | Fase 1 | ✅ Completada (misma rama), verificación manual | Elimina la duplicación de mayor severidad detectada (lógica EPW/MET), con alcance acotado y claramente delimitado. |
| 4 | Fase 3 | ⬜ Pendiente | Consolida el beneficio de la Fase 2 impidiendo regresiones futuras. |
| 5 | Fase 4 | ⬜ Pendiente | Mejora de diseño de valor medio, no urgente. |
| 6 | Fase 5 | ⬜ Pendiente | Mayor beneficio a largo plazo para mantenibilidad, pero mayor riesgo — condicionada a tener tests. |
| Continua | Fase 6 | ⬜ Pendiente | Mejora incremental sin bloquear el resto del roadmap (`TODO.md` ya cubre documentación/PyPI). |

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

