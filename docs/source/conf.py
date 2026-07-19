# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html
"""Sphinx configuration for the ``pyweatherfiles`` documentation.

Building the docs
------------------
From the repository root::

    pip install -e ".[docs]"
    dist_build_docs.bat

or manually::

    python -m sphinx.ext.apidoc --force -o docs/source/api pyweatherfiles
    cd docs
    make.bat html   # Windows
    make html       # Linux/Mac

The generated HTML is written to ``docs/build/html/index.html``.
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
    "myst_parser",              # Allows writing pages in Markdown (.md)
]

# Allow both .rst and .md source files.
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "html_image",
]
myst_heading_anchors = 3

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
    "numpy": ("https://numpy.org/doc/stable/", None),
}

todo_include_todos = True

# -- Options for HTML output --------------------------------------------------
html_theme = "furo"
html_static_path = ["_static"]
html_title = f"{project} {version}"

html_theme_options = {
    "source_repository": "https://github.com/termotecnia/pyweatherfiles",
    "source_branch": "main",
    "source_directory": "docs/source/",
}

# Markdown files included via MyST (README.md, README_ES.md, ...) live at the
# repository root and use GitHub-flavoured relative links; keep anchors as-is.
suppress_warnings = ["myst.header", "myst.xref_missing"]


