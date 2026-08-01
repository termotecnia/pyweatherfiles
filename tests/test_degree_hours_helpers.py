# -*- coding: utf-8 -*-
"""
tests/test_degree_hours_helpers.py
=====================================

Unit tests for the pure, dependency-free helpers in
``pyweatherfiles.degree_hours._helpers`` (35% coverage before this file per
``INFORME_REVISION_GENERAL.md``'s Fase 2 coverage analysis).
"""

import numpy as np
import pytest

from pyweatherfiles.degree_hours._helpers import (
    EP_DAYTYPE_WEEKDAYS,
    WEEKDAILY_FIELD,
    build_24h_profile,
    idf_objects,
    until_to_hour,
)


class TestUntilToHour:
    def test_parses_simple_time(self):
        assert until_to_hour("08:00") == 8

    def test_parses_with_surrounding_whitespace(self):
        assert until_to_hour("  17:30  ") == 17

    def test_parses_24_00_as_24(self):
        assert until_to_hour("24:00") == 24

    def test_parses_midnight(self):
        assert until_to_hour("00:00") == 0


class TestBuild24hProfile:
    def test_single_pair_fills_from_zero(self):
        profile = build_24h_profile([(24, 5.0)])
        assert list(profile) == [5.0] * 24

    def test_two_pairs_split_the_day(self):
        profile = build_24h_profile([(8, 17.0), (24, 20.0)])
        assert list(profile[:8]) == [17.0] * 8
        assert list(profile[8:]) == [20.0] * 16

    def test_unsorted_pairs_are_sorted_internally(self):
        sorted_profile = build_24h_profile([(8, 17.0), (24, 20.0)])
        unsorted_profile = build_24h_profile([(24, 20.0), (8, 17.0)])
        np.testing.assert_array_equal(sorted_profile, unsorted_profile)

    def test_empty_pairs_returns_all_nan(self):
        profile = build_24h_profile([])
        assert profile.shape == (24,)
        assert np.all(np.isnan(profile))

    def test_partial_coverage_leaves_nan_gaps(self):
        # Only covers hours 0-13 (via the single (14, 99.0) pair); the rest
        # of the day is left as NaN since no pair covers it.
        profile = build_24h_profile([(14, 99.0)])
        assert profile[13] == 99.0
        assert np.isnan(profile[14])
        assert np.isnan(profile[23])


class FakeIdfInner:
    """Minimal stand-in for eppy's ``IDF.idfobjects`` dict-like access."""

    def __init__(self, objs_by_key):
        self.idfobjects = objs_by_key


class FakeBesosBuilding:
    """Minimal stand-in for a besos ``Building`` wrapping an eppy IDF
    (exposed via its ``.idf`` attribute)."""

    def __init__(self, inner):
        self.idf = inner


class TestIdfObjects:
    def test_finds_objects_with_exact_key_case(self):
        inner = FakeIdfInner({"ZONE": ["z1", "z2"]})
        assert idf_objects(inner, "ZONE") == ["z1", "z2"]

    def test_case_insensitive_lookup_uppercase_stored(self):
        inner = FakeIdfInner({"ZONE": ["z1"]})
        assert idf_objects(inner, "zone") == ["z1"]
        assert idf_objects(inner, "Zone") == ["z1"]

    def test_case_insensitive_lookup_lowercase_stored(self):
        inner = FakeIdfInner({"zone": ["z1"]})
        assert idf_objects(inner, "ZONE") == ["z1"]

    def test_missing_key_returns_empty_list(self):
        inner = FakeIdfInner({"ZONE": ["z1"]})
        assert idf_objects(inner, "SPACE") == []

    def test_unwraps_besos_building_wrapper(self):
        inner = FakeIdfInner({"ZONE": ["z1", "z2"]})
        wrapped = FakeBesosBuilding(inner)
        assert idf_objects(wrapped, "ZONE") == ["z1", "z2"]


class TestModuleConstants:
    def test_ep_daytype_weekdays_covers_all_python_weekdays(self):
        all_weekdays = set()
        for key in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"):
            all_weekdays.update(EP_DAYTYPE_WEEKDAYS[key])
        assert all_weekdays == set(range(7))

    def test_weekdays_and_weekends_partition_the_week(self):
        weekdays = set(EP_DAYTYPE_WEEKDAYS["weekdays"])
        weekends = set(EP_DAYTYPE_WEEKDAYS["weekends"])
        assert weekdays.isdisjoint(weekends)
        assert weekdays | weekends == set(range(7))

    def test_alldays_covers_every_weekday(self):
        assert set(EP_DAYTYPE_WEEKDAYS["alldays"]) == set(range(7))

    def test_weekdaily_field_has_one_entry_per_python_weekday(self):
        assert set(WEEKDAILY_FIELD.keys()) == set(range(7))
        # Field indices 2-8 correspond to Sun..Sat as raw eppy fieldvalues
        # positions in SCHEDULE:WEEK:DAILY (index 0 = object type, 1 = Name).
        assert set(WEEKDAILY_FIELD.values()) == set(range(2, 9))

