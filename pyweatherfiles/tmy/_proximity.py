# -*- coding: utf-8 -*-
"""
tmy/_proximity.py
==================

:class:`_ProximityMixin` — **Step 3** of the Sandia TMY workflow: proximity
re-ranking of the FS candidates (Sawaqed et al., 2005) via
:meth:`sandia_step_3_proximity_ranking` and its private helpers.

Extracted from the former monolithic ``tmy.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6). See ``pyweatherfiles/tmy/__init__.py``
for the package-level overview.
"""

import warnings

import pandas as pd
import numpy as np


class _ProximityMixin:
    """Step 3: Proximity Ranking (Sawaqed et al. 2005)."""

    # --- PRIVATE METHODS (INTERNAL LOGIC) ---

    def _validate_proximity_normalization_method(self, normalization_method):
        """Validates and normalizes the proximity normalization method string."""
        if normalization_method is None:
            normalization_method = 'std'

        method = str(normalization_method).strip().lower()
        if method == 'sawaqed':
            warnings.warn("'sawaqed' is deprecated for proximity normalization. Use 'weighted' instead.", DeprecationWarning, stacklevel=3)
            method = 'weighted'

        valid_methods = {'std', 'long_term_mean', 'range', 'weighted', 'no_normalization'}
        if method not in valid_methods:
            raise ValueError(f"Invalid normalization_method '{normalization_method}'. Must be one of {sorted(valid_methods)}")
        return method

    def _resolve_proximity_weights(self, normalization_weights):
        """Returns validated proximity weights for the 'weighted' proximity method."""
        default_weights = {
            't_mean': 0.30,
            't_median': 0.20,
            'ghi_mean': 0.30,
            'ghi_median': 0.20
        }

        if normalization_weights is None:
            return default_weights

        expected_keys = set(default_weights.keys())
        provided_keys = set(normalization_weights.keys())

        missing_keys = expected_keys - provided_keys
        extra_keys = provided_keys - expected_keys
        if missing_keys or extra_keys:
            raise ValueError(
                "Invalid normalization_weights keys. "
                f"Expected exactly {sorted(expected_keys)}, got {sorted(provided_keys)}."
            )

        resolved = {k: float(v) for k, v in normalization_weights.items()}
        if any(v < 0 for v in resolved.values()):
            raise ValueError("All normalization_weights values must be >= 0.")

        total = sum(resolved.values())
        if not np.isclose(total, 1.0, atol=1e-9):
            raise ValueError(f"normalization_weights must sum to 1.0. Current sum is {total}.")

        return resolved

    def _safe_denominator(self, value):
        """Protects proximity normalization from zero/NaN denominators."""
        if pd.isna(value) or value == 0:
            return 1.0
        return float(value)

    def _run_proximity_ranking(self, normalization_method='std', normalization_weights=None):
        """
        Step 3: Proximity Ranking (Sawaqed et al. 2005)
        Re-orders the top 5 candidates based on the deviation of their monthly
        mean and median Temperature and GHI from the long-term history.
        """
        method = self._validate_proximity_normalization_method(normalization_method)
        weights = self._resolve_proximity_weights(normalization_weights) if method == 'weighted' else None

        print(f"Step 3: Applying Proximity Ranking to re-order top 5 candidates (method='{method}')...")
        if method == 'weighted':
            print(f"  Proximity weights: {weights}")

        # Calculate Long-Term Stats for all months first for efficiency
        # We need Mean and Median for T_air and GHI

        # Determine variable names in df_daily
        t_col = 'T_air' if 'T_air' in self.df_daily.columns else 'T_air_mean'
        ghi_col = 'GHI' if 'GHI' in self.df_daily.columns else 'GHI_sum'

        if t_col not in self.df_daily.columns or ghi_col not in self.df_daily.columns:
            print(f"  WARNING: Proximity ranking requires Temp and GHI. Found {self.df_daily.columns.tolist()}. Skipping re-ordering.")
            self.candidate_months = self.candidate_months_pre_proximity
            if self.save_validation_dfs:
                self.validation_step3_proximity_ranking = self.validation_step2_summary_fs_ranking
            return

        candidate_months = {}

        for month in range(1, 13):
            candidates = self.candidate_months_pre_proximity.get(month, [])
            if not candidates: continue

            # Long-term stats for the month (using all available years in df_daily)
            lt_data_month = self.df_daily[self.df_daily.index.month == month]

            lt_t_mean = lt_data_month[t_col].mean()
            lt_t_median = lt_data_month[t_col].median()
            lt_t_std = lt_data_month[t_col].std()

            lt_ghi_mean = lt_data_month[ghi_col].mean()
            lt_ghi_median = lt_data_month[ghi_col].median()
            lt_ghi_std = lt_data_month[ghi_col].std()
            lt_t_range = lt_data_month[t_col].max() - lt_data_month[t_col].min()
            lt_ghi_range = lt_data_month[ghi_col].max() - lt_data_month[ghi_col].min()

            if method == 'std' or method == 'weighted':
                den_t = self._safe_denominator(lt_t_std)
                den_ghi = self._safe_denominator(lt_ghi_std)
            elif method == 'long_term_mean':
                den_t = self._safe_denominator(abs(lt_t_mean))
                den_ghi = self._safe_denominator(abs(lt_ghi_mean))
            elif method == 'range':
                den_t = self._safe_denominator(lt_t_range)
                den_ghi = self._safe_denominator(lt_ghi_range)
            else:  # 'no_normalization'
                den_t = 1.0
                den_ghi = 1.0

            ranking_details = []

            for year in candidates:
                cand_data = lt_data_month[lt_data_month.index.year == year]

                if cand_data.empty:
                    ranking_details.append({'Year': year, 'Max_Error': np.inf})
                    continue

                # Candidate stats
                c_t_mean = cand_data[t_col].mean()
                c_t_median = cand_data[t_col].median()
                c_ghi_mean = cand_data[ghi_col].mean()
                c_ghi_median = cand_data[ghi_col].median()

                # Deviations (Absolute Errors)
                err_t_mean = abs(c_t_mean - lt_t_mean)
                err_t_median = abs(c_t_median - lt_t_median)
                err_ghi_mean = abs(c_ghi_mean - lt_ghi_mean)
                err_ghi_median = abs(c_ghi_median - lt_ghi_median)

                # Normalized deviations according to the selected denominator method.
                n_err_t_mean = err_t_mean / den_t
                n_err_t_median = err_t_median / den_t
                n_err_ghi_mean = err_ghi_mean / den_ghi
                n_err_ghi_median = err_ghi_median / den_ghi

                if method == 'weighted':
                    weighted_score = (
                        weights['t_mean'] * n_err_t_mean +
                        weights['t_median'] * n_err_t_median +
                        weights['ghi_mean'] * n_err_ghi_mean +
                        weights['ghi_median'] * n_err_ghi_median
                    )
                    proximity_score = weighted_score
                else:
                    weighted_score = np.nan
                    proximity_score = max(n_err_t_mean, n_err_t_median, n_err_ghi_mean, n_err_ghi_median)

                ranking_details.append({
                    'Year': year,
                    'Max_Error': proximity_score,
                    'Proximity_Score': proximity_score,
                    'Proximity_Method': method,
                    'Den_T': den_t,
                    'Den_GHI': den_ghi,
                    'Weighted_Score': weighted_score,
                    'Raw_Err_T_Mean': err_t_mean,
                    'Raw_Err_T_Med': err_t_median,
                    'Raw_Err_GHI_Mean': err_ghi_mean,
                    'Raw_Err_GHI_Med': err_ghi_median,
                    'Norm_Err_T_Mean': n_err_t_mean,
                    'Norm_Err_T_Med': n_err_t_median,
                    'Norm_Err_GHI_Mean': n_err_ghi_mean,
                    'Norm_Err_GHI_Med': n_err_ghi_median
                })

            # Sort candidates by proximity score (ascending)
            # Rank 1 = Lowest Max Error
            sorted_details = sorted(ranking_details, key=lambda x: x['Max_Error'])

            # Update the candidate list for this month with the new order
            sorted_candidates = [item['Year'] for item in sorted_details]
            candidate_months[month] = sorted_candidates

            # Update fs_ranking_results to reflect new order and store ranking metric
            # We preserve the FS score but re-order the list
            current_fs_results = self.fs_ranking_results.get(month, [])
            new_fs_results = []
            for item in sorted_details:
                year = item['Year']
                # Find original FS data
                orig_data = next((x for x in current_fs_results if x['year'] == year), {'Total_W_FS': np.nan})
                new_entry = orig_data.copy()
                new_entry.update(item) # Add the error stats
                new_fs_results.append(new_entry)

            self.fs_ranking_results[month] = new_fs_results

            print(f"  Month {month}: Re-ordered by Proximity -> {sorted_candidates}")

        self.candidate_months = candidate_months

        if self.save_validation_dfs:
            self._generate_proximity_summary()

    def _generate_proximity_summary(self):
        """Generates the summary dataframe of Top 5 candidates ordered by Proximity."""
        all_months_data = []
        for month in range(1, 13):
            month_name = pd.to_datetime(f'2000-{month}-01').strftime('%B')
            top_5_data = self.fs_ranking_results.get(month, [])
            for rank, item in enumerate(top_5_data):
                row = {
                    'Month': month_name,
                    'Year': item['Year'],
                    'Prox_Rank': rank + 1,
                    'Max_Error': item.get('Max_Error', np.nan),
                    'Proximity_Score': item.get('Proximity_Score', np.nan),
                    'Proximity_Method': item.get('Proximity_Method', np.nan),
                    'Den_T': item.get('Den_T', np.nan),
                    'Den_GHI': item.get('Den_GHI', np.nan),
                    'Weighted_Score': item.get('Weighted_Score', np.nan),
                    'Raw_Err_T_Mean': item.get('Raw_Err_T_Mean', np.nan),
                    'Raw_Err_T_Med': item.get('Raw_Err_T_Med', np.nan),
                    'Raw_Err_GHI_Mean': item.get('Raw_Err_GHI_Mean', np.nan),
                    'Raw_Err_GHI_Med': item.get('Raw_Err_GHI_Med', np.nan),
                    'Norm_Err_T_Mean': item.get('Norm_Err_T_Mean', np.nan),
                    'Norm_Err_T_Med': item.get('Norm_Err_T_Med', np.nan),
                    'Norm_Err_GHI_Mean': item.get('Norm_Err_GHI_Mean', np.nan),
                    'Norm_Err_GHI_Med': item.get('Norm_Err_GHI_Med', np.nan),
                    'Total_W_FS': item.get('Total_W_FS', np.nan)
                }
                all_months_data.append(row)

        if all_months_data:
            df_summary = pd.DataFrame(all_months_data).set_index(['Month', 'Year'])
            self.validation_step3_proximity_ranking = df_summary

    # --- PUBLIC WORKFLOWS ---

    def sandia_step_3_proximity_ranking(self, normalization_method='std', normalization_weights=None):
        """
        **Step 3** of the Sandia TMY workflow (Sawaqed, Zurigat & Al-Hinai,
        2005): re-orders the 5 FS candidates from Step 2 by how close their
        monthly mean/median temperature and GHI are to the long-term
        statistics, using a normalised, configurable proximity score (see
        the module-level formulas in the package README, section 3.4).
        Populates :attr:`candidate_months` with the re-ordered candidate
        lists (ascending by proximity score, best first).

        Args:
            normalization_method (str): One of 'std' (default), 'long_term_mean',
                'range', 'weighted', or 'no_normalization'. The deprecated
                alias ``'sawaqed'`` is still accepted and mapped internally
                to ``'weighted'`` (emits a ``DeprecationWarning``).
            normalization_weights (dict, optional): Used only when
                normalization_method='weighted'. Expected keys:
                't_mean', 't_median', 'ghi_mean', 'ghi_median'.
                Values must be non-negative and sum to 1.

        Returns:
            TMYGenerator: ``self``, to allow method chaining.

        Raises:
            RuntimeError: If :meth:`sandia_step_2_select_candidates_fs` has
                not been run yet.
            ValueError: If *normalization_method* is invalid, or if
                *normalization_weights* has invalid keys/values.

        Example:
            >>> gen.sandia_step_2_select_candidates_fs()  # doctest: +SKIP
            >>> gen.sandia_step_3_proximity_ranking(normalization_method="std")  # doctest: +SKIP
        """
        if self.candidate_months_pre_proximity is None: raise RuntimeError("Run sandia_step_2_select_candidates_fs() first.")
        self._run_proximity_ranking(
            normalization_method=normalization_method,
            normalization_weights=normalization_weights
        )
        return self

