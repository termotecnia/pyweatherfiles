# -*- coding: utf-8 -*-
"""
tmy
====

TMY (Typical Meteorological Year) generation using the Sandia National
Laboratories methodology (Hall et al., 1978), with additional support for
NREL's TMY3 weighting scheme (Wilcox & Marion, 2008).

This is the core module of the ``pyweatherfiles`` package: :class:`TMYGenerator`
implements the full **7-step Sandia workflow** (Finkelstein-Schafer candidate
selection, proximity re-ranking, persistence filtering, raw assembly and
junction smoothing), orchestrated end-to-end by
:meth:`TMYGenerator.generate_tmy`, or run step by step via the
``sandia_step_1_load_and_prepare`` ... ``sandia_step_7_smooth_junctions``
public methods for full control/inspection of each intermediate result.

This used to be a single monolithic ``tmy.py`` file (~4.100 lines, one class
with ~70 methods); it was split into this package in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6), mirroring the earlier ``degree_hours``/
``epw_trend_analyzer`` splits, to keep each concern (data loading, FS
selection, proximity ranking, persistence, assembly/smoothing, validation,
plotting, backward-compatibility) in its own, more manageable module while
``TMYGenerator`` keeps its full, unchanged public API (implemented via
mixins combined in ``_core.py``). The public import path
(``from pyweatherfiles import TMYGenerator`` / ``from pyweatherfiles import
tmy`` -> ``tmy.TMYGenerator``) is unchanged for callers.

Sub-modules
-----------
- ``_data_loading.py`` (``_DataLoadingMixin``) — Step 1: load & prepare.
- ``_fs_selection.py`` (``_FsSelectionMixin``) — Step 2: Finkelstein-Schafer
  candidate selection.
- ``_proximity.py`` (``_ProximityMixin``) — Step 3: proximity ranking
  (Sawaqed et al., 2005).
- ``_persistence.py`` (``_PersistenceMixin``) — Steps 4 & 5: persistence
  filtering and final month selection.
- ``_assembly_smoothing.py`` (``_AssemblySmoothingMixin``) — Steps 6 & 7:
  raw TMY assembly and junction smoothing.
- ``_validation.py`` (``_ValidationMixin``) — diagnostic/validation methods
  plus the v4.09 analysis & correction methods (``get_candidate_stats``,
  ``generate_full_summary``, ``analyze_selection``,
  ``correct_selection_by_temperature``).
- ``_plotting.py`` (``_PlottingMixin``) — every ``plot_*`` visualization
  method.
- ``_compat.py`` (``_CompatMixin``) — deprecated ``step_1_*``...``step_4_*``
  aliases and ``validation_st2_*``/``validation_st3_*``/``validation_st4_*``
  compatibility properties.
- ``_core.py`` — :class:`TMYGenerator`, combining all of the above as
  mixins, with ``__init__``, ``generate_tmy`` and ``export_tmy``.

Example
-------
Full default pipeline::

    from pyweatherfiles import tmy

    gen = tmy.TMYGenerator(
        file_path="weather_data.csv",
        cdf_method="daily",
        data_frequency="hourly",
        weighting_method="sandia",
    )
    gen.generate_tmy(use_persistence=True, persistence_method="sequential")
    gen.export_tmy("tmy_output.csv")

See also
--------
``pyweatherfiles/degree_hours`` and ``pyweatherfiles/epw_trend_analyzer``,
split with the exact same mixin pattern in the same Fase 5 refactor.
"""

from ._core import TMYGenerator

__all__ = ["TMYGenerator"]

