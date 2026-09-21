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

Install every optional runtime extra at once with:

```bash
pip install "pyweatherfiles[full]"
```

## Verify the installation

```python
import pyweatherfiles

print(pyweatherfiles.__version__)
print(pyweatherfiles.TMYGenerator)
```

Next: head to {doc}`quickstart` for the shortest end-to-end example, or to the
{doc}`tutorial notebook <jupyter_notebooks/tutorial_pyweatherfiles_case_study>`
for the complete workflow with real data.

