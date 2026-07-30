# -*- coding: utf-8 -*-
"""
tests/conftest.py
===================

Shared pytest fixtures for the ``pyweatherfiles`` test suite.

These fixtures provide lightweight, dependency-free stand-ins for Ladybug
``EPW`` hourly data-collection fields, so that
:mod:`pyweatherfiles.epw_field_utils` can be unit-tested without needing a
real ``.epw`` file on disk.
"""

import pytest


class FakeDataType:
    """Minimal stand-in for ``ladybug.datatype`` metadata."""

    def __init__(self, point_in_time: bool):
        self.point_in_time = point_in_time


class FakeHeader:
    """Minimal stand-in for a Ladybug ``Header`` object."""

    def __init__(self, point_in_time: bool):
        self.data_type = FakeDataType(point_in_time)


class FakeField:
    """Minimal stand-in for a Ladybug hourly ``DataCollection`` field."""

    def __init__(self, values, point_in_time: bool):
        self.header = FakeHeader(point_in_time)
        self.values = values


class FakeEPW:
    """
    Minimal stand-in for a ``ladybug.epw.EPW`` object: only implements
    plain attribute get/set for hourly fields, which is all
    :func:`pyweatherfiles.epw_field_utils.set_epw_values`/``get_epw_values``
    and :func:`pyweatherfiles.epw_field_utils.neutralize_unused_epw_fields`
    need.
    """

    def add_field(self, name: str, values, point_in_time: bool = True) -> None:
        setattr(self, name, FakeField(values, point_in_time))


@pytest.fixture
def fake_epw() -> FakeEPW:
    """A fresh :class:`FakeEPW` instance with no fields defined."""
    return FakeEPW()

