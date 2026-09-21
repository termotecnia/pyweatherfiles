# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html
"""Sphinx configuration for the ``pyweatherfiles`` documentation.

The site is built automatically on `Read the Docs
<https://readthedocs.org/>`_ using ``.readthedocs.yaml`` at the repository
root, which installs the package with the ``docs`` extra and runs Sphinx
against this ``conf.py``.

Tutorial notebook
------------------
``jupyter_notebooks/tutorial_pyweatherfiles_case_study.ipynb`` (Seville and
Madrid, real data) is the project's single tutorial. It lives directly under
this ``source/`` directory together with its own input data
(``jupyter_notebooks/data/``), since the notebook and its data are meant to
be cloned and run standalone from GitHub, not just rendered here. It is
rendered in place with ``myst-nb`` using the outputs already stored in the
notebook (``nb_execution_mode = "off"``), so building the documentation never
re-runs the full TMY/degree-hours/trend pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

# -- Path setup --------------------------------------------------------------
# Make the ``pyweatherfiles`` package importable for autodoc, regardless of
# whether it is pip-installed in the active environment.
DOCS_SOURCE_DIR = Path(__file__).resolve().parent
REPO_ROOT = DOCS_SOURCE_DIR.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# -- Project information ------------------------------------------------------
project = "pyweatherfiles"
author = "Daniel Sánchez-García"
copyright = f"2026, {author}"

try:
    import pyweatherfiles as _pkg
    release = getattr(_pkg, "__version__", "0.0.0")
except Exception:  # pragma: no cover - docs must still build if import fails
    release = "0.0.0"
version = release

# -- General configuration ----------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",      # Parses Google/NumPy-style docstrings (Args:, Returns:, ...)
    "sphinx.ext.viewcode",      # Adds links to highlighted source code
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    "myst_nb",                  # Markdown (.md) pages *and* Jupyter notebook (.ipynb) rendering.
                                 # myst_nb internally sets up myst_parser; do NOT also list
                                 # "myst_parser" here or Sphinx double-registers its roles/directives.
    "sphinx_rtd_theme",         # Read the Docs theme (also pulls in sphinxcontrib-jquery).
]

# NOTE: source_suffix is intentionally *not* set manually here. myst_nb
# registers ".md" and ".ipynb" itself (via app.add_source_suffix(..., "myst-nb"));
# overriding source_suffix with the plain "markdown" parser name would break
# that registration (Sphinx would then look for a parser literally named
# "markdown", which no longer exists once "myst_parser" is not also listed
# above). ".rst" continues to work via Sphinx's own built-in default.

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "html_image",
]
myst_heading_anchors = 3

# -- myst-nb (notebook rendering) ---------------------------------------------
# Render the tutorial notebook using the outputs it already contains instead
# of re-executing it: the real pipeline needs the Seville dataset, an
# EnergyPlus IDF, and several heavy optional dependencies (ladybug, pvlib...)
# that should not be a hard requirement just to build the documentation.
nb_execution_mode = "off"
# Notebooks are the tutorial itself, not doctests to fail the build over.
nb_execution_allow_errors = True
# Merge consecutive stdout/stderr streams so long TMY console logs stay readable.
nb_merge_streams = True

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# Napoleon settings (docstrings in this codebase mix Google-style "Args:" and
# plain prose; Napoleon's defaults handle both reasonably well).
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_use_param = True
napoleon_use_rtype = False

# Autodoc: keep member order as declared in the source, show inherited members
# for the public API and always include constructor signatures.
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}

# Optional/heavy dependencies are mocked so the documentation can be built
# even in minimal environments that do not have them installed (they are not
# required to introspect the public API surface). ``ladybug-core`` is a hard
# runtime dependency of the package (see pyproject.toml) and is intentionally
# NOT mocked so its real API is reflected in the docs when available.
autodoc_mock_imports = ["pvlib", "tabulate", "besos", "eppy", "accim"]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
}

todo_include_todos = True

# -- Options for HTML output --------------------------------------------------
html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_title = f"{project} {version}"

html_theme_options = {
    "collapse_navigation": False,
    "sticky_navigation": True,
    "navigation_depth": 3,
    "titles_only": False,
    "prev_next_buttons_location": "both",
    "style_external_links": True,
}

# Enables the theme's "Edit on GitHub" / "View page source" links.
html_context = {
    "display_github": True,
    "github_user": "termotecnia",
    "github_repo": "pyweatherfiles",
    "github_version": "main",
    "conf_py_path": "/docs/source/",
}

# Markdown files included via MyST (README.md, README_ES.md) live at the
# repository root and use GitHub-flavoured relative links; keep anchors as-is.
suppress_warnings = ["myst.header", "myst.xref_missing"]


