# pyweatherfiles

**`pyweatherfiles`** is a Python toolkit for weather-file management aimed at
building energy simulation: **Typical Meteorological Year (TMY)** generation
(Sandia/TMY3 methodology), bidirectional format conversion (EPW ↔ `.met` ↔
hourly CSV/Excel series), **heating/cooling degree-hours** calculation,
multi-year **climate trend analysis**, EPW file comparison, and gap-filling of
raw hourly series.

This site is generated with [Sphinx](https://www.sphinx-doc.org/) and hosts:

- A **complete technical reference** of every module, class, method and
  formula (in English and Spanish) — reused directly from the repository's
  `README.md` / `README_ES.md` so there is a single source of truth.
- The **API reference**, auto-generated from the docstrings in the source
  code (`sphinx-apidoc` + `autodoc`).
- A step-by-step **Jupyter Notebook tutorial** (Seville and Madrid, real
  data) that covers TMY generation, EPW conversion and
  degree-hours/climate-trend analysis end to end, with its own
  version-controlled input data so it can be executed standalone.

```{tip}
New to the package? Start with {doc}`installation` and {doc}`quickstart`,
then work through the
{doc}`tutorial notebook <jupyter_notebooks/tutorial_pyweatherfiles_case_study>`.
```

## Module map

| Module (`pyweatherfiles.*`) | Main classes / functions | Purpose |
|---|---|---|
| `tmy` | `TMYGenerator` | Generates a TMY from historical series, Sandia/TMY3 method in 7 steps |
| `hourly_epw_converter` | `HourlyEPWConverter`, `BatchHourlyEPWConverter` | Converts clean hourly series (CSV/Excel) into `.epw` files |
| `met_epw_converter` | `convert_met_to_epw`, `convert_epw_to_met` | Bidirectional conversion between `.met` (LIDER/CALENER-CTE) and `.epw` |
| `degree_hours` | `DegreeHoursCalculator`, `EpwBatchAnalyzer`, `EpwGroupTrendAnalyzer` | Heating/cooling degree-hours from an EPW + setpoints (IDF or dict); single-EPW, multi-EPW comparative, or whole-folder trend analysis classified by filename |
| `epw_trend_analyzer` | `EpwTrendAnalyzer`, `TrendConfig`, `OutputConfig` | Multi-year climate trends over collections of annual EPWs |
| `epw_comparator` | `compare_epw_files`, `create_comparison_hourly_dataframe`, ... | Structural/statistical/hourly comparison between two EPW files |
| `climate_processor` | `ClimateProcessor` | Cleaning, reindexing and gap-filling of raw hourly station series |
| `session_manager` | `save_object_session`, `save_function_session`, `load_session` | Reproducible `.pkl` + `.json` session persistence used across the package |

```{toctree}
:maxdepth: 2
:caption: Getting started

installation
quickstart
jupyter_notebooks/tutorial_pyweatherfiles_case_study
```

```{toctree}
:maxdepth: 2
:caption: Full reference

full_reference_en
full_reference_es
```

```{toctree}
:maxdepth: 2
:caption: API reference

api/modules
```

## Indices

- {ref}`genindex`
- {ref}`modindex`
- {ref}`search`

