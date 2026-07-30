# -*- coding: utf-8 -*-
"""
session_manager.py
===================

Centralised, reproducible session persistence for the whole ``pyweatherfiles``
package.

**What problem does this module solve?** Almost every public class/function in
the package (:class:`~pyweatherfiles.tmy.TMYGenerator`,
:class:`~pyweatherfiles.hourly_epw_converter.HourlyEPWConverter`,
:class:`~pyweatherfiles.degree_hours.DegreeHoursCalculator`,
:func:`~pyweatherfiles.met_epw_converter.convert_met_to_epw`, etc.) can save a
**session** right after finishing its work: a snapshot of exactly what inputs
were used and what the resulting object/DataFrame looked like. This makes runs
auditable and reproducible (useful for scientific articles, QA, or simply
remembering "how did I generate this file six months ago?").

Every session is written as **two files** sharing the same deterministic,
collision-resistant name (see :func:`generate_session_filename`):

- ``{prefix}_{slug1}_{slug2}_{slug3}_{hash8}.pkl`` — the actual serialised
  Python object (or a partial, sanitised state dict if some attribute cannot
  be pickled), recoverable with :func:`load_session`.
- ``{prefix}_{slug1}_{slug2}_{slug3}_{hash8}.json`` — a human-readable
  snapshot (timestamp, package version, all public attributes converted to a
  JSON-safe form) that can be opened in any text editor without Python.

This module is used internally by other modules and is rarely imported
directly by end users, but its public functions are perfectly usable on their
own if you want to add session persistence to your own scripts.

Examples
--------
Saving the session of an arbitrary object you built yourself::

    from pyweatherfiles.session_manager import save_object_session, load_session

    class MyResult:
        def __init__(self, value):
            self.value = value

    result = MyResult(value=42)
    pkl_path = save_object_session(
        result,
        prefix="MyResult",
        inputs_dict={"source_file": "data.csv", "method": "average"},
    )
    # -> ".../MyResult_data_average_9f8a1c02.pkl" (+ matching .json)

    restored = load_session(pkl_path)
    assert restored.value == 42

Saving the session of a plain function call (no class involved)::

    from pyweatherfiles.session_manager import save_function_session

    def add(a, b):
        return a + b

    inputs = {"a": 2, "b": 3}
    save_function_session("add", inputs, result=add(**inputs))
"""

import copy
import datetime
import hashlib
import json
import os
import pickle
import re
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

try:
    from . import __version__ as _PKG_VERSION
except ImportError:
    _PKG_VERSION = "unknown"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sanitize(text: str, max_len: int = 28) -> str:
    """Turn an arbitrary string (typically a file path) into a short,
    filesystem-safe slug usable inside a filename.

    The base name (without directory or extension) is extracted, every
    character that is not alphanumeric or ``_``/``-`` is replaced with ``_``,
    repeated underscores are collapsed, and the result is truncated to
    *max_len* characters.

    Args:
        text (str): Arbitrary text to sanitise (often a file path or a
            parameter value).
        max_len (int, optional): Maximum length of the returned slug.
            Defaults to 28.

    Returns:
        str: A filesystem-safe slug, e.g. ``_sanitize("C:/data/Seville 2020.xlsx")
        -> "Seville_2020"``.
    """
    text = os.path.splitext(os.path.basename(str(text)))[0]
    text = re.sub(r'[^\w\-]', '_', text)
    text = re.sub(r'_+', '_', text).strip('_')
    return text[:max_len]


def _make_hash(inputs_dict: dict, length: int = 8) -> str:
    """Compute a short, deterministic MD5 hash that uniquely identifies a set
    of inputs, used as the final component of session filenames so that two
    runs with different parameters never collide.

    Args:
        inputs_dict (dict): Mapping of input names to values. Values are
            stringified and the dict is sorted by key before hashing, so the
            hash only depends on content, not on key/insertion order.
        length (int, optional): Number of hex characters to keep from the
            full MD5 digest. Defaults to 8.

    Returns:
        str: A lowercase hexadecimal string of length *length*.
    """
    canonical = json.dumps(
        {k: str(v) for k, v in sorted(inputs_dict.items())},
        sort_keys=True,
    ).encode()
    return hashlib.md5(canonical).hexdigest()[:length]


def generate_session_filename(
    prefix: str,
    inputs_dict: dict,
    extension: str = "pkl",
) -> str:
    """
    Build a unique, human-readable session filename.

    Format: ``{prefix}_{slug1}_{slug2}_{slug3}_{hash8}.{ext}``, where up to
    the first 3 values of *inputs_dict* are turned into short slugs (via
    :func:`_sanitize`) and appended to *prefix*, followed by a short
    deterministic hash (via :func:`_make_hash`) of the *entire* inputs dict.
    This keeps filenames readable at a glance while still guaranteeing
    uniqueness across different parameter combinations.

    Args:
        prefix (str): Class or function name used as the filename prefix
            (e.g. ``'TMYGenerator'``, ``'convert_met_to_epw'``).
        inputs_dict (dict): Key inputs used to distinguish sessions (file
            paths, methods, years...). Only the first 3 values are turned
            into visible slugs; all of them contribute to the hash.
        extension (str, optional): File extension without the leading dot.
            Defaults to ``'pkl'``.

    Returns:
        str: The generated filename, e.g.
        ``"TMYGenerator_weather_data_daily_hourly_3a1b9c04.pkl"``.

    Example:
        >>> generate_session_filename(
        ...     "TMYGenerator",
        ...     {"file_path": "weather_data.csv", "cdf_method": "daily"},
        ... )
        'TMYGenerator_weather_data_daily_....pkl'
    """
    parts = [prefix]
    for i, v in enumerate(inputs_dict.values()):
        if i >= 3:
            break
        slug = _sanitize(str(v))
        if slug:
            parts.append(slug)
    parts.append(_make_hash(inputs_dict))
    return "_".join(parts) + f".{extension}"


def _infer_output_dir(inputs_dict: dict) -> str:
    """Guess a sensible directory to write session files to when the caller
    did not provide an explicit ``session_dir``.

    Scans *inputs_dict* values for anything that looks like a file path
    (contains a path separator) and returns the absolute directory of the
    first match; falls back to the current working directory otherwise.

    Args:
        inputs_dict (dict): Mapping of input names to values, typically
            including at least one file path (e.g. ``file_path``,
            ``epw_path``).

    Returns:
        str: An absolute directory path.
    """
    for v in inputs_dict.values():
        s = str(v)
        if os.sep in s or '/' in s:
            d = os.path.dirname(os.path.abspath(s))
            if d:
                return d
    return os.getcwd()


# ---------------------------------------------------------------------------
# JSON serialisation helpers
# ---------------------------------------------------------------------------

def _to_json_safe(value: Any) -> Any:
    """Recursively convert an arbitrary Python value into something
    ``json.dump``-compatible, without raising ``TypeError`` on the objects
    commonly found in this package (:class:`pandas.DataFrame`,
    :class:`pandas.Series`, :class:`numpy.ndarray`, numpy scalars, nested
    dict/list/tuple, dates...).

    DataFrames/Series/ndarrays are **summarised** (shape, columns, dtypes)
    rather than fully dumped, to keep the resulting JSON small and readable.
    Long lists/tuples (more than 200 items) are truncated, keeping only the
    first 10 elements plus their original length. Anything else that cannot
    be converted falls back to ``str(value)`` or the literal string
    ``"<non-serialisable>"``.

    Args:
        value (Any): Value to convert.

    Returns:
        Any: A JSON-serialisable representation of *value*.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.DataFrame):
        return {
            "__type__": "DataFrame",
            "shape": list(value.shape),
            "columns": list(value.columns.astype(str)),
            "dtypes": {str(c): str(dt) for c, dt in value.dtypes.items()},
        }
    if isinstance(value, pd.Series):
        return {
            "__type__": "Series",
            "name": str(value.name) if value.name is not None else None,
            "length": len(value),
            "dtype": str(value.dtype),
        }
    if isinstance(value, np.ndarray):
        return {"__type__": "ndarray", "shape": list(value.shape), "dtype": str(value.dtype)}
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        safe = [_to_json_safe(item) for item in value]
        if len(safe) > 200:
            return {"__type__": "truncated_list", "length": len(safe), "first_10": safe[:10]}
        return safe
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    try:
        return str(value)
    except Exception:
        return "<non-serialisable>"


def _object_to_json_dict(obj: Any, extra_info: Optional[dict] = None) -> dict:
    """Build a JSON-safe dict snapshot of every public (non-underscore)
    attribute of *obj*, used as the payload written to the ``.json``
    companion file in :func:`save_object_session`.

    Args:
        obj (Any): The instance whose public attributes should be captured.
        extra_info (dict, optional): Extra key/value pairs (typically the
            constructor inputs) to store under the ``"inputs"`` key.

    Returns:
        dict: A dict with ``timestamp``, ``class_name``,
        ``pyweatherfiles_version``, optionally ``inputs``, and
        ``attributes`` (every public attribute, converted via
        :func:`_to_json_safe`; attributes that raise on access are recorded
        as ``"<error reading attribute>"``).
    """
    result: dict = {
        "timestamp": datetime.datetime.now().isoformat(),
        "class_name": type(obj).__name__,
        "pyweatherfiles_version": _PKG_VERSION,
    }
    if extra_info:
        result["inputs"] = {k: _to_json_safe(v) for k, v in extra_info.items()}
    attrs: dict = {}
    for attr in vars(obj):
        if attr.startswith("_"):
            continue
        try:
            attrs[attr] = _to_json_safe(getattr(obj, attr))
        except Exception:
            attrs[attr] = "<error reading attribute>"
    result["attributes"] = attrs
    return result


def _function_result_to_json_dict(
    func_name: str,
    inputs: dict,
    result: Any,
    extra: Optional[dict] = None,
) -> dict:
    """Build the JSON-safe payload used by :func:`save_function_session`
    for a standalone function call (as opposed to a class instance).

    Args:
        func_name (str): Name of the function that was called.
        inputs (dict): The arguments the function was called with.
        result (Any): The function's return value.
        extra (dict, optional): Any additional data worth recording
            (e.g. intermediate DataFrames, flags).

    Returns:
        dict: A dict with ``timestamp``, ``function_name``,
        ``pyweatherfiles_version``, ``inputs``, ``result`` and, if provided,
        ``extra`` — all converted to JSON-safe values via
        :func:`_to_json_safe`.
    """
    d: dict = {
        "timestamp": datetime.datetime.now().isoformat(),
        "function_name": func_name,
        "pyweatherfiles_version": _PKG_VERSION,
        "inputs": {k: _to_json_safe(v) for k, v in inputs.items()},
        "result": _to_json_safe(result),
    }
    if extra:
        d["extra"] = {k: _to_json_safe(v) for k, v in extra.items()}
    return d


# ---------------------------------------------------------------------------
# Pickle helpers (with graceful fallback for non-picklable attributes)
# ---------------------------------------------------------------------------

def _pickle_obj(obj: Any) -> bytes:
    """
    Serialise *obj* with :mod:`pickle`, tolerating attributes that cannot be
    pickled (e.g. open file handles, some C-extension objects).

    The function first tries a direct ``pickle.dumps(obj)``. If that raises
    any exception, it falls back to pickling a **sanitised state dict**
    instead: every attribute in ``vars(obj)`` is pickled individually, and
    any attribute that fails is replaced with a ``"<non-picklable: TypeName>"``
    placeholder string so the rest of the session is not lost.

    Args:
        obj (Any): Object to serialise.

    Returns:
        bytes: The pickled payload, ready to be written to a ``.pkl`` file.
    """
    try:
        return pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        print(f"[SESSION] Warning: direct pickle failed ({e}). Saving partial state…")
        state: dict = {}
        for k, v in vars(obj).items():
            try:
                pickle.dumps(v)
                state[k] = v
            except Exception:
                state[k] = f"<non-picklable: {type(v).__name__}>"
        payload = {"__class__": type(obj).__name__, "__state__": state}
        return pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_object_session(
    obj: Any,
    prefix: str,
    inputs_dict: dict,
    session_dir: Optional[str] = None,
) -> Optional[str]:
    """
    Save a class instance to a ``.pkl`` file (full object, via
    :func:`_pickle_obj`) plus a companion ``.json`` metadata file (via
    :func:`_object_to_json_dict`), using a deterministic filename computed by
    :func:`generate_session_filename`.

    This is the function called internally, right after a heavy computation
    finishes, by classes such as :class:`~pyweatherfiles.tmy.TMYGenerator` or
    :class:`~pyweatherfiles.degree_hours.DegreeHoursCalculator` whenever
    ``save_session=True`` (the default across the package).

    Parameters
    ----------
    obj : Any
        Class instance to persist (e.g. a fitted ``TMYGenerator``).
    prefix : str
        Human-readable filename prefix (e.g. ``'TMYGenerator'``).
    inputs_dict : dict
        Key inputs used to build the unique filename (e.g.
        ``{"file_path": ..., "cdf_method": ...}``).
    session_dir : str, optional
        Directory for the files. Inferred from *inputs_dict* (directory of
        the first path-like value found) if ``None``.

    Returns
    -------
    str or None
        Path to the saved ``.pkl`` file, or ``None`` if pickling failed
        outright.

    Example
    -------
    >>> class Dummy:
    ...     def __init__(self):
    ...         self.value = 123
    >>> save_object_session(Dummy(), "Dummy", {"source": "manual"})  # doctest: +SKIP
    '/current/dir/Dummy_manual_....pkl'
    """
    if session_dir is None:
        session_dir = _infer_output_dir(inputs_dict)
    os.makedirs(session_dir, exist_ok=True)

    pkl_path  = os.path.join(session_dir, generate_session_filename(prefix, inputs_dict, "pkl"))
    json_path = os.path.join(session_dir, generate_session_filename(prefix, inputs_dict, "json"))

    # --- Pickle ---
    try:
        data = _pickle_obj(obj)
        with open(pkl_path, "wb") as f:
            f.write(data)
        print(f"[SESSION] Pickle saved to: {pkl_path}")
    except Exception as e:
        print(f"[SESSION] ERROR saving pickle: {e}")
        return None

    # --- JSON ---
    try:
        json_dict = _object_to_json_dict(obj, extra_info=inputs_dict)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_dict, f, indent=2, ensure_ascii=False, default=str)
        print(f"[SESSION] JSON saved to:    {json_path}")
    except Exception as e:
        print(f"[SESSION] ERROR saving JSON: {e}")

    return pkl_path


def save_function_session(
    func_name: str,
    inputs_dict: dict,
    result: Any,
    session_dir: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Optional[str]:
    """
    Persist a standalone function's inputs + result as a ``.pkl`` file
    (a dict with ``inputs``/``result``/``extra`` keys) plus a companion
    ``.json`` metadata file (via :func:`_function_result_to_json_dict`).

    This is the function-style counterpart of :func:`save_object_session`,
    used by module-level functions that are not tied to a class, such as
    :func:`~pyweatherfiles.met_epw_converter.convert_met_to_epw` or
    :func:`~pyweatherfiles.epw_comparator.create_comparison_hourly_dataframe`.

    Parameters
    ----------
    func_name : str
        Function name used as the filename prefix (e.g.
        ``'convert_met_to_epw'``).
    inputs_dict : dict
        Inputs used to derive the unique filename (e.g. the file paths the
        function was called with).
    result : Any
        The function's return value (can be a bool, a DataFrame, etc.; it is
        summarised, not fully dumped, in the JSON file).
    session_dir : str, optional
        Directory for the files. Inferred from *inputs_dict* if ``None``.
    extra : dict, optional
        Additional data to include in the JSON (e.g. flags, intermediate
        DataFrames).

    Returns
    -------
    str or None
        Path to the saved ``.pkl`` file, or ``None`` on failure.

    Example
    -------
    >>> def double(x):
    ...     return x * 2
    >>> x = 21
    >>> save_function_session("double", {"x": x}, result=double(x))  # doctest: +SKIP
    '/current/dir/double_21_....pkl'
    """
    if session_dir is None:
        session_dir = _infer_output_dir(inputs_dict)
    os.makedirs(session_dir, exist_ok=True)

    pkl_path  = os.path.join(session_dir, generate_session_filename(func_name, inputs_dict, "pkl"))
    json_path = os.path.join(session_dir, generate_session_filename(func_name, inputs_dict, "json"))

    payload = {"inputs": inputs_dict, "result": result, "extra": extra}

    # --- Pickle ---
    try:
        with open(pkl_path, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        print(f"[SESSION] Pickle saved to: {pkl_path}")
    except Exception as e:
        print(f"[SESSION] ERROR saving pickle: {e}")
        return None

    # --- JSON ---
    try:
        json_dict = _function_result_to_json_dict(func_name, inputs_dict, result, extra)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_dict, f, indent=2, ensure_ascii=False, default=str)
        print(f"[SESSION] JSON saved to:    {json_path}")
    except Exception as e:
        print(f"[SESSION] ERROR saving JSON: {e}")

    return pkl_path


def load_session(pkl_path: str) -> Any:
    """
    Load a session previously saved by :func:`save_object_session` or
    :func:`save_function_session`.

    Parameters
    ----------
    pkl_path : str
        Path to the ``.pkl`` file (as returned by either save function).

    Returns
    -------
    Any
        The deserialised object (for :func:`save_object_session`) or the
        ``{"inputs": ..., "result": ..., "extra": ...}`` payload dict (for
        :func:`save_function_session`). If the original object could not be
        pickled directly, a ``{"__class__": ..., "__state__": ...}`` dict is
        returned instead (see :func:`_pickle_obj`).

    Raises
    ------
    FileNotFoundError
        If *pkl_path* does not exist.

    Example
    -------
    >>> from pyweatherfiles.session_manager import load_session
    >>> session = load_session("TMYGenerator_weather_data_daily_3a1b9c04.pkl")  # doctest: +SKIP
    >>> session.validation_full_summary  # doctest: +SKIP
    """
    if not os.path.exists(pkl_path):
        raise FileNotFoundError(f"Session file not found: {pkl_path}")
    with open(pkl_path, "rb") as f:
        obj = pickle.load(f)
    print(f"[SESSION] Session loaded from: {pkl_path}")
    return obj
