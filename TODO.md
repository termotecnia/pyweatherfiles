# TODO.md

Document for tracking pending tasks for the `pyweatherfiles` project. Mark with `[x]` once a task is completed, and move relevant details to `README.md`/`README_ES.md` if appropriate.

>  Versión en español: [`TODO_ES.md`](TODO_ES.md).

---

## Pending tasks

### 1. [ ] Integrate the climate data acquisition module (pending delivery)

- **Status:** blocked — waiting to receive the external module/code.
- **Context:** the repo already has `pyweatherfiles/climate_processor.py` with an optional dependency on `pvlib`. Once received, we'll need to decide whether the new module replaces it, complements it, or lives as a new file (e.g. `pyweatherfiles/climate_data_fetcher.py`).
- **Planned steps once the module arrives:**
  - [ ] Review the received code (data source, output format, dependencies).
  - [ ] Decide its final location within the package and its relationship to `climate_processor.py`.
  - [ ] Adapt it to the repo's conventions: explicit column mappings (`datetime_col`, `col_temp`, etc.), use of `session_manager` for persistence if applicable, console diagnostics if consistent with the rest of the package.
  - [ ] Add/update dependencies in `pyproject.toml` (handling `ImportError` at runtime if it's an optional dependency, as is done with `pvlib`, `tabulate`, `besos`, `eppy`).
  - [ ] Expose it in `pyweatherfiles/__init__.py` only if it should be part of the minimal public API.
  - [ ] Add a usage example in `examples/`.
  - [ ] Document the data flow (input/output) in the documentation from task 3.

### 2. [ ] Publish `pyweatherfiles` on PyPI once everything is ready

- **Status:** pending — conditional on closing tasks 1 and 3 (or at least clarifying what is left out of the first release).
- **Context:** the scripts `dist_build_package.bat`, `dist_upload_test.bat`, and `dist_upload.bat` already exist.
- **Planned steps:**
  - [x] Review `pyproject.toml` dependency list: `ladybug-core` is already a mandatory dependency, and `pvlib`/`tabulate`/`besos`/`eppy`/`accim` are now declared as optional extras (`climate`, `comparator`, `energyplus`, `accents`, plus a combined `full`), with their imports guarded by `try/except ImportError` in `climate_processor.py`/`epw_comparator.py` (they already were in `degree_hours.py`). See `INFORME_REVISION_GENERAL.md` §6 Fase 0.3.
  - [x] Still pending on `pyproject.toml` — now also done: added a physical `LICENSE` file at the repo root (MIT, matches the `license = "MIT"` metadata), bumped `requires-python` from the stale `>=3.7` (EOL, incompatible with current pandas/numpy) to `>=3.10`, and added Python-version `classifiers` (3.10-3.13). Version number is still `0.0.0` — bump it as part of the actual release step below.
  - [x] `dist_build_package.bat`'s `python -m build` step is now also exercised automatically on every push/PR via `.github/workflows/ci.yml` (Fase 3), so packaging breakage should surface before this manual step.
  - [ ] Run `dist_build_package.bat` (cleans `dist/`, `build/`, `*.egg-info` and runs `python -m build`).
  - [ ] Publish to TestPyPI with `dist_upload_test.bat` and validate installation in a clean virtual environment (`pip install -i https://test.pypi.org/simple/ pyweatherfiles`).
  - [ ] Test the examples in `examples/` against the package installed from TestPyPI (not from the local repo).
  - [ ] Publish to PyPI with `dist_upload.bat` (requires `.pypirc`).
  - [ ] Create the version tag in git and, if applicable, release notes.

### 3. [x] Write the software documentation, including a tutorial in `.ipynb`

- **Status:** done (except the item conditional on task 1, still blocked).
- **Context:** `dist_build_docs.bat` already assumed Sphinx (`sphinx-apidoc` + `make.bat html`); the `docs/` folder has been recreated to match it exactly.
- **What was done:**
  - [x] Chose **Sphinx** (+ `myst-nb` for Markdown pages *and* rendering the tutorial notebook, + the Read the Docs theme `sphinx-rtd-theme`), matching what `dist_build_docs.bat` already expected. Recreated `docs/source/conf.py`, `docs/Makefile`, `docs/make.bat`, and the page tree (`index.md`, `installation.md`, `quickstart.md`). Added a `docs` extra in `pyproject.toml` (`pip install -e ".[docs]"`). `docs/source/api/` is auto-regenerated on every build (`sphinx-apidoc`) but is committed anyway as a GitHub backup; only `docs/build/` (the final HTML) stays git-ignored.
  - [x] Documented the main public API: the existing exhaustive `README.md`/`README_ES.md` (all modules/classes/methods/formulas) is reused as the "full reference" pages in the Sphinx site (`full_reference_en.md` / `full_reference_es.md`), plus a real `autodoc`/`sphinx-apidoc` API reference generated from the actual docstrings (`autodoc_mock_imports` covers optional heavy deps `pvlib`/`tabulate`/`besos`/`eppy`/`accim` so the docs build without them). Fixed a few malformed docstrings (`tmy.py`, `degree_hours.py`, `epw_trend_analyzer.py`) that produced Sphinx/docutils warnings; the site now builds with **zero warnings**.
  - [x] TMY workflow conventions (column mapping, `data_frequency`/`cdf_method`, proximity normalization methods, deprecated `'sawaqed'` alias) were already covered in README §3 and are now part of the Sphinx reference too.
  - [x] The project's **single tutorial** is `docs/source/jupyter_notebooks/tutorial_pyweatherfiles_case_study.ipynb` (Seville and Madrid, real data): covers `TMYGenerator` → `HourlyEPWConverter` / `convert_met_to_epw` → `DegreeHoursCalculator` → `EpwGroupTrendAnalyzer`, and is committed together with its own input data under `docs/source/jupyter_notebooks/data/` — fully runnable from a fresh clone, no external/untracked data required. Executed end-to-end with `nbconvert` (0 errors) and committed with real outputs/plots embedded.
  - [x] The notebook is **rendered directly inside the Sphinx site** (not just linked as a download): it lives under `docs/source/` and `myst-nb` renders it with `nb_execution_mode="off"`, reusing the outputs/plots already stored in the notebook instead of re-running the full pipeline on every doc build.
  - [x] Added `.readthedocs.yaml` (Sphinx config `docs/source/conf.py`, installs the package with the `docs` extra) so the site can be built on [Read the Docs](https://readthedocs.org/); added the RTD badge + link to `README.md`/`README_ES.md`. The project is now published at `https://pyweatherfiles.readthedocs.io/en/latest/`.
  - [x] Linked the documentation and the tutorial from `README.md` and `README_ES.md` (top banner).
  - [ ] Climate module from task 1: still blocked (task 1 not started yet); nothing to document until it is integrated.
- **Side fixes done along the way (see `pyweatherfiles/degree_hours.py`):** replaced a few `print()` statements that used the Unicode arrow `→`, which raised `UnicodeEncodeError` on Windows consoles using the `cp1252` code page (encountered while validating the tutorial notebook).

### 4. [ ] If the climate module from task 1 is integrated, extend the documentation/tutorial accordingly

- **Status:** deferred — depends entirely on task 1 (still blocked, external module not received).
- **Planned steps once task 1 unblocks:** add the new module to the Sphinx API reference (autodoc will pick it up automatically once it exists), document its data flow, and add a section/notebook cell to `docs/source/jupyter_notebooks/tutorial_pyweatherfiles_case_study.ipynb` if relevant.

### 5. [x] Publish the site on Read the Docs (import the repository on readthedocs.org)

- **Status:** completed 2026-09-21. `termotecnia/pyweatherfiles` is public (see [[notes/decisions|D-007]]), the project was imported manually on Read the Docs, and the successful build is published at `https://pyweatherfiles.readthedocs.io/en/latest/`.
- **Webhook:** Read the Docs created its GitHub webhook automatically when the integration was added. It is active, delivers JSON through verified HTTPS, has a configured signature secret, listens for `create`, `delete`, `pull_request`, and `push`, and its endpoint returned HTTP 200. The webhook configuration is external account state; neither its URL nor its secret belongs in the repository.
- **Completed steps:**
  - [x] Make the GitHub repository public (done 2026-09-21).
  - [x] Import `pyweatherfiles` into Read the Docs and complete its first successful build.
  - [x] Confirm the published `latest` site is reachable.
  - [x] Verify that the automatically created GitHub webhook accepts a signed delivery.
- **Follow-up:**
  - [ ] After the next normal push to `main`, confirm in the Read the Docs build list that it creates a new successful build. A GitHub `ping` validates endpoint delivery but does not prove the `push`-triggered build path.

---

## Notes on using this document

- Add new tasks with a date and, if applicable, references to affected files/modules.
- When completing a task, mark the main checkbox `[ ]` → `[x]` along with the corresponding sub-tasks.
- If a pending task becomes irrelevant, don't delete it: strike it through or move it to a "Discarded" section with the reason.

---

*Last updated: 2026-09-21*



