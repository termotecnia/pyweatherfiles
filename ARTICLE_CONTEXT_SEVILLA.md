# pyweatherfiles — Contexto técnico del artículo (caso de estudio: Sevilla)

> **Nota:** Este documento es una copia dedicada, **exclusivamente para servir de contexto al artículo científico** (y para pegar en Claude u otro LLM como material de referencia). Describe **solo** el flujo de trabajo real usado en `generating epws seville.py`. Para la documentación general del paquete completo (todos los módulos, incluidos los no usados en este script), consulta el [`README.md`](README.md) del repositorio.

**`pyweatherfiles`** es un paquete de Python para la gestión de ficheros climáticos y la generación de **Años Meteorológicos Típicos (TMY)** a partir de series históricas horarias, con conversión bidireccional a los formatos usados por herramientas de simulación energética de edificios (EnergyPlus, DesignBuilder, etc.).

Este documento describe **al máximo nivel de detalle técnico** el flujo de trabajo realmente utilizado en un caso de estudio (generación del año climático de Sevilla), tal como aparece en `generating epws seville.py`. Está pensado para servir simultáneamente como:

1. **Documento fuente** para asistir en la redacción de un artículo científico (metodología, fórmulas, parámetros y referencias bibliográficas listas para citar).
2. Material de referencia técnica del caso de estudio de Sevilla.

> Autor del paquete: Daniel Sánchez-García (Universidad de Cádiz) — `daniel.sanchezgarcia@uca.es`

---

## Tabla de contenidos

1. [Visión general y flujo de datos](#1-visión-general-y-flujo-de-datos)
2. [Instalación y dependencias](#2-instalación-y-dependencias)
3. [Caso de estudio real: Sevilla](#3-caso-de-estudio-real-sevilla)
4. [Componente 1 — `HourlyEPWConverter`: series horarias → EPW](#4-componente-1--hourlyepwconverter-series-horarias--epw)
5. [Componente 2 — `convert_met_to_epw`: fichero de referencia `.met` → EPW](#5-componente-2--convert_met_to_epw-fichero-de-referencia-met--epw)
6. [Componente 3 — `TMYGenerator`: generación del TMY (metodología Sandia/TMY3)](#6-componente-3--tmygenerator-generación-del-tmy-metodología-sandiatmy3)
7. [Componente 4 — TMY → EPW final](#7-componente-4--tmy--epw-final)
8. [Persistencia de sesión y reproducibilidad](#8-persistencia-de-sesión-y-reproducibilidad)
9. [Pipeline completo anotado (equivalente al script del artículo)](#9-pipeline-completo-anotado-equivalente-al-script-del-artículo)
10. [Validación posterior (breve nota)](#10-validación-posterior-breve-nota)
11. [Otras utilidades del paquete (fuera de este flujo)](#11-otras-utilidades-del-paquete-fuera-de-este-flujo)
12. [Referencias bibliográficas](#12-referencias-bibliográficas)
13. [Notas de uso de este documento para el artículo](#13-notas-de-uso-de-este-documento-para-el-artículo)
14. [Licencia](#14-licencia)

---

## 1. Visión general y flujo de datos

El caso de uso real documentado aquí encadena **cuatro etapas**, todas ejecutadas sobre el mismo dataset horario multianual de origen (`Sevilla_Definitivo_para_convertir_a_epw.xlsx`):

```
                         ┌───────────────────────────────────────────┐
                         │  Sevilla_Definitivo_para_convertir_a_epw   │
                         │           .xlsx  (serie horaria           │
                         │         multianual, ya depurada)           │
                         └───────────────┬─────────────────────────────┘
                                         │
        ┌────────────────────────────────┼─────────────────────────────┐
        │                                │                              │
        ▼                                ▼                              │
┌───────────────────┐         ┌─────────────────────────┐               │
│ (1) HourlyEPW      │         │ (3) TMYGenerator         │               │
│     Converter       │         │  cdf_method='daily'      │               │
│  .process(          │         │  hourly_file_path=       │◄──────────────┘
│   'seville_{year}   │         │     (mismo Excel)        │
│    .epw')           │         │  .generate_tmy(...)      │
│                     │         │  .export_tmy(            │
│  → seville_2005.epw │         │     'seville_tmy_3.csv') │
│    ... seville_2025 │         └────────────┬──────────────┘
│    .epw (uno/año)   │                      │
└───────────────────┘                      ▼
                                  ┌─────────────────────────┐
┌───────────────────┐             │ (4) HourlyEPWConverter   │
│ (2) convert_met_    │             │   .process(              │
│      to_epw         │             │   'seville_tmy.epw')     │
│  sevilla_SP.met      │             │                          │
│  → seville_met.epw  │             │  → seville_tmy.epw       │
└───────────────────┘             └─────────────────────────┘
```

- **(1)** convierte la serie horaria multianual completa en **un EPW por año** (línea base "long-term").
- **(2)** convierte el fichero climático de referencia oficial español (`.met`, formato LIDER/CALENER-CTE) a EPW (línea base "normativa/de referencia").
- **(3)** ejecuta el algoritmo completo de generación de TMY (metodología Sandia, 7 pasos) sobre la misma serie horaria y exporta el año típico resultante a CSV, **conservando los nombres de columna originales del Excel**.
- **(4)** reutiliza el mismo conversor de (1) para transformar ese CSV del TMY en el EPW final, listo para simulación energética.

Las dos últimas secciones del script (`epw_comparator.create_comparison_hourly_dataframe` y las llamadas a `besos`/EnergyPlus) se emplean solo como **comprobación posterior** (ver [§10](#10-validación-posterior-breve-nota)) y no forman parte del núcleo metodológico aquí detallado.

---

## 2. Instalación y dependencias

```bash
pip install pyweatherfiles
```

Dependencias declaradas en `pyproject.toml`:

| Paquete | Uso en este flujo |
|---|---|
| `pandas`, `numpy` | Carga, resampleo, estadística, series temporales |
| `scipy` | `UnivariateSpline` / `CubicSpline` para el suavizado de las uniones mensuales del TMY |
| `matplotlib`, `seaborn` | Visualización y diagnóstico (no usadas en el flujo mínimo aquí descrito) |
| `openpyxl` | Lectura/escritura de `.xlsx` |
| `ladybug-core` | Lectura/escritura de ficheros **EPW**, cálculo de posición solar (`Sunpath`) |
| `pyyaml` | Utilidades internas |

Dependencia adicional usada en la etapa de **validación** (no en la generación en sí): `besos` + `eppy` (wrapper de EnergyPlus).

---

## 3. Caso de estudio real: Sevilla

Fichero de origen: **`Sevilla_Definitivo_para_convertir_a_epw.xlsx`** — serie horaria multianual ya depurada/rellenada, con cabeceras en inglés (algunas con espacio final, p. ej. `'Global Horizontal Irradiance '`):

| Columna en el Excel | Variable interna | Nota |
|---|---|---|
| `time` | `time` (índice datetime) | |
| `Dry-bulb temperature` | `T_air` | Temperatura de bulbo seco (°C) |
| `Dew Point temperature` | `T_dew` | Temperatura de rocío (°C) |
| `Wind Speed` | `Wind_speed` | **Se asume km/h** (ver §4) |
| `Global Horizontal Irradiance ` | `GHI` | Irradiancia global horizontal (Wh/m²) |
| `Beam Normal Irradiance ` | `DNI` | Irradiancia directa normal (Wh/m²) |

Fichero plantilla EPW: **`ESP_Sevilla.083910_IWEC.epw`** (dataset IWEC — *International Weather for Energy Calculations*, ASHRAE), usado únicamente como plantilla para extraer/definir cabecera geográfica (latitud, longitud, elevación, huso horario) y estructura EPW válida.

Fichero de referencia normativa: **`sevilla_SP.met`** — fichero climático de referencia en formato `.met` (tipo LIDER/CALENER, usado en el Código Técnico de la Edificación español, CTE DB-HE).

> **Detalle clave de diseño:** los nombres de columna por defecto de `HourlyEPWConverter` (`col_temp='Dry-bulb temperature'`, `col_dew='Dew Point temperature'`, `col_wind='Wind Speed'`, `col_ghi='Global Horizontal Irradiance '`, `col_dni='Beam Normal Irradiance '`) **coinciden exactamente** con las cabeceras originales del Excel de Sevilla. Por eso, ni la conversión (1) ni la conversión (4) necesitan pasar `column_mapping`: en el paso (4), `TMYGenerator.export_tmy()` **restaura automáticamente** esos mismos nombres originales antes de escribir el CSV (ver §6.8), cerrando el ciclo sin necesidad de remapeos manuales.

---

## 4. Componente 1 — `HourlyEPWConverter`: series horarias → EPW

```python
from pyweatherfiles import hourly_epw_converter

converter_longterm = hourly_epw_converter.HourlyEPWConverter(
    file_path='Sevilla_Definitivo_para_convertir_a_epw.xlsx',
    base_epw_path='ESP_Sevilla.083910_IWEC.epw',
)
converter_longterm.process(output_pattern='seville_{year}.epw')
```

### 4.1 Constructor

Parámetros relevantes:

- `file_path`, `base_epw_path` (obligatorios).
- `lat, lon, elev, tz_hour` (opcionales): si no se indican, se **extraen automáticamente** del EPW plantilla vía `ladybug.epw.EPW(base_epw_path).location`.
- Mapeo de columnas configurable (`datetime_col`, `col_temp`, `col_dew`, `col_wind`, `col_ghi`, `col_dni`, `col_rh`, `col_pres`, `col_wind_dir`, `col_dhi`, `col_cloud_cover`, `col_irh`, o un `column_mapping` dict global).
- `preserve_extra` (bool): si `True`, no anula el campo `total_sky_cover` cuando hay columna de nubosidad disponible.
- `remove_leap_day` (bool, por defecto `True`): elimina el 29 de febrero para mantener el estándar EnergyPlus de 8760 h/año.

### 4.2 Carga de datos (`_load_file`)

- Lee `.xlsx` o `.csv`, parsea el índice temporal, **ordena cronológicamente**.
- **Conversión de unidades automática (convención fija del paquete):**
  - Velocidad de viento: `Wind_speed = Wind_speed_input / 3.6` → **se asume la entrada en km/h** y se convierte a m/s.
  - Presión: `Pressure = Pressure_input * 100.0` → **se asume la entrada en hPa** y se convierte a Pa.
- Registra los años disponibles (`available_years`).

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

- Genera **un EPW por año** disponible (o por una lista concreta de años), nombrando cada fichero según `output_pattern` (p. ej. `'seville_{year}.epw'` → `seville_2005.epw`, `seville_2006.epw`, …) o, por defecto, `'{basename}_{year}.epw'`.
- Al finalizar, si `save_session=True` (por defecto), guarda automáticamente una **sesión reproducible** (`.pkl` + `.json`) — ver [§8](#8-persistencia-de-sesión-y-reproducibilidad).

> El paquete incluye también `BatchHourlyEPWConverter`, una clase de orquestación multi-ciudad (no usada en este flujo de Sevilla) con un método `suggest_config()` capaz de emparejar automáticamente ficheros de datos y plantillas EPW por nombre de ciudad, extrayendo su geolocalización.

---

## 5. Componente 2 — `convert_met_to_epw`: fichero de referencia `.met` → EPW

```python
from pyweatherfiles import met_epw_converter

met_epw_converter.convert_met_to_epw(
    met_path='sevilla_SP.met',
    base_epw_path='ESP_Sevilla.083910_IWEC.epw',
    epw_path='seville_met.epw',
    replace_unused_with_missing=True
)
```

### 5.1 El formato `.met`

Fichero de texto plano con:
- **Línea de metadatos** con latitud, longitud y elevación (localizada automáticamente si no está en la posición esperada, buscando en las primeras 10 líneas un valor de latitud plausible `[-90, 90]`).
- **Bloque de datos** de 13 columnas (`Month, Day, Hour, DryBulb, SkyTemp, RadDirectaHoriz, RadDifusaHoriz, AbsHum, RelHum, WindSpeed, WindDir, Azimuth, Zenith`) o variante de 15 columnas (sin `WindDir`, con 2 columnas auxiliares no usadas).
- El huso horario se aproxima como `tz_hour = round(longitud / 15.0)` (huso solar nominal, no necesariamente el huso civil/político real — relevante a documentar como posible limitación menor si se discute en el artículo).

### 5.2 Fórmulas de conversión

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
- **Cierre de balance de radiación**: `residual = GHI − (DHI + DNI·cos_zenith)`, reportando la media y el percentil 95 del valor absoluto — una comprobación de consistencia física del triplete GHI/DNI/DHI reconstruido.

### 5.3 Resto del proceso

- Fuerza un `AnalysisPeriod` estándar no bisiesto de 8760 h.
- Aplica la misma corrección de desfase *point-in-time* que en `HourlyEPWConverter` (§4.4, punto 4).
- Si `replace_unused_with_missing=True`, neutraliza los mismos 15 campos EPW no usados con sus códigos oficiales de valor ausente (idéntico a §4.4, punto 5).
- Guarda sesión reproducible vía `save_function_session` (API de función, no de clase) si `save_session=True` (por defecto).

> El módulo incluye también la conversión inversa `convert_epw_to_met()` (EPW → `.met`), no utilizada en este flujo, útil para producir ficheros de referencia `.met` a partir de un EPW existente.

---

## 6. Componente 3 — `TMYGenerator`: generación del TMY (metodología Sandia/TMY3)

```python
from pyweatherfiles import tmy

converter_tmy = tmy.TMYGenerator(
    file_path='Sevilla_Definitivo_para_convertir_a_epw.xlsx',
    cdf_method='daily',
    data_frequency='hourly',
    weighting_method='sandia',
    save_validation_dfs=True,
    hourly_file_path='Sevilla_Definitivo_para_convertir_a_epw.xlsx',
    datetime_col='time',
    col_temp='Dry-bulb temperature',
    col_dew='Dew Point temperature',
    col_wind='Wind Speed',
    col_ghi='Global Horizontal Irradiance ',
    col_dni='Beam Normal Irradiance '
)

converter_tmy.generate_tmy(use_persistence=True)
converter_tmy.export_tmy('seville_tmy_3.csv')
```

Este es el **núcleo metodológico** del paquete: una implementación del método **Sandia** de generación de TMY (Hall et al., 1978), compatible además con el esquema de ponderación **TMY3** de NREL (Wilcox & Marion, 2008), estructurada en **7 pasos** (`sandia_step_1` … `sandia_step_7`), orquestados por `generate_tmy()`.

### 6.1 Detalle de la llamada en el caso de Sevilla

- `cdf_method='daily'`: la selección de meses candidatos (pasos 2-5) se calcula sobre **agregados diarios** (más rápido que `'hourly'`).
- `hourly_file_path=` el mismo Excel: aunque la selección estadística usa agregados diarios, **se mantiene disponible la resolución horaria completa** para el ensamblado final (paso 6) y el suavizado de uniones mensuales (paso 7). Solo se conservan del fichero horario los meses que también existen en el fichero diario.
- `weighting_method='sandia'`: usa la tabla de pesos Sandia (no TMY3).
- `use_persistence=True` en `generate_tmy()`: activa el filtrado de persistencia (pasos 4-5) con su método por defecto, `persistence_method='sequential'`.

### 6.2 Paso 1 — Carga y preparación (`sandia_step_1_load_and_prepare`)

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

### 6.3 Paso 2 — Selección de candidatos por el estadístico Finkelstein-Schafer (`sandia_step_2_select_candidates_fs`)

Para cada mes calendario (1-12) y cada año disponible, se compara la **función de distribución acumulada (CDF) empírica** de ese mes/año candidato frente a la CDF de largo plazo (todos los años) del mismo mes calendario.

**Posiciones de graficado (plotting position) para la CDF empírica** (`plotting_position_method`, por defecto `'hazen'`):

```
hazen:     CDF(i) = (i − 0.5) / n
weibull:   CDF(i) = i / (n + 1)
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
Total_W_FS = Σ_i  peso_i · FS_i        (suma sobre todas las variables ponderadas, tabla de §6.2)
```

**Filtro de completitud de datos** (`missing_data_threshold`, por defecto 0.9): un mes-año candidato se **excluye** si `puntos_válidos / puntos_esperados < 0.9` (siendo `puntos_esperados = días_del_mes × 24` en horario o `días_del_mes` en diario). Los meses excluidos se registran (`excluded_months`) y se informan por consola.

Para cada mes se retienen los **5 años con menor `Total_W_FS`** como candidatos iniciales (`candidate_months_pre_proximity`).

### 6.4 Paso 3 — *Proximity Ranking* (`sandia_step_3_proximity_ranking`)

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

### 6.5 Pasos 4-5 — Filtrado de persistencia y selección final del mes

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

### 6.6 Paso 6 — Ensamblado del TMY bruto (`sandia_step_6_assemble_tmy`)

Para cada uno de los 12 meses, se extrae el mes completo (con resolución horaria si `df_hourly` está disponible; si no, diaria) del **año seleccionado**, se re-etiqueta al año sintético 2000, se elimina el 29 de febrero si el año de origen era bisiesto, y se concatenan los 12 meses en `tmy_raw`.

### 6.7 Paso 7 — Suavizado de las uniones mensuales (`sandia_step_7_smooth_junctions`)

- **Requiere datos horarios** (`df_hourly` o `hourly_file_path`); si no están disponibles, se omite el suavizado (el TMY final = TMY bruto) con un aviso.
- Para cada una de las **11 uniones** entre meses consecutivos:
  1. Se ajusta un **spline de suavizado** (`scipy.interpolate.UnivariateSpline`, parámetro `s_factor`, por defecto `0.0` → interpolación exacta) usando los **dos meses completos** de datos horarios de sus respectivos años de origen.
  2. Se evalúa el spline sobre una **ventana configurable** alrededor de la unión (`hours` antes/después, por defecto 6 h; configurable de forma independiente por unión y por lado mediante el diccionario `smoothing_config`).
  3. Se reemplazan los valores brutos en esa ventana por los suavizados, **para todas las variables excepto `GHI` y `DNI`** (la radiación se deja intacta para no distorsionar la geometría solar).
- **Recorte de seguridad final:** valores negativos residuales (undershoot) en `GHI`, `DNI` o `Wind_speed` se recortan a 0.
- Genera automáticamente la tabla de validación `validation_step6_tmy_composition` (fusión de estadísticas FS + proximidad + persistencia por mes seleccionado) y llama a `generate_full_summary()`.
- **Guarda sesión reproducible automáticamente** (`.pkl` + `.json`) si `save_session=True` (por defecto) — ver [§8](#8-persistencia-de-sesión-y-reproducibilidad).

### 6.8 Exportación (`export_tmy`)

```python
converter_tmy.export_tmy('seville_tmy_3.csv')
```

- Soporta `.csv` / `.tmy` / `.xlsx`.
- Recorte de seguridad final de negativos en `GHI`/`DNI`/`Wind_speed`.
- **Añade columnas auxiliares**: cualquier variable presente en `df_hourly` pero ausente en `tmy_final` (p. ej. columnas extra del Excel no usadas en la ponderación) se ensambla igual que el TMY (mismos meses/años seleccionados) y se anexa.
- **Restaura los nombres de columna originales del fichero fuente** (inversos de `col_temp`, `col_dew`, `col_wind`, `col_ghi`, `col_dni`, `datetime_col`) antes de escribir — por eso el CSV resultante (`seville_tmy_3.csv`) usa exactamente las cabeceras `'Dry-bulb temperature'`, `'Dew Point temperature'`, `'Wind Speed'`, `'Global Horizontal Irradiance '`, `'Beam Normal Irradiance '`, idénticas al Excel original y a los valores por defecto de `HourlyEPWConverter` (§4, §7).

> **Nota de unidades:** `TMYGenerator` es **agnóstico a la unidad** de cada variable durante todo el proceso estadístico (no convierte km/h ni hPa); simplemente preserva los valores tal como llegaron del fichero fuente. La conversión a unidades SI/EPW (m/s, Pa) ocurre exclusivamente en `HourlyEPWConverter`, en el paso siguiente. Esta separación de responsabilidades (motor estadístico ↔ capa de exportación EPW) es una decisión de arquitectura relevante para la reproducibilidad del método.

---

## 7. Componente 4 — TMY → EPW final

```python
converter_tmy_to_epw = hourly_epw_converter.HourlyEPWConverter(
    file_path='seville_tmy_3.csv',
    base_epw_path='ESP_Sevilla.083910_IWEC.epw',
)
converter_tmy_to_epw.process(output_pattern='seville_tmy.epw')
```

Se reutiliza **exactamente el mismo `HourlyEPWConverter`** descrito en §4, ahora sobre el CSV del TMY recién exportado. Como éste conserva las cabeceras originales (§6.8) — que coinciden con los valores por defecto del conversor —, no se necesita ningún `column_mapping` adicional. El resultado, `seville_tmy.epw`, es un fichero EPW de un único año sintético (2000), listo para simulación energética (EnergyPlus/DesignBuilder/etc.), construido a partir del año típico generado.

---

## 8. Persistencia de sesión y reproducibilidad

Todas las clases/funciones principales del flujo (`TMYGenerator.sandia_step_7_smooth_junctions`, `HourlyEPWConverter.process`, `BatchHourlyEPWConverter.process_all`, `convert_met_to_epw`) guardan automáticamente (`save_session=True` por defecto) una **sesión reproducible** mediante `pyweatherfiles.session_manager`:

- **`.pkl`**: el objeto completo serializado (con *fallback* parcial: si algún atributo no es serializable, se sustituye por un marcador de texto y se conserva el resto).
- **`.json`**: una instantánea legible por humanos — timestamp, versión del paquete, y todos los atributos públicos (incluidas las tablas `validation_step*`) convertidos a forma segura para JSON (los `DataFrame`/`Series`/`ndarray` se resumen con forma, columnas y tipos; las listas largas se truncan a los primeros 10 elementos).

**Nomenclatura de fichero** (determinista, para evitar colisiones y facilitar la trazabilidad):

```
{Prefijo}_{slug_input_1}_{slug_input_2}_{slug_input_3}_{hash_md5_8_caracteres}.pkl / .json
```

Por ejemplo, para el `TMYGenerator` de Sevilla, se generaría algo como `TMYGenerator_Sevilla_Definitivo_pa_daily_sandia_<hash8>.pkl/.json` en el mismo directorio que el fichero de entrada (o en `session_dir` si se especifica).

Recuperación: `pyweatherfiles.session_manager.load_session(pkl_path)`.

Esto permite **auditar y reproducir exactamente** cada ejecución del pipeline (parámetros de entrada + resultado completo), algo especialmente valioso para la sección de metodología/reproducibilidad de un artículo científico.

---

## 9. Pipeline completo anotado (equivalente al script del artículo)

```python
from pyweatherfiles import hourly_epw_converter, met_epw_converter, tmy

# (1) Serie horaria multianual → un EPW "long-term" por año disponible
converter_longterm = hourly_epw_converter.HourlyEPWConverter(
    file_path='Sevilla_Definitivo_para_convertir_a_epw.xlsx',
    base_epw_path='ESP_Sevilla.083910_IWEC.epw',
)
converter_longterm.process(output_pattern='seville_{year}.epw')

# (2) Fichero de referencia normativo (.met, tipo LIDER/CALENER-CTE) → EPW
met_epw_converter.convert_met_to_epw(
    met_path='sevilla_SP.met',
    base_epw_path='ESP_Sevilla.083910_IWEC.epw',
    epw_path='seville_met.epw',
    replace_unused_with_missing=True
)

# (3) Generación del TMY (Sandia, 7 pasos) sobre la misma serie horaria
converter_tmy = tmy.TMYGenerator(
    file_path='Sevilla_Definitivo_para_convertir_a_epw.xlsx',
    cdf_method='daily',                 # selección de candidatos sobre agregados diarios
    data_frequency='hourly',            # el fichero fuente es horario
    weighting_method='sandia',
    save_validation_dfs=True,
    hourly_file_path='Sevilla_Definitivo_para_convertir_a_epw.xlsx',  # habilita ensamblado/suavizado horario
    datetime_col='time',
    col_temp='Dry-bulb temperature',
    col_dew='Dew Point temperature',
    col_wind='Wind Speed',
    col_ghi='Global Horizontal Irradiance ',
    col_dni='Beam Normal Irradiance '
)
converter_tmy.generate_tmy(use_persistence=True)   # Pasos 1→7, persistencia 'sequential' por defecto
converter_tmy.export_tmy('seville_tmy_3.csv')      # cabeceras originales restauradas

# (4) CSV del TMY → EPW final listo para simulación
converter_tmy_to_epw = hourly_epw_converter.HourlyEPWConverter(
    file_path='seville_tmy_3.csv',
    base_epw_path='ESP_Sevilla.083910_IWEC.epw',
)
converter_tmy_to_epw.process(output_pattern='seville_tmy.epw')
```

---

## 10. Validación posterior (breve nota)

Tras generar `seville_tmy.epw`, el script del artículo realiza dos comprobaciones adicionales (fuera del alcance metodológico detallado aquí):

1. **Comparación horaria EPW vs. EPW** con `pyweatherfiles.epw_comparator.create_comparison_hourly_dataframe(base_epw_path, generated_epw_path)`, contrastando el TMY generado frente a un año concreto de la serie *long-term* (p. ej. `seville_2018.epw`).
2. **Simulación energética** del TMY resultante en modelos de edificio de referencia (`SF_Detached_B_min_South.idf`, `SF_Detached_D_min_South.idf`) vía `besos.eplus_funcs.run_energyplus`, para evaluar su efecto sobre la demanda energética simulada frente a los años reales y al fichero de referencia normativo (`_met`).

---

## 11. Otras utilidades del paquete (fuera de este flujo)

No usadas en el caso de Sevilla descrito, pero disponibles en el paquete:

- **`DegreeHoursCalculator` / `EpwBatchAnalyzer`** (`degree_hours.py`): cálculo de grados-hora de calefacción/refrigeración a partir de EPW, individual o comparativo multi-EPW.
- **`EpwTrendAnalyzer`, `TrendConfig`, `OutputConfig`** (`epw_trend_analyzer.py`): análisis de tendencias climáticas multianuales.
- **`climate_processor.py`**: utilidades basadas en `pvlib`.
- **`epw_comparator.py`**: comparación tabular/estadística entre EPWs (usa `tabulate`).
- Métodos avanzados de `TMYGenerator` no usados en este flujo pero disponibles para análisis y diagnóstico: `plot_cdfs`, `plot_fs_details`, `plot_junctions`, `plot_smoothing_comparison`, `plot_persistence_runs`, `plot_annual_cdfs`, `plot_monthly_means`, `plot_monthly_cdfs`, `get_candidate_stats`, `analyze_selection`, `correct_selection_by_temperature`, `plot_monthly_trend`, `plot_monthly_series`, `compare_tmy_versions`.

> Para el detalle completo de estos módulos (no usados en el caso de Sevilla), consulta el [`README.md`](README.md) general del paquete.

---

## 12. Referencias bibliográficas

Referencias directamente asociadas a la metodología implementada, útiles para la sección de metodología del artículo:

- Hall, I.J., Prairie, R.R., Anderson, H.E., Boes, E.C. (1978). *Generation of Typical Meteorological Years for 26 SOLMET Stations*. Sandia Laboratories, SAND78-1601.
- Wilcox, S., Marion, W. (2008). *Users Manual for TMY3 Data Sets*. NREL/TP-581-43156, National Renewable Energy Laboratory.
- Finkelstein, J.M., Schafer, R.E. (1971). "Improved goodness-of-fit tests." *Biometrika*, 58(3), 641–645.
- Sawaqed, N.M., Zurigat, Y.H., Al-Hinai, H. (2005). "A step-by-step application of the Sandia method in developing a typical meteorological year for different climatic zones of Oman." *Energy Conversion and Management*, 46(4), 633–646.
- Roudsari, M.S., Pak, M. (2013). "Ladybug: a parametric environmental plugin for Grasshopper to help designers create an environmentally-conscious design." *Proceedings of BS2013*.
- Documentación oficial del formato **EPW** (EnergyPlus Weather File) — *Auxiliary Programs / Weather Converter Program*, U.S. Department of Energy.
- Código Técnico de la Edificación (CTE), Documento Básico HE — ficheros climáticos de referencia `.met` (LIDER/CALENER), Ministerio de Transportes, Movilidad y Agenda Urbana (España).

---

## 13. Notas de uso de este documento para el artículo

Sugerencia de correspondencia entre secciones de este informe y apartados típicos de un artículo científico:

| Sección de este documento | Apartado sugerido del artículo |
|---|---|
| §3 (caso de estudio) | *Study area / Data* |
| §4, §5 (conversores EPW/MET) | *Data preparation* |
| §6 (metodología Sandia completa) | *Methods* (con las fórmulas de §6.3-§6.5 citables tal cual) |
| §6.7 (suavizado) | *Post-processing* |
| §8 (sesiones) | *Reproducibility / Data availability* |
| §10 (validación) | *Validation / Results* |
| §12 (referencias) | *Bibliografía* directamente reutilizable |

Al pegar este documento en Claude (o en cualquier LLM), puedes pedir directamente cosas como: *"redacta el apartado de Métodos del artículo a partir de las secciones 6.1 a 6.8"*, o *"genera una tabla comparativa de los pesos Sandia vs. TMY3 en formato LaTeX a partir de la tabla de la sección 6.2"*.

---

## 14. Licencia

MIT

