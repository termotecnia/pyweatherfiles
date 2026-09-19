# -*- coding: utf-8 -*-
"""
tmy/_compat.py
================

:class:`_CompatMixin` — backward-compatibility layer for
:class:`~pyweatherfiles.tmy.TMYGenerator`: the deprecated ``step_1_*`` ...
``step_4_*`` method aliases (pre-4.10 API) and the deprecated
``validation_st2_*``/``validation_st3_*``/``validation_st4_*`` property
names, all delegating to their current ``sandia_step_*``/
``validation_step*`` counterparts and emitting a ``DeprecationWarning``.

Extracted from the former monolithic ``tmy.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6). See ``pyweatherfiles/tmy/__init__.py``
for the package-level overview.
"""

import warnings


class _CompatMixin:
    """Deprecated ``step_*`` aliases and ``validation_st*`` compatibility
    properties, kept so that code written against pre-4.10 versions of
    :class:`~pyweatherfiles.tmy.TMYGenerator` keeps working transparently."""

    # --- BACKWARD COMPATIBILITY PROPERTIES ---
    # These properties exist solely so that code written against pre-4.10
    # versions of this class (which used the ``validation_st2_*``/
    # ``validation_st3_*``/``validation_st4_*`` attribute names) keeps
    # working transparently: reading/writing them redirects to the current
    # ``validation_step*`` attribute described in the class docstring.

    @property
    def validation_st2_df_fs_ranking_by_month(self):
        """dict[int, pandas.DataFrame]: Deprecated alias for
        :attr:`validation_step2_fs_ranking_by_month`."""
        return self.validation_step2_fs_ranking_by_month

    @validation_st2_df_fs_ranking_by_month.setter
    def validation_st2_df_fs_ranking_by_month(self, value):
        self.validation_step2_fs_ranking_by_month = value

    @property
    def validation_st2_summary_fs_ranking(self):
        """pandas.DataFrame or None: Deprecated alias for
        :attr:`validation_step3_proximity_ranking` (kept under its
        historical name; the top-5 candidates it stores were already in
        proximity order in the original implementation)."""
        # Maps to proximity ranking since originally it stored the top 5 in proximity order
        return self.validation_step3_proximity_ranking

    @validation_st2_summary_fs_ranking.setter
    def validation_st2_summary_fs_ranking(self, value):
        self.validation_step3_proximity_ranking = value

    @property
    def validation_st3_df_persistence_decision(self):
        """pandas.DataFrame or dict: Deprecated alias for
        :attr:`validation_step4_df_persistence_decision`."""
        return self.validation_step4_df_persistence_decision

    @validation_st3_df_persistence_decision.setter
    def validation_st3_df_persistence_decision(self, value):
        self.validation_step4_df_persistence_decision = value

    @property
    def validation_st3_persistence_sequential_details(self):
        """dict[int, pandas.DataFrame] or None: Deprecated alias for
        :attr:`validation_step4_persistence_sequential_details`."""
        return self.validation_step4_persistence_sequential_details

    @validation_st3_persistence_sequential_details.setter
    def validation_st3_persistence_sequential_details(self, value):
        self.validation_step4_persistence_sequential_details = value

    @property
    def validation_st3_persistence_score_details(self):
        """dict[int, pandas.DataFrame] or None: Deprecated alias for
        :attr:`validation_step4_persistence_score_details`."""
        return self.validation_step4_persistence_score_details

    @validation_st3_persistence_score_details.setter
    def validation_st3_persistence_score_details(self, value):
        self.validation_step4_persistence_score_details = value

    @property
    def validation_st4_df_tmy_composition(self):
        """pandas.DataFrame or None: Deprecated alias for
        :attr:`validation_step6_tmy_composition`."""
        return self.validation_step6_tmy_composition

    @validation_st4_df_tmy_composition.setter
    def validation_st4_df_tmy_composition(self, value):
        self.validation_step6_tmy_composition = value

    # --- DEPRECATED PUBLIC WORKFLOWS ---

    def step_1_load_and_prepare_data(self):
        """[DEPRECATED] Use sandia_step_1_load_and_prepare() instead."""
        warnings.warn("step_1_load_and_prepare_data() is deprecated. Use sandia_step_1_load_and_prepare() instead.", DeprecationWarning, stacklevel=2)
        return self.sandia_step_1_load_and_prepare()

    def step_2_select_candidate_months(self, completeness_threshold=None):
        """[DEPRECATED] Use sandia_step_2 and sandia_step_3 instead."""
        warnings.warn("step_2_select_candidate_months() is deprecated. Use sandia_step_2_select_candidates_fs() and sandia_step_3_proximity_ranking() instead.", DeprecationWarning, stacklevel=2)
        self.sandia_step_2_select_candidates_fs(completeness_threshold=completeness_threshold)
        self.sandia_step_3_proximity_ranking()
        return self

    def step_3_apply_persistence(self, thresholds=(0.33, 0.67), min_run_length=1, persistence_weights=None, persistence_method='score', zero_run_method='eliminate_worst_ranked'):
        """[DEPRECATED] Use sandia_step_4_and_5_apply_persistence() instead."""
        warnings.warn("step_3_apply_persistence() is deprecated. Use sandia_step_4_and_5_apply_persistence() instead.", DeprecationWarning, stacklevel=2)
        return self.sandia_step_4_and_5_apply_persistence(thresholds, min_run_length, persistence_weights, persistence_method, zero_run_method)

    def step_4_create_and_smooth_tmy(self, hours=6, s_factor='auto'):
        """[DEPRECATED] Use sandia_step_6 and sandia_step_7 instead."""
        warnings.warn("step_4_create_and_smooth_tmy() is deprecated. Use sandia_step_6_assemble_tmy() and sandia_step_7_smooth_junctions() instead.", DeprecationWarning, stacklevel=2)
        self.sandia_step_6_assemble_tmy()
        self.sandia_step_7_smooth_junctions(hours=hours, s_factor=s_factor)
        return self

    def _smooth_tmy_curve_fitting(self, hours=6, s_factor='auto'):
        """
        Part of Step 6: Smooths the TMY discontinuities using curve fitting (spline).
        """
        if self.tmy_raw is None: raise RuntimeError("Raw TMY not generated yet. Run 'step_4_create_and_smooth_tmy()' first.")

