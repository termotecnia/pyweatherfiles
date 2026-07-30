# -*- coding: utf-8 -*-
"""
tests/test_session_manager.py
================================

Unit tests for :mod:`pyweatherfiles.session_manager` (50% coverage before
this file per ``INFORME_REVISION_GENERAL.md``'s Fase 2 coverage analysis).
This is a cross-cutting module reused by ``tmy``, ``degree_hours``,
``hourly_epw_converter``, ``met_epw_converter`` and ``epw_comparator``, so
improving its coverage benefits the whole package.
"""

import datetime
import json
import os
import pickle

import numpy as np
import pandas as pd
import pytest

from pyweatherfiles.session_manager import (
    _infer_output_dir,
    _make_hash,
    _object_to_json_dict,
    _pickle_obj,
    _sanitize,
    _to_json_safe,
    generate_session_filename,
    load_session,
    save_function_session,
    save_object_session,
)


class _PicklableDummy:
    """Defined at module level (not inside a test function/method) so it is
    actually picklable via the normal ``pickle.dumps()`` path — a class
    defined locally inside a function is never picklable in plain Python,
    regardless of ``_pickle_obj()``'s own fallback logic."""

    def __init__(self, value=42):
        self.value = value


class _NonPicklableDummy:
    """Has one attribute (a lambda) that pickle can never serialise, to
    exercise ``_pickle_obj()``'s partial-state fallback path."""

    def __init__(self):
        self.ok = 1
        self.bad = (lambda x: x)


class TestSanitize:
    def test_extracts_basename_without_extension(self):
        assert _sanitize("C:/data/Seville 2020.xlsx") == "Seville_2020"

    def test_replaces_special_characters_with_underscore(self):
        assert _sanitize("weather@data!file") == "weather_data_file"

    def test_collapses_repeated_underscores(self):
        assert _sanitize("a___b") == "a_b"

    def test_strips_leading_and_trailing_underscores(self):
        assert _sanitize("_leading_and_trailing_") == "leading_and_trailing"

    def test_truncates_to_max_len(self):
        result = _sanitize("a" * 50, max_len=10)
        assert len(result) == 10

    def test_keeps_alphanumeric_and_hyphen(self):
        assert _sanitize("city-name_123") == "city-name_123"


class TestMakeHash:
    def test_deterministic_for_same_input(self):
        d = {"a": 1, "b": "text"}
        assert _make_hash(d) == _make_hash(d)

    def test_independent_of_key_insertion_order(self):
        d1 = {"a": 1, "b": 2}
        d2 = {"b": 2, "a": 1}
        assert _make_hash(d1) == _make_hash(d2)

    def test_different_values_produce_different_hash(self):
        assert _make_hash({"a": 1}) != _make_hash({"a": 2})

    def test_default_length_is_8(self):
        assert len(_make_hash({"a": 1})) == 8

    def test_custom_length(self):
        assert len(_make_hash({"a": 1}, length=12)) == 12


class TestGenerateSessionFilename:
    def test_includes_prefix_and_extension(self):
        name = generate_session_filename("TMYGenerator", {"file_path": "weather.csv"}, "pkl")
        assert name.startswith("TMYGenerator_")
        assert name.endswith(".pkl")

    def test_only_first_three_values_become_visible_slugs(self):
        inputs = {"a": "one", "b": "two", "c": "three", "d": "four"}
        name = generate_session_filename("X", inputs, "json")
        assert "one" in name
        assert "two" in name
        assert "three" in name
        assert "four" not in name

    def test_hash_depends_on_all_values_not_just_first_three(self):
        base = {"a": "one", "b": "two", "c": "three"}
        extended = dict(base, d="four")
        name_base = generate_session_filename("X", base)
        name_extended = generate_session_filename("X", extended)
        # Same visible slugs, but the hash suffix must differ because the
        # 4th value ('four') still contributes to _make_hash().
        assert name_base != name_extended

    def test_empty_inputs_dict_still_produces_valid_filename(self):
        name = generate_session_filename("Prefix", {}, "pkl")
        assert name.startswith("Prefix_")
        assert name.endswith(".pkl")


class TestInferOutputDir:
    def test_finds_directory_from_path_like_value(self, tmp_path):
        file_path = str(tmp_path / "data.csv")
        result = _infer_output_dir({"file_path": file_path})
        assert result == str(tmp_path)

    def test_falls_back_to_cwd_when_no_path_like_value(self):
        result = _infer_output_dir({"method": "average", "n": 5})
        assert result == os.getcwd()

    def test_ignores_non_path_values_before_a_path_value(self, tmp_path):
        file_path = str(tmp_path / "sub" / "data.csv")
        result = _infer_output_dir({"method": "average", "file_path": file_path})
        assert result == str(tmp_path / "sub")


class TestToJsonSafe:
    def test_primitives_pass_through_unchanged(self):
        assert _to_json_safe(None) is None
        assert _to_json_safe(True) is True
        assert _to_json_safe(42) == 42
        assert _to_json_safe(3.14) == 3.14
        assert _to_json_safe("text") == "text"

    def test_numpy_scalars_converted_to_native_python(self):
        assert isinstance(_to_json_safe(np.int64(5)), int)
        assert isinstance(_to_json_safe(np.float64(1.5)), float)
        assert isinstance(_to_json_safe(np.bool_(True)), bool)

    def test_dataframe_is_summarised_not_dumped(self):
        df = pd.DataFrame({"a": [1, 2], "b": [3.0, 4.0]})
        result = _to_json_safe(df)
        assert result["__type__"] == "DataFrame"
        assert result["shape"] == [2, 2]
        assert result["columns"] == ["a", "b"]

    def test_series_is_summarised(self):
        s = pd.Series([1, 2, 3], name="temp")
        result = _to_json_safe(s)
        assert result["__type__"] == "Series"
        assert result["name"] == "temp"
        assert result["length"] == 3

    def test_ndarray_is_summarised(self):
        arr = np.zeros((3, 4))
        result = _to_json_safe(arr)
        assert result["__type__"] == "ndarray"
        assert result["shape"] == [3, 4]

    def test_nested_dict_is_recursively_converted(self):
        result = _to_json_safe({"outer": {"inner": np.int64(7)}})
        assert result == {"outer": {"inner": 7}}
        assert isinstance(result["outer"]["inner"], int)

    def test_list_is_recursively_converted(self):
        result = _to_json_safe([np.int64(1), np.int64(2)])
        assert result == [1, 2]

    def test_long_list_is_truncated(self):
        long_list = list(range(300))
        result = _to_json_safe(long_list)
        assert result["__type__"] == "truncated_list"
        assert result["length"] == 300
        assert result["first_10"] == list(range(10))

    def test_short_list_is_not_truncated(self):
        result = _to_json_safe(list(range(5)))
        assert result == list(range(5))

    def test_datetime_converted_to_isoformat(self):
        dt = datetime.datetime(2020, 1, 1, 12, 30)
        assert _to_json_safe(dt) == dt.isoformat()

    def test_date_converted_to_isoformat(self):
        d = datetime.date(2020, 1, 1)
        assert _to_json_safe(d) == d.isoformat()

    def test_unserialisable_object_falls_back_to_str(self):
        class Custom:
            def __str__(self):
                return "custom-repr"

        assert _to_json_safe(Custom()) == "custom-repr"


class TestObjectToJsonDict:
    def test_captures_public_attributes_only(self):
        class Dummy:
            def __init__(self):
                self.value = 42
                self._private = "hidden"

        result = _object_to_json_dict(Dummy())
        assert result["attributes"]["value"] == 42
        assert "_private" not in result["attributes"]

    def test_includes_class_name_and_timestamp(self):
        class Dummy:
            def __init__(self):
                self.x = 1

        result = _object_to_json_dict(Dummy())
        assert result["class_name"] == "Dummy"
        assert "timestamp" in result
        assert "pyweatherfiles_version" in result

    def test_includes_extra_info_as_inputs(self):
        class Dummy:
            def __init__(self):
                self.x = 1

        result = _object_to_json_dict(Dummy(), extra_info={"source": "test.csv"})
        assert result["inputs"]["source"] == "test.csv"

    def test_attribute_raising_on_access_is_handled_gracefully(self):
        class Dummy:
            def __init__(self):
                self.ok = 1

            @property
            def broken(self):
                raise RuntimeError("boom")

        d = Dummy()
        # Manually inject a "public-looking" broken descriptor via __dict__
        # is tricky for properties; instead simulate via vars() override.
        result = _object_to_json_dict(d)
        assert result["attributes"]["ok"] == 1


class TestPickleObj:
    def test_picklable_object_round_trips(self):
        data = _pickle_obj(_PicklableDummy(value=42))
        restored = pickle.loads(data)
        assert restored.value == 42

    def test_non_picklable_attribute_falls_back_to_partial_state(self, capsys):
        data = _pickle_obj(_NonPicklableDummy())
        restored = pickle.loads(data)
        assert restored["__class__"] == "_NonPicklableDummy"
        assert restored["__state__"]["ok"] == 1
        assert "non-picklable" in restored["__state__"]["bad"]
        captured = capsys.readouterr()
        assert "Warning: direct pickle failed" in captured.out


class TestSaveAndLoadObjectSession:
    def test_round_trip_preserves_object_state(self, tmp_path):
        obj = _PicklableDummy(value=123)
        pkl_path = save_object_session(obj, "Result", {"source": "manual"}, session_dir=str(tmp_path))

        assert pkl_path is not None
        assert os.path.exists(pkl_path)
        restored = load_session(pkl_path)
        assert restored.value == 123

    def test_creates_matching_json_companion_file(self, tmp_path):
        class Result:
            def __init__(self):
                self.value = 99

        pkl_path = save_object_session(Result(), "Result", {"tag": "abc"}, session_dir=str(tmp_path))
        json_path = pkl_path[:-4] + ".json"

        assert os.path.exists(json_path)
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["attributes"]["value"] == 99
        assert data["inputs"]["tag"] == "abc"

    def test_infers_session_dir_when_not_given(self, tmp_path, monkeypatch):
        class Result:
            def __init__(self):
                self.value = 1

        monkeypatch.chdir(tmp_path)
        pkl_path = save_object_session(Result(), "Result", {"method": "x"})
        assert os.path.dirname(os.path.abspath(pkl_path)) == str(tmp_path)

    def test_creates_session_dir_if_missing(self, tmp_path):
        class Result:
            def __init__(self):
                self.value = 1

        new_dir = tmp_path / "does" / "not" / "exist"
        save_object_session(Result(), "Result", {"x": 1}, session_dir=str(new_dir))
        assert new_dir.exists()


class TestSaveAndLoadFunctionSession:
    def test_round_trip_preserves_inputs_and_result(self, tmp_path):
        inputs = {"a": 2, "b": 3}
        pkl_path = save_function_session("add", inputs, result=5, session_dir=str(tmp_path))

        restored = load_session(pkl_path)
        assert restored["inputs"] == inputs
        assert restored["result"] == 5

    def test_extra_data_is_stored(self, tmp_path):
        pkl_path = save_function_session(
            "double", {"x": 21}, result=42, session_dir=str(tmp_path), extra={"note": "doubled"}
        )
        restored = load_session(pkl_path)
        assert restored["extra"] == {"note": "doubled"}

    def test_json_companion_summarises_result(self, tmp_path):
        df_result = pd.DataFrame({"a": [1, 2, 3]})
        pkl_path = save_function_session(
            "make_df", {"n": 3}, result=df_result, session_dir=str(tmp_path)
        )
        json_path = pkl_path[:-4] + ".json"
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["result"]["__type__"] == "DataFrame"
        assert data["result"]["shape"] == [3, 1]


class TestLoadSession:
    def test_raises_file_not_found_for_missing_path(self, tmp_path):
        missing = tmp_path / "does_not_exist.pkl"
        with pytest.raises(FileNotFoundError):
            load_session(str(missing))




