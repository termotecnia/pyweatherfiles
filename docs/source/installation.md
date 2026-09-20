# Installation

## From PyPI (once published)

```bash
pip install pyweatherfiles
```

## From the repository (development install)

```bash
git clone https://github.com/termotecnia/pyweatherfiles.git
cd pyweatherfiles
pip install -e .
```

## Dependencies

Mandatory dependencies (declared in `pyproject.toml`):

```text
pandas, numpy, scipy, matplotlib, seaborn, openpyxl, ladybug-core, pyyaml
```

Optional dependencies, required only by specific modules:

| Dependency | Needed by | Install with |
|---|---|---|
| `pvlib` | `climate_processor.ClimateProcessor` | `pip install pvlib` |
| `tabulate` | `epw_comparator.compare_epw_files` | `pip install tabulate` |
| `besos` + `eppy` | `degree_hours.DegreeHoursCalculator.extract_setpoints_from_idf` (IDF setpoint extraction) | `pip install besos eppy` |
| `accim` | `degree_hours` (optional accent-sanitization of IDF paths) | `pip install accim` |

## Building this documentation locally

Install the `docs` extra (Sphinx, MyST-Parser for Markdown support, and the
Furo theme). The ``dist_build_docs.bat`` helper will also install this extra
automatically if it detects that the documentation dependencies are missing:

```bash
pip install -e ".[docs]"
```

Then, from the repository root, run the helper script:

```bat
dist_build_docs.bat
```

or run the equivalent commands manually:

```bash
python -m sphinx.ext.apidoc --force -o docs/source/api pyweatherfiles
cd docs
make.bat clean && make.bat html     REM Windows
# make clean && make html           # Linux/Mac
```

```{note}
Always `clean` before rebuilding manually: Sphinx's incremental build only
checks the mtime of each page's own source file, so it does **not** detect
changes to `README.md`/`README_ES.md`/`ARTICLE_CONTEXT_SEVILLA.md` when they
are pulled in via `` {include} `` (used by `full_reference_en`,
`full_reference_es` and `article_context`) — a stale `docs/build/` can
silently keep showing outdated content otherwise. `dist_build_docs.bat`
already does this for you.
```

The generated site is written to `docs/build/html/index.html`.

