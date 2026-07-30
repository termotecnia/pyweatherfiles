# -*- coding: utf-8 -*-
"""
degree_hours
=============

Heating/cooling degree-hours from an EPW file, using setpoints extracted
from an EnergyPlus IDF model or defined through a custom dictionary, plus a
multi-EPW comparative analyser.

Degree-hours (heating degree-hours, HDH, and cooling degree-hours, CDH) are
one of the simplest and most widely used indicators of a building's thermal
demand: for every hour where the outdoor dry-bulb temperature is below the
heating setpoint (or above the cooling setpoint), the temperature difference
is accumulated. This module computes them from an EPW weather file and a
source of setpoint temperatures, with hourly/daily/monthly/yearly
aggregation, optional date/hour-of-day filtering, and HVAC-availability
masking (hours where the system is scheduled off do not count).

This used to be a single monolithic ``degree_hours.py`` file; it was split
into this package in Fase 5 of ``INFORME_REVISION_GENERAL.md`` (§6) to
keep each class in its own, more manageable module. The public import path
(``from pyweatherfiles.degree_hours import DegreeHoursCalculator`` /
``from pyweatherfiles import degree_hours``) is unchanged.

Three public classes
---------------------
- :class:`DegreeHoursCalculator` (``calculator.py``) — the core engine: one
  EPW in, HDH/CDH out, at any of 4 aggregation frequencies, with setpoints
  either parsed from a real EnergyPlus IDF (dual-setpoint thermostats,
  ``SCHEDULE:COMPACT`` and ``SCHEDULE:YEAR`` schedules,
  ``IdealLoadsAirSystem`` availability) or defined via a lightweight Python
  dict (constant, daily, weekly or hourly-weekly patterns — no IDF
  required).
- :class:`EpwBatchAnalyzer` (``batch_analyzer.py``) — runs
  :class:`DegreeHoursCalculator` over *several* EPW files and *several*
  hour-of-day scenarios at once, producing a single comparative DataFrame
  with ``(epw_name, variable)`` MultiIndex columns — ideal for "TMY vs.
  real years vs. reference file" tables.
- :class:`EpwGroupTrendAnalyzer` (``group_trend_analyzer.py``) — runs
  :class:`DegreeHoursCalculator` over an entire *set* of EPW files (e.g. a
  whole folder of multi-year records), automatically classified into named
  groups (e.g. one per city/climate) from each filename via a configurable
  regex, and adds per-group year-over-year trend statistics (including a
  *global* fixed-effects trend, :meth:`EpwGroupTrendAnalyzer.fit_global_trend`)
  plus small-multiples plotting — ideal for "20 years x N climates, never
  pooled together" analyses.

Example
-------
Single-EPW degree-hours with setpoints from a real IDF model::

    from pyweatherfiles.degree_hours import DegreeHoursCalculator

    calc = DegreeHoursCalculator("city_tmy.epw")
    results = calc.calculate("building_model.idf", frequency=["hourly", "daily", "monthly"], mode="both")
    print(results["monthly"])
    calc.export_results("degree_hours.xlsx")

Comparing a TMY against several real years and a custom setpoint schedule::

    from pyweatherfiles.degree_hours import EpwBatchAnalyzer

    batch = EpwBatchAnalyzer(
        epw_paths=["city_tmy.epw", "city_2019.epw", "city_2020.epw"],
        setpoint_source={"type": "constant", "heating": 20.0, "cooling": 25.0},
        epw_variables={"global_horizontal_radiation": ["sum", "mean"]},
        hours={"morning": list(range(9)), "all_day": list(range(24))},
        frequencies=["monthly"],
    )
    results = batch.run()
    batch.export("batch_degree_hours.xlsx")

Author: Daniel Sánchez-García
"""

from .batch_analyzer import EpwBatchAnalyzer
from .calculator import DegreeHoursCalculator
from .group_trend_analyzer import EpwGroupTrendAnalyzer

__all__ = ["DegreeHoursCalculator", "EpwBatchAnalyzer", "EpwGroupTrendAnalyzer"]

