# -*- coding: utf-8 -*-
"""
session_manager.py
==================
Centralised session persistence (pickle + JSON) for pyweatherfiles
classes and standalone functions.

Public API
----------
save_object_session(obj, prefix, inputs_dict, session_dir=None)
save_function_session(func_name, inputs_dict, result, session_dir=None, extra=None)
load_session(pkl_path)
generate_session_filename(prefix, inputs_dict, extension='pkl')
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
    """Return a filesystem-safe slug from *text*."""
    text = os.path.splitext(os.path.basename(str(text)))[0]
    text = re.sub(r'[^\w\-]', '_', text)
    text = re.sub(r'_+', '_', text).strip('_')
    return text[:max_len]


def _make_hash(inputs_dict: dict, length: int = 8) -> str:
    """Short deterministic MD5 hash of *inputs_dict*."""
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

    Format: ``{prefix}_{slug1}_{slug2}_{hash8}.{ext}``

    Parameters
    ----------
    prefix : str
        Class / function name (e.g. ``'TMYGenerator'``).
    inputs_dict : dict
        Key inputs used to distinguish sessions (paths, methods, years…).
    extension : str
        File extension without leading dot (default: ``'pkl'``).

    Returns
    -------
    str
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
    """Return the directory of the first file-path value found in *inputs_dict*."""
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
    """Recursively convert *value* to a JSON-serialisable form."""
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
    """Snapshot of *obj*'s public attributes as a JSON-safe dict."""
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
    """JSON snapshot for a standalone function's result."""
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
    Try to pickle *obj* as-is; if that fails, pickle a sanitised state dict
    (non-picklable attributes are replaced with a string placeholder).
    """
    try:
        return pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        print(f"[SESSION] Advertencia: pickle directo falló ({e}). Guardando estado parcial…")
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
    Save *obj* to a ``.pkl`` file and a ``.json`` metadata file.

    Parameters
    ----------
    obj : Any
        Class instance to persist.
    prefix : str
        Human-readable filename prefix (e.g. ``'TMYGenerator'``).
    inputs_dict : dict
        Key inputs used to build the unique filename.
    session_dir : str, optional
        Directory for the files. Inferred from *inputs_dict* if ``None``.

    Returns
    -------
    str or None
        Path to the saved ``.pkl`` file, or ``None`` on failure.
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
        print(f"[SESSION] Pickle guardado en: {pkl_path}")
    except Exception as e:
        print(f"[SESSION] ERROR al guardar pickle: {e}")
        return None

    # --- JSON ---
    try:
        json_dict = _object_to_json_dict(obj, extra_info=inputs_dict)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_dict, f, indent=2, ensure_ascii=False, default=str)
        print(f"[SESSION] JSON guardado en:   {json_path}")
    except Exception as e:
        print(f"[SESSION] ERROR al guardar JSON: {e}")

    return pkl_path


def save_function_session(
    func_name: str,
    inputs_dict: dict,
    result: Any,
    session_dir: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Optional[str]:
    """
    Persist a standalone function's inputs + result as ``.pkl`` + ``.json``.

    Parameters
    ----------
    func_name : str
        Function name used as filename prefix.
    inputs_dict : dict
        Inputs used to derive the unique filename.
    result : Any
        The function's return value.
    session_dir : str, optional
        Directory for the files. Inferred from *inputs_dict* if ``None``.
    extra : dict, optional
        Additional data to include in the JSON (e.g. intermediate DataFrames).

    Returns
    -------
    str or None
        Path to the saved ``.pkl`` file, or ``None`` on failure.
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
        print(f"[SESSION] Pickle guardado en: {pkl_path}")
    except Exception as e:
        print(f"[SESSION] ERROR al guardar pickle: {e}")
        return None

    # --- JSON ---
    try:
        json_dict = _function_result_to_json_dict(func_name, inputs_dict, result, extra)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_dict, f, indent=2, ensure_ascii=False, default=str)
        print(f"[SESSION] JSON guardado en:   {json_path}")
    except Exception as e:
        print(f"[SESSION] ERROR al guardar JSON: {e}")

    return pkl_path


def load_session(pkl_path: str) -> Any:
    """
    Load a session previously saved by :func:`save_object_session` or
    :func:`save_function_session`.

    Parameters
    ----------
    pkl_path : str
        Path to the ``.pkl`` file.

    Returns
    -------
    Any
        The deserialised object or payload dict.
    """
    if not os.path.exists(pkl_path):
        raise FileNotFoundError(f"Session file not found: {pkl_path}")
    with open(pkl_path, "rb") as f:
        obj = pickle.load(f)
    print(f"[SESSION] Sesión cargada desde: {pkl_path}")
    return obj
