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
Furo theme):

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
make.bat html     REM Windows
# make html       # Linux/Mac
```

The generated site is written to `docs/build/html/index.html`.

