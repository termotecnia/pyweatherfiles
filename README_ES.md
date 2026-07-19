# pyweatherfiles

[![Documentation Status](https://readthedocs.org/projects/pyweatherfiles/badge/?version=latest)](https://pyweatherfiles.readthedocs.io/en/latest/?badge=latest)

**`pyweatherfiles`** es un paquete de Python para la gestión integral de ficheros climáticos orientado a la simulación energética de edificios: generación de **Años Meteorológicos Típicos (TMY)**, conversión bidireccional entre formatos (EPW, `.met`, series horarias en CSV/Excel), cálculo de **grados-hora** de calefacción/refrigeración, **análisis de tendencias climáticas** multianuales, comparación de ficheros EPW y depuración/relleno de series horarias brutas.

Este documento describe **al máximo nivel de detalle técnico el paquete completo**: todos sus módulos, clases, funciones, parámetros y fórmulas — incluidos aquellos que **no** se usan en el script de referencia del artículo (`generating epws seville.py`).

> ℹ️ Si buscas el documento centrado **exclusivamente** en el flujo real del artículo (caso de estudio de Sevilla: `HourlyEPWConverter` + `convert_met_to_epw` + `TMYGenerator`), consulta [`ARTICLE_CONTEXT_SEVILLA.md`](ARTICLE_CONTEXT_SEVILLA.md).

> 🇬🇧 English version of this document: see [`README.md`](README.md).

> Autor del paquete: Daniel Sánchez-García (Universidad de Cádiz) — `daniel.sanchezgarcia@uca.es`

> 📘 **Documentación HTML completa** (alojada en Read the Docs — referencia de API autogenerada desde el código fuente, más esta misma guía, navegable y con buscador): **https://pyweatherfiles.readthedocs.io/**. Constrúyela localmente con `pip install -e ".[docs]"` y `dist_build_docs.bat` (ver `docs/source/installation.md`).
> 📓 **Tutorial práctico en notebook** (se ejecuta de principio a fin con datos ya incluidos en este repositorio, sin descargas externas; también se muestra renderizado directamente en la documentación online): [`examples/tutorial_pyweatherfiles.ipynb`](examples/tutorial_pyweatherfiles.ipynb).

---

## Tabla de contenidos

1. [Descripción general y arquitectura](#1-descripción-general-y-arquitectura)
2. [Instalación y dependencias](#2-instalación-y-dependencias)
3. [`tmy` — `TMYGenerator` (generación de TMY, metodología Sandia/TMY3)](#3-tmy--tmygenerator-generación-de-tmy-metodología-sandiatmy3)
4. [`hourly_epw_converter` — `HourlyEPWConverter` / `BatchHourlyEPWConverter`](#4-hourly_epw_converter--hourlyepwconverter--batchhourlyepwconverter)
5. [`met_epw_converter` — `convert_met_to_epw` / `convert_epw_to_met`](#5-met_epw_converter--convert_met_to_epw--convert_epw_to_met)
6. [`degree_hours` — `DegreeHoursCalculator` / `EpwBatchAnalyzer`](#6-degree_hours--degreehourscalculator--epwbatchanalyzer)
7. [`epw_trend_analyzer` — `EpwTrendAnalyzer`](#7-epw_trend_analyzer--epwtrendanalyzer)
8. [`epw_comparator` — comparación de ficheros EPW](#8-epw_comparator--comparación-de-ficheros-epw)
9. [`climate_processor` — `ClimateProcessor` (depuración/relleno de series horarias)](#9-climate_processor--climateprocessor-depuraciónrelleno-de-series-horarias)
10. [`session_manager` — persistencia de sesión (transversal)](#10-session_manager--persistencia-de-sesión-transversal)
11. [Dependencias completas por módulo](#11-dependencias-completas-por-módulo)
12. [Ejemplos rápidos por módulo](#12-ejemplos-rápidos-por-módulo)
13. [Notas de diseño y advertencias generales](#13-notas-de-diseño-y-advertencias-generales)
14. [Referencias bibliográficas](#14-referencias-bibliográficas)
15. [Licencia](#15-licencia)

---

## 1. Descripción general y arquitectura

### 1.1 ¿Qué resuelve cada módulo?

| Módulo (`pyweatherfiles.*`) | Clases / funciones principales | Propósito |
|---|---|---|
| `tmy` | `TMYGenerator` | Generación de un Año Meteorológico Típico (TMY) a partir de series históricas, método Sandia/TMY3 en 7 pasos |
| `hourly_epw_converter` | `HourlyEPWConverter`, `BatchHourlyEPWConverter` | Convierte series horarias (CSV/Excel) ya depuradas a ficheros `.epw`, uno por año o en lote multi-ciudad |
| `met_epw_converter` | `convert_met_to_epw`, `convert_epw_to_met` | Conversión bidireccional entre el formato `.met` (LIDER/CALENER-CTE) y `.epw` |
| `degree_hours` | `DegreeHoursCalculator`, `EpwBatchAnalyzer` | Grados-hora de calefacción/refrigeración desde EPW + consignas (IDF o dict), individual o comparativa multi-EPW |
| `epw_trend_analyzer` | `EpwTrendAnalyzer`, `TrendConfig`, `OutputConfig` | Tendencias climáticas multianuales (calentamiento, olas de calor) sobre colecciones de EPW anuales |
| `epw_comparator` | `explore_epw_structure`, `compare_epw_files`, `create_comparison_dataframe`, `create_comparison_hourly_dataframe` | Comparación estructural/estadística/horaria entre dos ficheros EPW |
| `climate_processor` | `ClimateProcessor` | Depuración, reindexado y relleno de huecos de series horarias brutas de estación (pre-procesado, aguas arriba de `tmy`/`hourly_epw_converter`) |
| `session_manager` | `save_object_session`, `save_function_session`, `load_session` | Persistencia reproducible (`.pkl` + `.json`) usada transversalmente por el resto de módulos |

### 1.2 API pública mínima (`pyweatherfiles/__init__.py`)

```python
from .tmy import TMYGenerator
from .degree_hours import DegreeHoursCalculator
from .epw_trend_analyzer import EpwTrendAnalyzer, TrendConfig, OutputConfig
```

El resto de clases/funciones (`hourly_epw_converter`, `met_epw_converter`, `epw_comparator`, `climate_processor`, `EpwBatchAnalyzer`, `session_manager`) se importan explícitamente desde su submódulo, p. ej. `from pyweatherfiles import hourly_epw_converter`.

### 1.3 Flujo de datos típico end-to-end

```
Estación / fuente de datos brutos (huecos, ruido)
        │
        ▼
 ClimateProcessor            (depuración, relleno de huecos, QA)  ── opcional, aguas arriba
        │
        ▼
 Serie horaria limpia (CSV/XLSX) ─────────────┬───────────────────────────────┐
        │                                     │                               │
        ▼                                     ▼                               ▼
 HourlyEPWConverter                     TMYGenerator                   ClimateProcessor.export_*
 (→ 1 EPW por año, "long-term")   (→ TMY: 1 año típico sintético)       (informes de calidad)
        │                                     │
        │                                     ▼
        │                            HourlyEPWConverter (TMY → EPW)
        │                                     │
        ▼                                     ▼
 EPWs anuales (city_year.epw)           EPW del TMY
        │                                     │
        ├─────────────┬───────────────────────┤
        ▼             ▼                       ▼
 EpwTrendAnalyzer  DegreeHoursCalculator   epw_comparator
 (tendencias        / EpwBatchAnalyzer      (comparación EPW vs EPW)
  multianuales)      (grados-hora)

 convert_met_to_epw / convert_epw_to_met: conversión independiente .met ↔ .epw
 (p. ej. ficheros de referencia normativa CTE/LIDER-CALENER)
```

---

## 2. Instalación y dependencias

```bash
pip install pyweatherfiles
```

Dependencias obligatorias (`pyproject.toml`): `pandas`, `numpy`, `scipy`, `matplotlib`, `seaborn`, `openpyxl`, `ladybug-core`, `pyyaml`.

Dependencias **opcionales**, requeridas solo por módulos concretos (ver [§11](#11-dependencias-completas-por-módulo) para el detalle exacto): `pvlib` (`climate_processor`), `tabulate` (`epw_comparator`), `besos` + `eppy` (`degree_hours`, extracción de consignas desde IDF), `accim` (`degree_hours`, opcional).

---

## 3. `tmy` — `TMYGenerator` (generación de TMY, metodología Sandia/TMY3)

Este es el **módulo central** del paquete: implementa el método **Sandia** de generación de TMY (Hall et al., 1978), con soporte adicional para el esquema de ponderación **TMY3** de NREL (Wilcox & Marion, 2008), estructurado en **7 pasos** (`sandia_step_1` … `sandia_step_7`) orquestados por `generate_tmy()`.

```python
from pyweatherfiles import tmy

gen = tmy.TMYGenerator(
    file_path='weather_data.csv',
    cdf_method='daily',
    data_frequency='hourly',
    weighting_method='sandia',
)
gen.generate_tmy(use_persistence=True)
gen.export_tmy('tmy_output.csv')
```

### 3.1 Constructor (`TMYGenerator.__init__`)

| Parámetro | Defecto | Descripción |
|---|---|---|
| `file_path` | — | CSV o Excel de entrada (obligatorio) |
| `cdf_method` | `'daily'` | `'daily'` (agregados, rápido) o `'hourly'` (resolución completa, costoso). No puede ser `'hourly'` si `data_frequency='daily'` |
| `years_to_include` | `None` | Subconjunto de años a usar; error si falta alguno solicitado |
| `weights` | `None` | Pesos personalizados por variable (sobrescribe la tabla por defecto de §3.2) |
| `column_mapping` | `None` | Dict adicional de mapeo de columnas (se combina con los `col_*`) |
| `data_frequency` | `'hourly'` | `'hourly'` o `'daily'` |
| `weighting_method` | `'sandia'` | `'sandia'` o `'tmy3'` |
| `save_validation_dfs` | `True` | Si `False`, omite la generación de las tablas `validation_step*` (más rápido, menos trazabilidad) |
| `hourly_file_path` | `None` | Fichero horario adicional para ensamblado/suavizado cuando `cdf_method='daily'` (puede ser el mismo fichero) |
| `missing_data_threshold` | `0.9` | Umbral de completitud de datos (Paso 2) |
| `plotting_position_method` | `'hazen'` | `'california'`, `'hazen'` o `'weibull'` |
| `datetime_col`, `col_temp`, `col_dew`, `col_wind`, `col_ghi`, `col_dni` | `'time'`, `'T_air'`, `'T_dew'`, `'Wind_speed'`, `'GHI'`, `'DNI'` | Nombres de columna de entrada a mapear |
| `save_session`, `session_dir` | `True`, `None` | Persistencia de sesión (ver [§10](#10-session_manager--persistencia-de-sesión-transversal)) |

### 3.2 Paso 1 — Carga y preparación (`sandia_step_1_load_and_prepare`)

- Aplica el mapeo de columnas (`column_mapping` derivado de los argumentos `col_*`).
- Convierte el índice a `datetime` (UTC), filtra por `years_to_include` si se especifica.
- Si `data_frequency='hourly'`: resamplea a frecuencia horaria (`resample('h').mean().interpolate('linear')`), recorta a 0 los valores negativos de `GHI`, `DNI` y `Wind_speed`, y crea una columna `GHI=0` con aviso si no existe.
- Calcula agregados diarios necesarios para `weighting_method` en `{'sandia','tmy3'}`: `T_air_mean/max/min`, `T_dew_mean/max/min`, `Wind_speed_mean/max`, `GHI_sum` (y `DNI_sum` solo para TMY3).
- Si se indicó `hourly_file_path`, se carga y procesa igual, y se **filtra a los meses presentes en el fichero diario**.
- Exige un mínimo de 5 años de datos.

**Tabla de pesos por defecto** (suman 1.0 en cada esquema):

| Variable | Sandia horario | TMY3 horario | Sandia diario | TMY3 diario |
|---|---|---|---|---|
| T_air (media) | 4/24 | 4/20 | 2/24 | 2/20 |
| T_air (máx.) | — | — | 1/24 | 1/20 |
| T_air (mín.) | — | — | 1/24 | 1/20 |
| T_dew (media) | 4/24 | 4/20 | 2/24 | 2/20 |
| T_dew (máx.) | — | — | 1/24 | 1/20 |
| T_dew (mín.) | — | — | 1/24 | 1/20 |
| Wind speed (media) | 4/24 | 2/20 | 2/24 | 1/20 |
| Wind speed (máx.) | — | — | 2/24 | 1/20 |
| GHI (suma) | 12/24 | 5/20 | 12/24 | 5/20 |
| DNI (suma) | — (excluida) | 5/20 | — (excluida) | 5/20 |

### 3.3 Paso 2 — Selección de candidatos por el estadístico Finkelstein-Schafer (`sandia_step_2_select_candidates_fs`)

Para cada mes calendario (1-12) y cada año disponible, se compara la **función de distribución acumulada (CDF) empírica** de ese mes/año candidato frente a la CDF de largo plazo (todos los años) del mismo mes calendario.

**Posiciones de graficado (plotting position) para la CDF empírica** (`plotting_position_method`, por defecto `'hazen'`):

```
hazen:      CDF(i) = (i − 0.5) / n
weibull:    CDF(i) = i / (n + 1)
california: CDF(i) = i / n
```
(`i` = rango ascendente 1..n de los valores ordenados; `n` = tamaño de la muestra)

**Estadístico de Finkelstein-Schafer (FS)** para una variable, mes y año candidato (Finkelstein & Schafer, 1971):

```
FS = (1/N) · Σ_{d=1}^{N} | CDF_candidato(x_d) − CDF_largo_plazo(x_d) |
```

donde `N` es el número de puntos del candidato (días si `cdf_method='daily'`, horas si `'hourly'`), y `CDF_largo_plazo` se interpola en cada valor `x_d` del candidato.

**FS ponderado total** para un año-mes candidato:

```
Total_W_FS = Σ_i  peso_i · FS_i        (suma sobre todas las variables ponderadas, tabla de §3.2)
```

**Filtro de completitud de datos** (`missing_data_threshold`, por defecto 0.9): un mes-año candidato se **excluye** si `puntos_válidos / puntos_esperados < 0.9` (siendo `puntos_esperados = días_del_mes × 24` en horario o `días_del_mes` en diario). Los meses excluidos se registran (`excluded_months`) y se informan por consola.

Para cada mes se retienen los **5 años con menor `Total_W_FS`** como candidatos iniciales (`candidate_months_pre_proximity`).

### 3.4 Paso 3 — *Proximity Ranking* (`sandia_step_3_proximity_ranking`)

Reordena los 5 candidatos FS según su cercanía a la estadística de largo plazo de temperatura y GHI, siguiendo el criterio de **Sawaqed, Zurigat & Al-Hinai (2005)**.

Para cada mes se calculan, sobre la temperatura media diaria (`T_air`/`T_air_mean`) y GHI (`GHI`/`GHI_sum`) de largo plazo: media, mediana, desviación típica y rango.

**Desviaciones absolutas del candidato respecto al largo plazo:**

```
err_t_mean    = |T_mean(candidato)   − T_mean(LP)|
err_t_median  = |T_mediana(candidato) − T_mediana(LP)|
err_ghi_mean  = |GHI_mean(candidato)  − GHI_mean(LP)|
err_ghi_median= |GHI_mediana(candidato)− GHI_mediana(LP)|
```

**Normalización** (`normalization_method`, por defecto `'std'`; denominadores `den_T`, `den_GHI`):

| Método | den_T | den_GHI |
|---|---|---|
| `std` (defecto) | σ_T (desv. típica LP) | σ_GHI (desv. típica LP) |
| `long_term_mean` | \|media_T LP\| | \|media_GHI LP\| |
| `range` | rango_T LP (máx−mín) | rango_GHI LP (máx−mín) |
| `weighted` | σ_T | σ_GHI |
| `no_normalization` | 1 | 1 |

(denominador protegido: si es 0/NaN, se usa 1.0)

**Puntuación de proximidad:**

```
si method != 'weighted':
    Proximity_Score = max(err_t_mean/den_T, err_t_median/den_T,
                            err_ghi_mean/den_GHI, err_ghi_median/den_GHI)

si method == 'weighted':
    Proximity_Score = w_t_mean·(err_t_mean/den_T)   + w_t_median·(err_t_median/den_T)
                    + w_ghi_mean·(err_ghi_mean/den_GHI) + w_ghi_median·(err_ghi_median/den_GHI)

    pesos por defecto: t_mean=0.30, t_median=0.20, ghi_mean=0.30, ghi_median=0.20  (suman 1.0)
```

> **Compatibilidad retro:** el alias histórico `normalization_method='sawaqed'` sigue aceptándose pero está **deprecado**, y se mapea internamente a `'weighted'` (emite `DeprecationWarning`).

Los 5 candidatos se reordenan de forma **ascendente** por `Proximity_Score` (mejor = menor puntuación).

### 3.5 Pasos 4-5 — Filtrado de persistencia y selección final del mes (`sandia_step_4_and_5_apply_persistence`)

Punto de partida: los 5 candidatos ya reordenados por proximidad. Se ofrecen **dos métodos** (`persistence_method`):

#### (a) `'sequential'` — exclusión secuencial determinista (usado por defecto en `generate_tmy()`)

Se calculan, para cada candidato, las **rachas (runs)** de días consecutivos:
- Temperatura media diaria **por encima** del percentil 67 (rachas "cálidas") **o por debajo** del percentil 33 (rachas "frías") de la distribución de largo plazo del mes.
- GHI diario **por debajo** del percentil 33 (rachas de "baja radiación").
- Umbrales configurables vía `thresholds=(0.33, 0.67)`; longitud mínima de racha configurable vía `min_run_length` (por defecto 1 día).

Se agregan en `Total_Runs` (nº total de rachas) y `Max_Run_Len` (racha más larga), y se aplican **3 pases** de exclusión:

```
PASE 1 — Nº de rachas:
  a) si todos tienen 0 rachas          → seleccionar directamente el rango-1 (mejor proximidad)
  b) si todos tienen el mismo nº rachas:
        - long. de racha desigual      → excluir el de racha más larga (empate → peor rango)
        - long. de racha igual         → excluir el peor rango (último de la lista)
  c) si el nº de rachas difiere        → excluir el de más rachas (empate → peor rango)

PASE 2 — Longitud de racha (sobre supervivientes del Pase 1):
  a) longitud desigual                 → excluir el de racha más larga
                                          (empate → más rachas totales, luego peor rango)
  b) longitud igual:
        - mismo nº de rachas           → excluir el peor rango
        - nº de rachas distinto        → excluir el de más rachas (empate → peor rango)

PASE 3 — Candidatos con 0 rachas (sobre supervivientes del Pase 2), según `zero_run_method`:
  - 'eliminate_worst_ranked' (defecto) → excluir solo el peor rango entre los de 0 rachas
  - 'eliminate_all'                    → excluir TODOS los de 0 rachas
  - 'eliminate_none'                   → no excluir ninguno
```

**Selección final (Paso 5):** entre los supervivientes, se elige el de **mejor rango de proximidad** (menor `Original_Rank`).

Cada decisión queda registrada con su motivo textual (p. ej. `"Excluded Pass 1 (Rule 1c: Max Runs)"`) en `validation_step4_persistence_sequential_details[mes]`.

#### (b) `'score'` — puntuación ponderada (alternativa)

```
Score = Total_W_FS
      + w_t_longest_run  · T_air_racha_más_larga
      + w_t_total_runs   · T_air_nº_rachas
      + w_ghi_longest_run· GHI_racha_más_larga
      + w_ghi_total_runs · GHI_nº_rachas

Pesos por defecto: w_t_longest_run=0.002, w_t_total_runs=0.001,
                    w_ghi_longest_run=0.001, w_ghi_total_runs=0.0005
```
Se elige el candidato con **menor Score**. Los pesos son personalizables vía `persistence_weights` (claves inválidas se avisan e ignoran).

`use_persistence=False` omite estos pasos y selecciona directamente el candidato de mejor rango FS/proximidad (`_select_months_by_fs_rank`).

### 3.6 Paso 6 — Ensamblado del TMY bruto (`sandia_step_6_assemble_tmy`)

Para cada uno de los 12 meses, se extrae el mes completo (con resolución horaria si `df_hourly` está disponible; si no, diaria) del **año seleccionado**, se re-etiqueta al año sintético 2000, se elimina el 29 de febrero si el año de origen era bisiesto, y se concatenan los 12 meses en `tmy_raw`.

### 3.7 Paso 7 — Suavizado de las uniones mensuales (`sandia_step_7_smooth_junctions`)

- **Requiere datos horarios** (`df_hourly` o `hourly_file_path`); si no están disponibles, se omite el suavizado (el TMY final = TMY bruto) con un aviso.
- Para cada una de las **11 uniones** entre meses consecutivos:
  1. Se ajusta un **spline de suavizado** (`scipy.interpolate.UnivariateSpline`, parámetro `s_factor`, por defecto `0.0` → interpolación exacta) usando los **dos meses completos** de datos horarios de sus respectivos años de origen.
  2. Se evalúa el spline sobre una **ventana configurable** alrededor de la unión (`hours` antes/después, por defecto 6 h; configurable de forma independiente por unión y por lado mediante el diccionario `smoothing_config`).
  3. Se reemplazan los valores brutos en esa ventana por los suavizados, **para todas las variables excepto `GHI` y `DNI`** (la radiación se deja intacta para no distorsionar la geometría solar).
- **Recorte de seguridad final:** valores negativos residuales (undershoot) en `GHI`, `DNI` o `Wind_speed` se recortan a 0.
- Genera automáticamente la tabla de validación `validation_step6_tmy_composition` y llama a `generate_full_summary()`.
- **Guarda sesión reproducible automáticamente** (`.pkl` + `.json`) si `save_session=True` (por defecto) — ver [§10](#10-session_manager--persistencia-de-sesión-transversal).

### 3.8 `generate_tmy()` — orquestador de los 7 pasos

```python
gen.generate_tmy(
    use_persistence=True,                       # aplica pasos 4-5
    persistence_thresholds=(0.33, 0.67),
    min_run_length=1,
    persistence_weights=None,                   # solo para persistence_method='score'
    persistence_method='sequential',             # 'sequential' (defecto) o 'score'
    zero_run_method='eliminate_worst_ranked',    # solo para 'sequential'
    completeness_threshold=0.9,
    save_validation_dfs=True,
    proximity_normalization_method='std',        # 'std'|'long_term_mean'|'range'|'weighted'|'no_normalization'
    proximity_normalization_weights=None,        # solo para 'weighted'
)
```

Ejecuta internamente, en orden: `sandia_step_1_load_and_prepare` → `sandia_step_2_select_candidates_fs` → `sandia_step_3_proximity_ranking` → (`sandia_step_4_and_5_apply_persistence` si `use_persistence=True`, si no `_select_months_by_fs_rank`) → `sandia_step_6_assemble_tmy` → `sandia_step_7_smooth_junctions`.

### 3.9 Exportación (`export_tmy`)

```python
gen.export_tmy('tmy_output.csv')   # también soporta .tmy / .xlsx
```

- Recorte de seguridad final de negativos en `GHI`/`DNI`/`Wind_speed`.
- **Añade columnas auxiliares**: cualquier variable presente en `df_hourly` pero ausente en `tmy_final` se ensambla igual que el TMY (mismos meses/años seleccionados) y se anexa.
- **Restaura los nombres de columna originales del fichero fuente** (inversos de `col_temp`, `col_dew`, `col_wind`, `col_ghi`, `col_dni`, `datetime_col`) antes de escribir.

> **Nota de unidades:** `TMYGenerator` es **agnóstico a la unidad** de cada variable durante todo el proceso estadístico (no convierte km/h ni hPa); simplemente preserva los valores tal como llegaron del fichero fuente. La conversión a unidades SI/EPW (m/s, Pa) ocurre exclusivamente en `HourlyEPWConverter` ([§4](#4-hourly_epw_converter--hourlyepwconverter--batchhourlyepwconverter)). Esta separación de responsabilidades (motor estadístico ↔ capa de exportación EPW) es una decisión de arquitectura relevante para la reproducibilidad del método.

### 3.10 Validación, diagnóstico y visualización

`TMYGenerator` mantiene, tras cada paso, un rico conjunto de **atributos de validación** (`validation_step2_fs_ranking_by_month`, `validation_step2_summary_fs_ranking`, `validation_step3_proximity_ranking`, `validation_step4_df_persistence_decision`, `validation_step4_persistence_sequential_details`, `validation_step4_persistence_score_details`, `validation_step5_selected_months_summary`, `validation_step6_tmy_composition`, `validation_full_summary`, `validation_selection_analysis`) que se incluyen automáticamente en la sesión persistida ([§10](#10-session_manager--persistencia-de-sesión-transversal)).

**Métodos de impresión/validación por consola:**

| Método | Descripción |
|---|---|
| `validate_step_1_data_loading()` | Estadísticos descriptivos de `df_hourly`/`df_daily` |
| `validate_fs_calculation(variable, month, year)` | Desglose paso a paso del cálculo FS para un caso concreto; devuelve un DataFrame con la interpolación |
| `validate_full_ranking_for_month(month)` | Ranking FS completo (todos los años) para un mes |
| `validate_persistence_selection()` | Imprime las tablas de decisión de persistencia (sequential o score) mes a mes |
| `validate_step_4_final_tmy()` | Tabla de composición del TMY + estadísticos descriptivos del TMY final |
| `summarize_fs_results()` | Tabla resumen del ranking FS de los 5 candidatos de cada mes |
| `check_input_expectations(file_path, weighting_method, data_frequency, column_mapping)` *(estático)* | Analiza un fichero de entrada y sugiere el `column_mapping` necesario, validando también el formato de la columna de tiempo |

**Métodos de visualización (matplotlib):**

| Método | Descripción |
|---|---|
| `plot_cdfs(month_to_plot, years_to_plot)` | CDFs de años concretos vs. CDF de largo plazo, para un mes |
| `plot_fs_details(var_to_plot, month_to_plot, year_to_plot)` | Visualización paso a paso del cálculo del estadístico FS (antes/después de interpolar) |
| `plot_junctions(junctions_to_plot, hours_around)` | Datos brutos (sin suavizar) alrededor de las uniones mensuales |
| `plot_smoothing_comparison(junctions_to_plot, hours_around)` | Comparación antes/después del suavizado, con los parámetros usados en el título |
| `plot_persistence_runs(month, years)` | Rachas de temperatura y GHI, con las bandas de racha resaltadas |
| `plot_annual_cdfs()` | CDF anual del TMY final vs. largo plazo, 4 variables principales |
| `plot_monthly_means()` | Medias mensuales (y GHI total) del TMY final vs. largo plazo |
| `plot_monthly_cdfs(sharex)` | Grid de 12 subplots (uno por mes) comparando CDF del TMY vs. largo plazo |

**Métodos de análisis y corrección (v4.09+):**

| Método | Descripción |
|---|---|
| `get_candidate_stats(month)` | DataFrame con T/GHI (media, diferencia vs. largo plazo, percentil) de los 5 candidatos tras *Proximity Ranking* |
| `generate_full_summary()` | Tabla consolidada de **una fila por mes** con las métricas clave de todos los pasos (FS, proximidad, persistencia, año seleccionado, diferencias T/GHI vs. largo plazo) → `validation_full_summary` |
| `analyze_selection(months, temp_diff_threshold=1.0, ghi_diff_threshold=None)` | Audita la selección de meses, marcando (`Flagged`) aquellos cuya T/GHI se desvía más del umbral respecto al largo plazo |
| `correct_selection_by_temperature(months, temp_diff_threshold=1.0, regenerate=True)` | Sustituye automáticamente las selecciones anómalas por el candidato del top-5 que minimiza \|T_mean − T_mean_LP\|, y opcionalmente regenera el TMY (bruto + suavizado) in-place |
| `plot_monthly_trend(months, variable, show_candidates=False)` | Tendencia interanual de la media mensual, año TMY marcado con ★, línea de tendencia lineal global; con `show_candidates=True` muestra también los otros candidatos del top-5 |
| `plot_monthly_series(months, variable)` | Series diarias de todos los años superpuestas (año TMY en rojo grueso, resto en azul claro) + media de largo plazo |
| `compare_tmy_versions(other_tmy_df, months, variable)` | Comparación lado a lado de dos versiones de TMY (p. ej. antes/después de `correct_selection_by_temperature`) |

### 3.11 Compatibilidad retroactiva

`tmy.py` mantiene, junto a los métodos `sandia_step_*` actuales, **alias deprecados** que envuelven a los nuevos y emiten `DeprecationWarning`: `step_1_load_and_prepare_data()`, `step_2_select_candidate_months()`, `step_3_apply_persistence()`, `step_4_create_and_smooth_tmy()`. También existen *properties* de compatibilidad para los nombres antiguos de los atributos de validación (`validation_st2_df_fs_ranking_by_month`, `validation_st2_summary_fs_ranking`, `validation_st3_df_persistence_decision`, `validation_st3_persistence_sequential_details`, `validation_st3_persistence_score_details`, `validation_st4_df_tmy_composition`), que redirigen transparentemente a los atributos `validation_step*` actuales.

---

## 4. `hourly_epw_converter` — `HourlyEPWConverter` / `BatchHourlyEPWConverter`

```python
from pyweatherfiles import hourly_epw_converter

converter = hourly_epw_converter.HourlyEPWConverter(
    file_path='weather_data.csv',      # ya limpio, sin huecos
    base_epw_path='template.epw',      # plantilla EPW (aporta lat/lon/elev/tz)
)
converter.process(output_pattern='city_{year}.epw')   # 1 EPW por año disponible
```

Convierte series horarias ya depuradas (CSV/Excel) a formato **EPW**, apto tanto para generar la serie "long-term" (un EPW por año) como para convertir el CSV/Excel resultante de `TMYGenerator.export_tmy()` en el EPW final del año típico.

### 4.1 Constructor

- `file_path`, `base_epw_path` (obligatorios).
- `lat, lon, elev, tz_hour` (opcionales): si no se indican, se **extraen automáticamente** del EPW plantilla vía `ladybug.epw.EPW(base_epw_path).location`.
- Mapeo de columnas configurable: `datetime_col='time'`, `col_temp='Dry-bulb temperature'`, `col_dew='Dew Point temperature'`, `col_wind='Wind Speed'`, `col_ghi='Global Horizontal Irradiance '`, `col_dni='Beam Normal Irradiance '`, `col_rh='Relative Humidity'`, `col_pres='Pressure'`, `col_wind_dir='Wind Direction'`, `col_dhi='Diffuse Horizontal Irradiance'`, `col_cloud_cover='Total Cloud Cover'`, `col_irh='IRh'` — o un `column_mapping` dict global.
- `preserve_extra` (bool): si `True`, no anula el campo `total_sky_cover` cuando hay columna de nubosidad disponible.
- `remove_leap_day` (bool, por defecto `True`): elimina el 29 de febrero para mantener el estándar EnergyPlus de 8760 h/año.

### 4.2 Carga de datos (`_load_file`)

- Lee `.xlsx` o `.csv`, parsea el índice temporal, **ordena cronológicamente**.
- **Conversión de unidades automática (convención fija del paquete):**
  - Velocidad de viento: `Wind_speed = Wind_speed_input / 3.6` → **se asume la entrada en km/h** y se convierte a m/s.
  - Presión: `Pressure = Pressure_input * 100.0` → **se asume la entrada en hPa** y se convierte a Pa.
- Registra los años disponibles (`available_years`); `get_year_data(year)` aísla el DataFrame de un año concreto.

### 4.3 Fórmulas auxiliares

**Humedad relativa** (si no viene en el fichero), a partir de temperatura de bulbo seco `T_db` y de rocío `T_dp` (fórmula tipo Magnus/August-Roche-Magnus):

```
e_s(T) = 6.112 · exp( 17.67·T / (T + 243.5) )      [presión de vapor de saturación]
RH = 100 · e_s(T_dp) / e_s(T_db)                    [recortada a [0, 100] %]
```

**Presión atmosférica estándar por elevación** (fórmula barométrica internacional, si no viene en el fichero):

```
P(h) = P0 · (1 − L·h / T0) ^ (g·M / (R·L))

P0 = 101 325 Pa      L  = 0.0065 K/m
T0 = 288.15 K        g  = 9.80665 m/s²
M  = 0.0289644 kg/mol   R  = 8.31447 J/(mol·K)
```

**Irradiancia difusa horizontal (DHI)**, si no viene en el fichero, reconstruida a partir de GHI y DNI usando la posición solar exacta (`ladybug.sunpath.Sunpath`, hora evaluada en el punto medio de cada hora, `hora + 0.5`):

```
zenith = 90° − altitud_solar
cos_zenith = cos(zenith)

si cos_zenith ≤ 0.01:   DHI = GHI                (sol muy bajo / bajo el horizonte)
en otro caso:            DHI = max(0, GHI − DNI·cos_zenith)
```

### 4.4 Transformación a EPW (`transform_to_epw`)

1. Filtra/ajusta el año a 8760 u 8784 horas según `remove_leap_day` y si el año es bisiesto.
2. Carga el EPW plantilla con `ladybug.epw.EPW`, actualiza cabecera (lat, lon, elevación, huso horario, comentarios) y el `AnalysisPeriod`.
3. Extrae e inyecta (mediante `_set_epw_values`, ver más abajo): `dry_bulb_temperature`, `dew_point_temperature`, `relative_humidity`, `wind_speed`, `wind_direction` (0 si no existe), `global_horizontal_radiation`, `direct_normal_radiation`, `diffuse_horizontal_radiation`, `atmospheric_station_pressure`. Opcionalmente `total_sky_cover` e `horizontal_infrared_radiation_intensity` si esas columnas existen.
4. **Corrección de desfase Ladybug (`_set_epw_values`)**: los campos EPW marcados como *point-in-time* sufren un desfase de índice interno en `ladybug-core`; el conversor lo compensa desplazando la serie una posición (`[último] + resto[:-1]`) antes de asignarla.
5. **Neutralización de variables EPW no usadas por EnergyPlus**: 15 campos (radiación/iluminancia extraterrestre, iluminancias, cobertura de nubes, visibilidad, altura de techo de nubes, agua precipitable, profundidad óptica de aerosoles, días desde última nevada, albedo, precipitación líquida) se rellenan con los **códigos de "valor ausente" oficiales del formato EPW** (p. ej. `9999`, `999999`, `99`, `0.999`), en lugar de dejarlos en 0, evitando que EnergyPlus los interprete erróneamente como datos válidos.
6. Guarda el EPW resultante con `epw_data.save(...)`.

### 4.5 Procesamiento por lotes (`process`)

- Genera **un EPW por año** disponible (o por una lista concreta de años vía `years=[...]`), nombrando cada fichero según `output_pattern` (p. ej. `'city_{year}.epw'`) o, por defecto, `'{basename}_{year}.epw'`.
- Al finalizar, si `save_session=True` (por defecto), guarda automáticamente una **sesión reproducible** (`.pkl` + `.json`) — ver [§10](#10-session_manager--persistencia-de-sesión-transversal).

### 4.6 `BatchHourlyEPWConverter` — orquestación multi-ciudad

```python
from pyweatherfiles import hourly_epw_converter

config = hourly_epw_converter.BatchHourlyEPWConverter.suggest_config(
    identifiers=['MADRID', 'SEVILLA'],
    data_files='ruta/a/datos/',       # carpeta o lista de ficheros
    base_epw_files='ruta/a/epws/',    # carpeta o lista de plantillas EPW
)
batch = hourly_epw_converter.BatchHourlyEPWConverter(config, output_dir='salida/')
batch.process_all(output_pattern='{identifier}_{year}.epw')
```

- `cities_config`: lista de dicts (o `DataFrame`) con, como mínimo, `file_path` y `base_epw_path` por ciudad; claves opcionales `lat/lon/elev/tz_hour`, `years`, y cualquier variable libre usada para formatear `output_pattern`.
- `get_mandatory_config_keys()` *(classmethod)*: imprime/devuelve las claves obligatorias.
- `suggest_config(identifiers, data_files, base_epw_files)` *(classmethod)*: empareja automáticamente, por coincidencia de nombre (subcadena, insensible a mayúsculas), cada identificador con su fichero de datos y su plantilla EPW, extrayendo de esta última lat/lon/elev/tz_hour vía Ladybug.
- `process_all(output_pattern, remove_leap_day=True, **global_kwargs)`: itera cada ciudad, instancia un `HourlyEPWConverter` y llama a `process()`, combinando `global_kwargs` con las variables propias de cada ciudad para rellenar `output_pattern`; imprime un resumen final y guarda una sesión de lote.

---

## 5. `met_epw_converter` — `convert_met_to_epw` / `convert_epw_to_met`

```python
from pyweatherfiles import met_epw_converter

met_epw_converter.convert_met_to_epw(
    met_path='reference_climate.met',
    base_epw_path='template.epw',
    epw_path='reference_climate.epw',
    replace_unused_with_missing=True
)
```

### 5.1 El formato `.met`

Fichero de texto plano con:
- **Línea de metadatos** con latitud, longitud y elevación (localizada automáticamente si no está en la posición esperada, buscando en las primeras 10 líneas un valor de latitud plausible `[-90, 90]`).
- **Bloque de datos** de 13 columnas (`Month, Day, Hour, DryBulb, SkyTemp, RadDirectaHoriz, RadDifusaHoriz, AbsHum, RelHum, WindSpeed, WindDir, Azimuth, Zenith`) o variante de 15 columnas (sin `WindDir`, con 2 columnas auxiliares no usadas).
- El huso horario se aproxima como `tz_hour = round(longitud / 15.0)` (huso solar nominal, no necesariamente el huso civil/político real).
- Este es el formato de los ficheros climáticos de referencia usados en el **Código Técnico de la Edificación español** (CTE DB-HE), tipo LIDER/CALENER.

### 5.2 Fórmulas de conversión (MET → EPW)

**Temperatura de rocío** (inversión de la fórmula de Magnus, a partir de `T_db` y `RH`):

```
b = 17.62,  c = 243.12
γ = b·T_db/(c+T_db) + ln(RH/100)
T_dp = c·γ / (b − γ)
```

**Presión atmosférica** reconstruida por ingeniería inversa a partir de la humedad absoluta (`AbsHum`, W) que trae el `.met`:

```
e_s(T) = 610.78 · 10^(7.5·T/(237.3+T))     [presión de vapor de saturación, Pa]
e = e_s(T_db) · RH/100                      [presión de vapor actual]
P_atm = e · (1 + 0.62198 / W)

→ si P_atm ∉ [50 000, 110 000] Pa (valor no físico), se usa la fórmula
  barométrica estándar por elevación (idéntica a la de §4.3) como respaldo.
```

**Temperatura de cielo → radiación infrarroja horizontal** (ley de Stefan-Boltzmann):

```
IR = σ · (T_cielo + 273.15)⁴          σ = 5.6697 × 10⁻⁸ W/(m²·K⁴)
```

**Reconstrucción astronómica de GHI/DNI** (con control de calidad):

```
GHI = RadDirectaHoriz + RadDifusaHoriz     (negativos de entrada recortados a 0, contados)

Para cada hora, con posición solar exacta evaluada en (hora − 0.5):
  zenith = 90° − altitud_solar ;  cos_zenith = cos(zenith)

  si cos_zenith ≤ 0.01  ó  RadDirectaHoriz ≤ 0:   DNI = 0
  en otro caso:
      DNI = RadDirectaHoriz / cos_zenith
      DNI = min(DNI, 1367 W/m²)      ← recorte a la constante solar (nº de recortes registrado)
```

Tras el cálculo, el conversor imprime un **informe de control de calidad**:
- Estadísticos de DNI (mínimo, percentil 95, máximo; nº de horas de "sol bajo" y nº de recortes por DNI > 1367 W/m²; nº de valores de radiación directa horizontal negativa detectados en la entrada).
- **Cierre de balance de radiación**: `residual = GHI − (DHI + DNI·cos_zenith)`, reportando la media y el percentil 95 del valor absoluto.

### 5.3 Resto del proceso (MET → EPW)

- Fuerza un `AnalysisPeriod` estándar no bisiesto de 8760 h.
- Aplica la misma corrección de desfase *point-in-time* que en `HourlyEPWConverter` (§4.4, punto 4).
- Si `replace_unused_with_missing=True`, neutraliza los mismos 15 campos EPW no usados con sus códigos oficiales de valor ausente (idéntico a §4.4, punto 5).
- Guarda sesión reproducible vía `save_function_session` (API de función, no de clase) si `save_session=True` (por defecto).

### 5.4 Conversión inversa: `convert_epw_to_met(epw_path, met_path)`

Reconstruye un `.met` (formato de 13 columnas) a partir de un EPW existente:
- `RadDirectaHoriz = GHI − DHI` (recortado ≥ 0); `RadDifusaHoriz = DHI` directamente.
- Temperatura de cielo: inversión de Stefan-Boltzmann a partir de `horizontal_infrared_radiation_intensity`.
- Humedad absoluta: fórmula psicrométrica estándar a partir de T, HR y presión (calculada por elevación).
- Marca de tiempo fija en el año 2005 (`Mes_Num`, `Dia`, `Hora`); `Azimuth`/`Zenith` se dejan como `0` (no se reconstruyen); no se almacena DNI (el formato `.met` solo guarda componentes horizontales).

---

## 6. `degree_hours` — `DegreeHoursCalculator` / `EpwBatchAnalyzer`

```python
from pyweatherfiles.degree_hours import DegreeHoursCalculator

calc = DegreeHoursCalculator('city_tmy.epw')
results = calc.calculate('building_model.idf', frequency=['hourly', 'daily', 'monthly'], mode='both')
print(results['monthly'])
calc.export_results('degree_hours.xlsx')
```

Calcula **grados-hora de calefacción (HDH) y refrigeración (CDH)** a partir de un EPW y de unas consignas de temperatura, extraídas de un fichero **IDF** (EnergyPlus) o definidas mediante un **diccionario personalizado**.

### 6.1 Constructor (`DegreeHoursCalculator(epw_path, year=None)`)

- Carga el EPW vía `ladybug.epw.EPW`; construye `self.temperatures` (serie horaria de temperatura de bulbo seco indexada por año sintético).
- Construye `self.epw_data`: un DataFrame con **todas** las variables horarias EPW disponibles (22 posibles: temperatura, punto de rocío, humedad relativa, presión, radiación/iluminancia global-directa-difusa, luminancia cenital, viento, cobertura de cielo, visibilidad, altura de nubes, IR horizontal, agua precipitable, profundidad óptica de aerosoles, nieve, precipitación) — útil también para `EpwBatchAnalyzer` (§6.4) y para `EpwTrendAnalyzer` (§7).

### 6.2 Fuente de consignas: IDF o diccionario personalizado

**(a) Desde un IDF** — `extract_setpoints_from_idf(idf_path, zone_name=None)`:
- Carga el edificio vía `besos.eppy_funcs.get_building` (con `eppy` como *fallback*).
- Para cada `ZONECONTROL:THERMOSTAT`, localiza su `THERMOSTATSETPOINT:DUALSETPOINT` asociado y extrae los *schedules* de consigna de calefacción/refrigeración.
- **Resuelve los *schedules* de EnergyPlus** soportando dos tipos:
  - `SCHEDULE:COMPACT`: parser completo de bloques `Through: MM/DD` (rangos de fecha), `For: <tipos_de_día>` (`Weekdays`, `Weekends`, `AllDays`, `AllOtherDays`, días individuales), y pares `Until: HH:MM`/valor, construyendo un perfil horario de 24 h por tipo de día y rango de fechas.
  - `SCHEDULE:YEAR` → `SCHEDULE:WEEK:DAILY` → `SCHEDULE:DAY:HOURLY`/`SCHEDULE:DAY:INTERVAL`: resuelve la cadena completa de referencias.
- También extrae los ***schedules* de disponibilidad del sistema HVAC** (`ZoneHVAC:IdealLoadsAirSystem`, vía la cadena `ZoneHVAC:EquipmentConnections` → `ZoneHVAC:EquipmentList` → `ZoneHVAC:IdealLoadsAirSystem`): cuando el sistema está programado como apagado, los grados-hora de ese periodo se anulan (no se cuentan). Zonas sin sistema `IdealLoads` se asumen disponibles el 100% del tiempo.

**(b) Desde un diccionario personalizado** — 4 tipos soportados en `config['type']`:

| `type` | Estructura | Uso |
|---|---|---|
| `'constant'` | `{'heating': 21.0, 'cooling': 26.0}` | Consigna fija todo el año |
| `'daily'` | `{'heating': [...365/366 valores...], 'cooling': [...]}` | Un valor por día del año |
| `'weekly'` | `{'periods': {nombre: ('MM-DD','MM-DD')}, 'patterns': {periodo: {tipo_día: {'heating':val,'cooling':val}}}}` | Un valor por tipo de día (`monday`…`sunday`, `weekday`, `weekend`, `alldays`) y periodo |
| `'hourly_weekly'` | Como `'weekly'` pero cada patrón es una lista de 24 valores horarios | Máxima granularidad sin IDF |

### 6.3 Cálculo (`calculate`)

```
HDH_h = max(0, SP_calefacción_h − T_h)     (solo horas en `hours`, si no 0)
CDH_h = max(0, T_h − SP_refrigeración_h)   (solo horas en `hours`, si no 0)
```

- Las **consignas se enmascaran con la disponibilidad HVAC** (cuando procede de IDF): si el sistema está apagado, HDH/CDH = 0 en esa hora.
- Filtro opcional de periodo (`start_date`/`end_date`, formato `'DD/MM'`, soporta rangos que cruzan el año nuevo, p. ej. diciembre→febrero) y de horas del día (`hours=[0..23]`).
- Agregación configurable (`frequency`): `'hourly'`, `'daily'` (`.resample('D').sum()`), `'monthly'` (`.resample('ME').sum()`), `'yearly'` (`.resample('YE').sum()`).
- `mode`: `'heating'`, `'cooling'` o `'both'`.
- `zone_name`: si `None`, promedia consignas y disponibilidad entre **todas** las zonas con termostato del IDF.
- Resultados en `self.result_hourly/daily/monthly/yearly`; sesión reproducible guardada automáticamente.

### 6.4 Visualización y exportación

- `plot(setpoint_source, period='year'|'month'|'week'|'day', period_value=..., show_air_temp=False)`: compara gráficamente las consignas (y opcionalmente la temperatura EPW). Vista anual = media diaria + banda min/máx; vistas mes/semana/día = resolución horaria. Donde el HVAC está apagado, la consigna se enmascara a `NaN` (hueco visual) para QA rápida antes de calcular.
- `export_results(output_path='degree_hours_results.xlsx')`: exporta cada tabla de frecuencia calculada a una hoja Excel distinta.

### 6.5 `EpwBatchAnalyzer` — análisis comparativo multi-EPW

```python
from pyweatherfiles.degree_hours import EpwBatchAnalyzer

batch = EpwBatchAnalyzer(
    epw_paths=['city_tmy.epw', 'city_met.epw', 'city_2020.epw'],
    setpoint_source='building_model.idf',
    epw_variables={'global_horizontal_radiation': ['sum', 'mean']},
    hours={'morning': list(range(9)), 'all_day': list(range(24))},
    frequencies=['hourly', 'daily', 'monthly'],
    start_date='01/06', end_date='30/09',
)
results = batch.run()          # dict {freq: DataFrame con columnas MultiIndex (epw, variable)}
batch.export('batch_degree_hours.xlsx')
```

- Ejecuta `DegreeHoursCalculator` sobre **múltiples EPW** y **múltiples escenarios de horas** (`hours` puede ser una lista plana, una lista de listas, o un dict de escenarios nombrados — cada uno genera columnas con sufijo propio, p. ej. `heating_dh_morning`).
- `epw_variables` acepta una lista simple (agregación automática: `sum` para variables de radiación/iluminancia/precipitación, `mean` para el resto) o un dict `{variable: agg_func | [agg_func, ...]}` (`'sum'/'mean'/'max'/'min'/'std'`).
- Resultado: DataFrame(s) con columnas **MultiIndex** `(epw, variable)`, uno por frecuencia solicitada — ideal para tablas comparativas de un artículo (TMY vs. años reales vs. fichero de referencia normativo).
- `export()` escribe una hoja combinada `all_epws_<freq>` por frecuencia (y, si solo se pidió una frecuencia, además una hoja por EPW).

---

## 7. `epw_trend_analyzer` — `EpwTrendAnalyzer`

```python
from pyweatherfiles import EpwTrendAnalyzer, TrendConfig, OutputConfig

analyzer = EpwTrendAnalyzer(
    trend_config=TrendConfig(root_dir='longterm_epw/'),   # busca *_????.epw, p. ej. seville_2005.epw
    output_config=OutputConfig(output_dir='trend_results/'),
)
outputs = analyzer.run()   # discover_files → compute_metrics → fit_city_trends → fit_global_models → export_outputs
```

Analiza **tendencias climáticas multianuales** (calentamiento, olas de calor) sobre una colección de EPWs anuales nombrados `city_year.epw` — **exactamente el patrón de salida que produce `HourlyEPWConverter.process()`** (§4), lo que conecta de forma natural la serie "long-term" generada en el pipeline con este analizador.

### 7.1 Configuración (`TrendConfig` / `OutputConfig`, *dataclasses*)

`TrendConfig`: `root_dir`, `file_glob="*_????.epw"`, `filename_regex=r"^(?P<city>[A-Za-z]+)_(?P<year>\d{4})\.epw$"`, `abs_hot_threshold_c=35.0`, `local_hot_percentile=90.0`, `min_heatwave_length_days=3`, `city_trend_targets=("t_mean_annual","t_p95_annual")`, `primary_target="t_mean_annual"`, `secondary_target="t_p95_annual"`, `min_slope_for_practical_significance=0.02`.

`OutputConfig`: `output_dir` + flags de qué artefactos generar (`save_csv`, `save_xlsx`, `save_plots`, `save_report`, `save_markdown_report`, `write_config_snapshot`) + nombres de fichero configurables para cada salida.

Constructores alternativos: `EpwTrendAnalyzer.from_dict(config)`, `.from_json(path)`, `.from_yaml(path)` (YAML requiere `pyyaml`).

### 7.2 Pipeline (`run()` = 5 pasos encadenables)

1. **`discover_files()`**: busca en `root_dir` los ficheros que casan con `file_glob`, parsea `city`/`year` con `filename_regex`; genera `files_df` y `coverage_df` (por ciudad: nº de años, rango, años faltantes dentro del rango).
2. **`compute_metrics()`**: para cada EPW, calcula (reutilizando `DegreeHoursCalculator` internamente para la temperatura horaria): `t_mean_annual`, `t_median_annual`, `t_p95_annual` (percentil 95), `hot_hours_abs`/`hot_days_abs` (recuento por encima de `abs_hot_threshold_c`). Añade **métricas de olas de calor**:
   - Umbral climatológico local por día del año (`month-day`): percentil `local_hot_percentile` del Tmax de ese día concreto a lo largo de todos los años de esa ciudad (con *fallback* al percentil de toda la ciudad si faltan datos para ese día-mes exacto).
   - Un día es "caluroso" si supera ese umbral local (`hot_local`) o el umbral absoluto fijo (`hot_abs`).
   - Rachas de días calurosos consecutivos de longitud ≥ `min_heatwave_length_days` cuentan como eventos de ola de calor (`heatwave_events_local/abs`, `heatwave_days_local/abs`).
3. **`fit_city_trends()`**: regresión lineal OLS (`scipy.stats.linregress`) por ciudad de cada métrica de `city_trend_targets` frente al año → pendiente (°C/año), intercepto, R², p-valor, error estándar.
4. **`fit_global_models()` / `fit_global_model(target)`**: ajusta un **modelo global de efectos fijos** `target ~ year + C(city)` por mínimos cuadrados ordinarios (matriz de diseño con `pd.get_dummies(city, drop_first=True)` + intercepto + año; resuelto vía `(XᵀX)⁻¹XᵀY`, con pseudo-inversa como respaldo si la matriz es singular). Reporta la **pendiente común a todas las ciudades tras controlar por el nivel climático propio de cada una** (°C/año), su error estándar, estadístico t, p-valor bilateral (t de Student con `n_obs − n_parámetros` grados de libertad), intervalo de confianza al 95%, R² y tamaños muestrales — un estimador de **panel de datos** con efectos fijos por ciudad, técnica estadísticamente rigurosa y citable en la sección de métodos si se usa análisis de tendencias en el artículo.
5. **`export_outputs()`**: escribe `annual_metrics.csv`, `city_trends.csv`, `global_trend.csv`, `coverage_summary.csv`, un `trend_outputs.xlsx` combinado, 3 figuras PNG (panel de tendencia por ciudad para la media anual y para el P95, y un gráfico "ajustado" globalmente tras eliminar los efectos fijos de ciudad), un informe de texto `conclusion_report.txt` con un veredicto automático (positivo/significativo/relevante en la práctica según los umbrales configurados), un informe Markdown más detallado `conclusion_report.md`, y una instantánea `used_config.json` de la configuración exacta usada (reproducibilidad).

### 7.3 Otros métodos públicos

`plot()` (genera solo las figuras), `get_results()` (devuelve todo en memoria), `to_json()` (serializa la configuración efectiva), `build_city_figure()` / `build_global_adjusted_figure()` (para personalizar figuras antes de guardarlas), `export_markdown_report()`. Función de conveniencia a nivel de módulo: `run_analysis(root_dir, output_dir)` (pipeline completo con configuración por defecto).

---

## 8. `epw_comparator` — comparación de ficheros EPW

```python
from pyweatherfiles import epw_comparator

epw_comparator.compare_epw_files('base.epw', 'generated.epw')          # informe por consola (tabulate)
df = epw_comparator.create_comparison_hourly_dataframe('base.epw', 'generated.epw')  # DataFrame horario
```

| Función | Descripción |
|---|---|
| `explore_epw_structure(epw_path)` | Diagnóstico: vuelca la estructura de `EPW.to_dict()` (claves, tipos, vista previa) — útil para localizar las colecciones de datos horarios |
| `compare_epw_files(base_epw_path, generated_epw_path)` | Informe de consola (vía `tabulate`) comparando cabecera (ciudad, lat, lon, huso horario, elevación, comentarios) y estadísticos descriptivos de la diferencia (generado − base) para 9 variables climáticas clave |
| `create_comparison_dataframe(base_epw_path, generated_epw_path)` | DataFrame lado a lado construido desde `EPW.to_dict()['data_collections']` de Ladybug, con columnas en español (`TempBulboSeco`, `HumedadRelativa`, etc.) sufijadas `_Base`/`_Generado` |
| `create_comparison_hourly_dataframe(base_epw_path, generated_epw_path)` | **La función usada en el caso de estudio del artículo** — lee ambos EPW directamente como CSV (saltando las 8 líneas de cabecera), asigna los 35 nombres de campo oficiales del diccionario de datos EPW, y devuelve un único DataFrame con columnas `Base_*`/`Generated_*` alineadas hora a hora. Usa `encoding='latin-1'` para tolerar tildes en EPWs de origen español. Guarda sesión reproducible por defecto |

---

## 9. `climate_processor` — `ClimateProcessor` (depuración/relleno de series horarias)

```python
from pyweatherfiles.climate_processor import ClimateProcessor

proc = ClimateProcessor('raw_station_data.xlsx', lat=37.38, lon=-5.98, alt=15)
proc.export_complete_report('quality_report.xlsx')  # datos rellenos + resumen + huecos + estadísticas anuales/mensuales
```

Módulo de **pre-procesado** (no exportado en `__init__.py`, requiere `pvlib`), pensado para depurar y rellenar huecos en series horarias brutas de estación **antes** de que sirvan de entrada a `TMYGenerator`/`HourlyEPWConverter` (aguas arriba del resto del pipeline).

### 9.1 Pipeline automático (se ejecuta íntegramente al instanciar la clase)

1. **`_load_data`**: lee CSV/Excel (en Excel asume una fila de unidades bajo la cabecera, `skiprows=[1]`), parsea la primera columna como fecha (`dayfirst=True`), ordena y la fija como índice; conserva una copia `df_before` sin modificar para comparar antes/después.
2. **`_map_variables`**: detección automática de columnas por coincidencia de palabra clave (insensible a mayúsculas) para 10 variables canónicas: `Dry-bulb` ('dry'), `Dew Point` ('dew'), `RH` ('humidity'), `WindDir` ('direction'), `WindSpeed` ('speed'), `Pressure` ('pressure'), `GHI` ('global'), `BHI` ('beam'+'horiz'), `DHI` ('diffuse'), `BNI` ('normal').
3. **`_reindex`**: reindexado a un `DatetimeIndex` horario continuo entre el mínimo y el máximo timestamp (expone los huecos reales como filas `NaN`).
4. **`_fill_data`** — motor de relleno, con estrategia y límite máximo de hueco específicos por variable (más allá del límite, el hueco se deja deliberadamente sin rellenar):

   | Variable | Método | Límite máx. de hueco |
   |---|---|---|
   | Presión | Interpolación lineal | 72 h |
   | Temperatura seca / rocío | *Spline* cúbico (orden 3) | 24 h |
   | Humedad relativa | Fórmula de Magnus (ver abajo) + interpolación lineal residual | 24 h |
   | Velocidad de viento | Interpolación lineal | 3 h |
   | Dirección de viento | Interpolación lineal | 2 h |
   | GHI / DHI / BNI | Interpolación lineal (huecos ≤3h) + método del índice de cielo despejado (huecos 3-24h, diurno) | 24 h (huecos nocturnos → 0) |

   **Humedad relativa reconstruida** (Magnus/August-Roche-Magnus), cuando faltan RH pero hay ambas temperaturas:
   ```
   RH = 100 · exp(17.625·Td/(243.04+Td)) / exp(17.625·T/(243.04+T))     [recortado a [0,100]]
   ```

   **Relleno de radiación solar por índice de cielo despejado** — el componente más sofisticado: usa `pvlib.location.Location.get_clearsky()` para obtener la referencia teórica de cielo despejado (GHI/DHI/DNI) en el sitio y las marcas de tiempo exactas. Huecos cortos (≤3h) se interpolan linealmente. Huecos medios (3-24h, solo en horas diurnas, `GHI_despejado > 5 W/m²`) se rellenan reconstruyendo un **índice de claridad** `kt = min(1.2, observado/despejado)`, suavizado con una mediana móvil centrada de 24h, y aplicado como `valor = GHI_despejado × kt_suavizado` — preservando patrones de nubosidad realistas en vez de una interpolación ingenua. Huecos nocturnos se rellenan con 0. Finalmente, si están presentes GHI y DHI, se recalcula **`BHI = GHI − DHI`** (recortado ≥ 0) para asegurar la consistencia interna de las tres componentes de radiación.

5. **`_calculate_availability_after`**: recalcula el % de completitud y construye una tabla `summary` (`Before_%`, `After_%`, `Gain_%` por variable).
6. **`_generate_statistics_tables`**: construye 3 tablas de control de calidad:
   - `gaps_df`: cada hueco que **sí** se pudo interpolar (variable, inicio, fin, horas interpoladas).
   - `annual_stats`: por año × variable — nº total de huecos, completados al 100% / parciales / no rellenados, horas originalmente perdidas/rellenadas/aún vacías, y una media de horas rellenadas por día.
   - `max_gaps_df`: por año y por mes, el hueco más largo (en horas) de cada variable, marcado `FILLED`/`NOT FILLED (>Xh)` según el límite específico de esa variable.

### 9.2 Exportación

`export_filled_data(output_name)` (solo datos rellenos), `export_annual_statistics(output_name)` (informe de calidad `annual_stats` + `max_gaps`), `export_complete_report(output_name)` (Excel con 5 hojas: datos rellenos, resumen, huecos, estadísticas anuales, huecos máximos) — todo vía `openpyxl`.

---

## 10. `session_manager` — persistencia de sesión (transversal)

Módulo usado **transversalmente** por casi todos los demás (`tmy`, `hourly_epw_converter`, `met_epw_converter`, `degree_hours`, `epw_comparator`) para guardar automáticamente (`save_session=True` por defecto en todas las clases/funciones principales) una **sesión reproducible**:

- **`.pkl`** (`save_object_session` / `save_function_session`): el objeto completo serializado (con *fallback* parcial — si algún atributo no es serializable, se sustituye por un marcador de texto y se conserva el resto).
- **`.json`**: instantánea legible por humanos — timestamp, versión del paquete, y todos los atributos públicos convertidos a forma segura para JSON (los `DataFrame`/`Series`/`ndarray` se resumen con forma, columnas y tipos; listas largas truncadas a los primeros 10 elementos).

**Nomenclatura de fichero** (determinista, evita colisiones y facilita trazabilidad):

```
{Prefijo}_{slug_input_1}_{slug_input_2}_{slug_input_3}_{hash_md5_8_caracteres}.pkl / .json
```

Recuperación: `pyweatherfiles.session_manager.load_session(pkl_path)`.

Esto permite **auditar y reproducir exactamente** cada ejecución (parámetros de entrada + resultado completo) — valioso para la sección de metodología/reproducibilidad de un artículo científico.

---

## 11. Dependencias completas por módulo

| Módulo | Dependencia | Tipo | Comportamiento si falta |
|---|---|---|---|
| `tmy` | `pandas`, `numpy`, `scipy`, `matplotlib` | Obligatoria | — |
| `hourly_epw_converter` | `ladybug-core` | Obligatoria (guardada) | `ImportError` con mensaje explicativo |
| `met_epw_converter` | `ladybug-core` | Obligatoria (guardada) | `ImportError` con mensaje explicativo |
| `degree_hours` | `ladybug-core` | Obligatoria (guardada) | `ImportError` con mensaje explicativo |
| `degree_hours` | `besos` (+ `eppy` como *fallback*) | Opcional (guardada) | `extract_setpoints_from_idf()` no funcionará sin `besos` |
| `degree_hours` | `accim` | Opcional (guardada) | Se omite el saneado de acentos en rutas IDF |
| `epw_trend_analyzer` | `scipy.stats`, `matplotlib` | Obligatoria | — |
| `epw_trend_analyzer` | `pyyaml` | Opcional (solo `from_yaml()`) | `ImportError` con mensaje explicativo |
| `epw_comparator` | `ladybug-core` | Obligatoria (guardada) | `ImportError` con mensaje explicativo |
| `epw_comparator` | `tabulate` | Obligatoria del módulo (**no guardada**) | `ImportError` estándar al importar el módulo |
| `climate_processor` | `pvlib` | Obligatoria del módulo (**no guardada**) | `ImportError` estándar al importar el módulo |
| `session_manager` | `numpy`, `pandas` | Obligatoria | — |

> Nota: `pvlib` (`climate_processor`) y `tabulate` (`epw_comparator`) se importan sin bloque `try/except`, a diferencia de `ladybug-core` (que sí tiene un mensaje de error personalizado en todos los módulos que la usan). Esto solo afecta si se importa explícitamente ese submódulo (`climate_processor`/`epw_comparator` no forman parte de la API mínima de `__init__.py`).

---

## 12. Ejemplos rápidos por módulo

**TMY con pesos y columnas personalizadas, datos diarios, método TMY3** (`examples/using_tmy_generator.py`):

```python
from pyweatherfiles import tmy

column_mapping = {
    'fecha': 'time',
    'Dry-bulb temperature_max': 'T_air_max', 'Dry-bulb temperature_min': 'T_air_min',
    'Dry-bulb temperature_mean': 'T_air_mean',
    'Dew Point temperature_max': 'T_dew_max', 'Dew Point temperature_min': 'T_dew_min',
    'Dew Point temperature_mean': 'T_dew_mean',
    'Wind speed_max': 'Wind_speed_max', 'Wind speed_mean': 'Wind_speed_mean',
    'GHI_sum': 'GHI_sum', 'DNI_sum': 'DNI_sum',
}
gen = tmy.TMYGenerator(
    file_path='MADRID.xlsx', cdf_method='daily', data_frequency='daily',
    column_mapping=column_mapping, weighting_method='tmy3', save_validation_dfs=True,
)
gen.generate_tmy(use_persistence=True)
gen.export_tmy('MADRID_TMY_persistence_tmy3.csv')
```

**Grados-hora individual con visualización previa** (`examples/degreehours simple.py`):

```python
from pyweatherfiles.degree_hours import DegreeHoursCalculator

calc = DegreeHoursCalculator('city_tmy.epw')
calc.plot('building.idf', period='day', period_value=['06-10', '06-11'], show_air_temp=True)
results = calc.calculate('building.idf', frequency=['hourly', 'daily', 'monthly'], mode='both')
calc.export_results('degree_hours.xlsx')
```

**Grados-hora comparativo multi-EPW, multi-escenario horario** (`examples/degreehours batch.py`):

```python
from pyweatherfiles.degree_hours import EpwBatchAnalyzer

batch = EpwBatchAnalyzer(
    epw_paths=['city_tmy.epw', 'city_met.epw', 'city_2005.epw'],
    setpoint_source='building.idf',
    epw_variables={'global_horizontal_radiation': ['sum', 'mean']},
    hours={'morning': list(range(9)), 'all_day': list(range(24))},
    mode='both', frequencies=['hourly', 'daily', 'monthly'],
    start_date='01/06', end_date='30/07',
)
results = batch.run()
batch.export('resultados_verano.xlsx')
```

**Análisis de tendencias sobre EPWs anuales**:

```python
from pyweatherfiles import EpwTrendAnalyzer, TrendConfig, OutputConfig

analyzer = EpwTrendAnalyzer(TrendConfig(root_dir='longterm_epw/'), OutputConfig(output_dir='trends/'))
analyzer.run()
```

---

## 13. Notas de diseño y advertencias generales

- **Convención de unidades en `HourlyEPWConverter`**: la velocidad de viento de entrada se asume en **km/h** (se divide entre 3.6) y la presión en **hPa** (se multiplica por 100). Si el fichero fuente ya viene en m/s o Pa, hay que pre-convertir antes de usar el conversor, o el resultado será incorrecto silenciosamente.
- **`TMYGenerator` no convierte unidades**: preserva los valores tal cual del fichero fuente durante todo el proceso estadístico; la conversión a unidades EPW ocurre solo en `HourlyEPWConverter`, lo que permite encadenar `TMYGenerator.export_tmy()` → `HourlyEPWConverter` sin pérdida ni doble conversión.
- **Compatibilidad de nombres de columna**: si los `col_*` usados en `TMYGenerator` coinciden con los `col_*` por defecto de `HourlyEPWConverter`, `export_tmy()` restaura automáticamente esos nombres y el CSV resultante es directamente compatible con `HourlyEPWConverter` sin `column_mapping` adicional.
- **`cdf_method='hourly'` es computacionalmente costoso** comparado con `'daily'`; para datasets largos (>10 años horarios) se recomienda `cdf_method='daily'` combinado con `hourly_file_path` para no perder la resolución horaria en el ensamblado/suavizado final.
- **`data_frequency='daily'` es incompatible con `cdf_method='hourly'`** (no hay datos horarios que analizar).
- **Persistencia de sesión activada por defecto** (`save_session=True`) en casi toda la API pública: genera automáticamente ficheros `.pkl`/`.json` junto a los datos de entrada — tenerlo en cuenta en flujos de CI/tests para no ensuciar directorios de trabajo (se puede desactivar con `save_session=False`).
- **`besos`/`eppy` son necesarios solo para `degree_hours.extract_setpoints_from_idf()`** (lectura de consignas desde IDF) — el resto del paquete funciona sin ellos.
- El huso horario en `convert_met_to_epw` se aproxima como `round(longitud/15)` (huso solar nominal), que puede diferir del huso civil real de algunos países (p. ej. España usa CET/CEST pese a estar geográficamente más próxima a UTC+0).

---

## 14. Referencias bibliográficas

- Hall, I.J., Prairie, R.R., Anderson, H.E., Boes, E.C. (1978). *Generation of Typical Meteorological Years for 26 SOLMET Stations*. Sandia Laboratories, SAND78-1601.
- Wilcox, S., Marion, W. (2008). *Users Manual for TMY3 Data Sets*. NREL/TP-581-43156, National Renewable Energy Laboratory.
- Finkelstein, J.M., Schafer, R.E. (1971). "Improved goodness-of-fit tests." *Biometrika*, 58(3), 641–645.
- Sawaqed, N.M., Zurigat, Y.H., Al-Hinai, H. (2005). "A step-by-step application of the Sandia method in developing a typical meteorological year for different climatic zones of Oman." *Energy Conversion and Management*, 46(4), 633–646.
- Roudsari, M.S., Pak, M. (2013). "Ladybug: a parametric environmental plugin for Grasshopper to help designers create an environmentally-conscious design." *Proceedings of BS2013*.
- Documentación oficial del formato **EPW** (EnergyPlus Weather File) — *Auxiliary Programs / Weather Converter Program*, U.S. Department of Energy.
- Código Técnico de la Edificación (CTE), Documento Básico HE — ficheros climáticos de referencia `.met` (LIDER/CALENER), Ministerio de Transportes, Movilidad y Agenda Urbana (España).
- Ineichen, P., Perez, R. (2002). "A new airmass independent formulation for the Linke turbidity coefficient." *Solar Energy*, 73(3), 151–157. *(modelo de cielo despejado subyacente en `pvlib.location.Location.get_clearsky`, usado por `ClimateProcessor`)*
- Perkins, S.E., Alexander, L.V. (2013). "On the measurement of heat waves." *Journal of Climate*, 26(13), 4500–4517. *(fundamento conceptual de la detección de olas de calor por percentil local, implementada en `EpwTrendAnalyzer`)*

---

## 15. Licencia

MIT

