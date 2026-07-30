# -*- coding: utf-8 -*-
"""
tmy/_persistence.py
=====================

:class:`_PersistenceMixin` — **Steps 4 & 5** of the Sandia TMY workflow:
persistence-run filtering (either the deterministic ``'sequential'``
exclusion process or the weighted ``'score'`` method) and final month
selection, via :meth:`sandia_step_4_and_5_apply_persistence` and its
private helpers.

Extracted from the former monolithic ``tmy.py`` in Fase 5 of
``INFORME_REVISION_GENERAL.md`` (§6). See ``pyweatherfiles/tmy/__init__.py``
for the package-level overview.
"""

import pandas as pd
import numpy as np


class _PersistenceMixin:
    """Steps 4 & 5: Persistence filtering and final month selection."""

    # --- PRIVATE METHODS (INTERNAL LOGIC) ---

    def _calculate_run_stats(self, series, upper_threshold, lower_threshold, min_run_length):
        """Calculates the frequency and maximum duration of persistence runs."""
        is_above = series > upper_threshold
        is_below = series < lower_threshold

        def get_run_info(condition_series):
            if not condition_series.any():
                return 0, 0
            groups = (condition_series != condition_series.shift()).cumsum()[condition_series]
            run_lengths = groups.value_counts()
            valid_run_lengths = run_lengths[run_lengths >= min_run_length]
            num_runs = len(valid_run_lengths)
            max_len = valid_run_lengths.max() if num_runs > 0 else 0
            return num_runs, int(max_len)

        above_freq, above_dur = get_run_info(is_above)
        below_freq, below_dur = get_run_info(is_below)
        total_freq = above_freq + below_freq
        max_dur = max(above_dur, below_dur)
        return total_freq, max_dur

    def _apply_persistence_scoring(self, persistence_weights):
        """Applies the persistence criteria using a scoring system."""
        print("\nApplying persistence criteria based on scoring...")
        selected_months = {}
        persistence_decisions_list = []
        if self.save_validation_dfs:
            self.validation_step4_persistence_score_details = {}
            self.validation_step4_persistence_sequential_details = None

        for month in range(1, 13):
            candidates = self.candidate_months.get(month, [])
            if not candidates: continue

            long_term_month_data = self.df_daily[self.df_daily.index.month == month]
            if long_term_month_data.empty: continue

            lower_p, upper_p = self.persistence_thresholds

            # Helper to get column
            t_col = 'T_air' if 'T_air' in long_term_month_data.columns else 'T_air_mean'
            ghi_col = 'GHI' if 'GHI' in long_term_month_data.columns else 'GHI_sum'

            if t_col not in long_term_month_data.columns or ghi_col not in long_term_month_data.columns:
                print(f"  Warning: Persistence analysis requires Temp and GHI. Found {long_term_month_data.columns.tolist()[:5]}... Skipping.")
                continue

            t_air_upper, t_air_lower = long_term_month_data[t_col].quantile([upper_p, lower_p])
            ghi_lower = long_term_month_data[ghi_col].quantile(lower_p)

            candidate_scores = []
            for year in candidates:
                candidate_data = self.df_daily[(self.df_daily.index.month == month) & (self.df_daily.index.year == year)]
                if candidate_data.empty: continue

                fs_stats = next((item for item in self.fs_ranking_results.get(month, []) if item['year'] == year), None)
                if not fs_stats: continue
                total_w_fs = fs_stats['Total_W_FS']

                t_air_freq, t_air_dur = self._calculate_run_stats(candidate_data[t_col], t_air_upper, t_air_lower, self.min_run_length)
                ghi_freq, ghi_dur = self._calculate_run_stats(candidate_data[ghi_col], np.inf, ghi_lower, self.min_run_length)

                w_t_dur = persistence_weights['w_t_longest_run']
                w_t_freq = persistence_weights['w_t_total_runs']
                w_ghi_dur = persistence_weights['w_ghi_longest_run']
                w_ghi_freq = persistence_weights['w_ghi_total_runs']

                prod_t_dur = w_t_dur * t_air_dur
                prod_t_freq = w_t_freq * t_air_freq
                prod_ghi_dur = w_ghi_dur * ghi_dur
                prod_ghi_freq = w_ghi_freq * ghi_freq

                score = total_w_fs + prod_t_dur + prod_t_freq + prod_ghi_dur + prod_ghi_freq

                candidate_scores.append({
                    'Year': year, 
                    'WT_FS': total_w_fs,
                    'T_Max_Len': t_air_dur, 'W_T_Max_Len': w_t_dur, 'Prod_T_Max_Len': prod_t_dur,
                    'T_TotalRuns': t_air_freq, 'W_T_TotalRuns': w_t_freq, 'Prod_T_TotalRuns': prod_t_freq,
                    'GHI_Max_Len': ghi_dur, 'W_GHI_Max_Len': w_ghi_dur, 'Prod_GHI_Max_Len': prod_ghi_dur,
                    'GHI_TotalRuns': ghi_freq, 'W_GHI_TotalRuns': w_ghi_freq, 'Prod_GHI_TotalRuns': prod_ghi_freq,
                    'Score': score
                })

            if not candidate_scores: continue

            df_decision = pd.DataFrame(candidate_scores).sort_values('Score').reset_index(drop=True)
            df_decision['Rank'] = df_decision.index + 1
            df_decision['Year'] = df_decision['Year'].astype(int)

            if self.save_validation_dfs:
                self.validation_step4_persistence_score_details[month] = df_decision.copy()
                
                # Also populate the old fallback for backward compatibility if needed, 
                # but adding 'Month' column as expected by validate_persistence_selection fallback

                df_for_concat = df_decision.copy()
                df_for_concat.insert(0, 'Month', month)
                persistence_decisions_list.append(df_for_concat)

            best_choice = df_decision.iloc[0]['Year'].astype(int)
            selected_months[month] = best_choice
            print(f"  Month {month}: Selected Year -> {int(best_choice)} (Score: {df_decision.iloc[0]['Score']:.4f})")

        if self.save_validation_dfs and persistence_decisions_list:
            self.validation_step4_df_persistence_decision = pd.concat(persistence_decisions_list, ignore_index=True)

        self.selected_months = selected_months

    def _apply_persistence_sequential_exclusion(self, zero_run_method='eliminate_worst_ranked'):
        """
        Applies the persistence criteria using the sequential iterative exclusion method.
        
        Args:
             zero_run_method (str): Methodology for handling candidates with zero runs in Pass 3.
                 Options: 'eliminate_worst_ranked' (default), 'eliminate_all', 'eliminate_none'.
        
        PERSISTENCE PROCESS (Step 4 & 5 - Sequential Exclusion):
        ========================================================
        
        Start from the 5 candidate years already ranked by Proximity in Step 3.
        
        STEP 4: COMPUTE PERSISTENCE INDICATORS & FILTER
        -----------------------------------------------
        For mean dry-bulb temperature:
            - consecutive days above the 67th percentile (warm runs)
            - consecutive days below the 33rd percentile (cool runs)
        For GHI:
            - consecutive days below the 33rd percentile (low-radiation runs)
        
        For each candidate month, calculate:
            - Number of runs (frequency)
            - Longest run length
        
        EXCLUSION CRITERIA (Step 4 continued):
        --------------------------------------
        The exclusion criteria are applied sequentially in a single pass (Pass 1, 2, 3).
        
        PASS 1: NUMBER OF RUNS CRITERION
           a. If all months have no runs → select the first month in ranking list
           b. If all months have equal number of runs → check length of runs:
              i.  If unequal run lengths → exclude the one with the longest run
              ii. If equal run lengths → exclude the last one in the list
           c. If number of runs are not equal:
              - Exclude the one with largest number of runs
              - Modified rule: eliminate only if it has more runs than all others
              - If tie for max runs → eliminate the worst-ranked among them
        
        PASS 2: RUNS LENGTH CRITERION (if Pass 1 survivors > 1)
           a. If unequal run length → exclude the longest run month
           b. If equal run length → check number of runs:
              i.  If equal number of runs → exclude the last one in the list
              ii. If not equal → exclude the one with the largest number of runs
        
        PASS 3: ZERO-RUN CRITERION (if Pass 2 survivors > 1)
           Inspect remaining months for number of runs.
           Behavior depends on `zero_run_method`:
           - 'eliminate_worst_ranked': Exclude ONE candidate (the one with worst Proximity Rank).
           - 'eliminate_all': Exclude ALL candidates with zero runs.
           - 'eliminate_none': Do nothing.
        
        STEP 5: FINAL SELECTION
        -----------------------
        Select the highest Proximity-ranked candidate among survivors.
        """
        print("\nApplying persistence criteria (Step 4) and Final Selection (Step 5)...")
        selected_months = {}
        if self.save_validation_dfs:
            self.validation_step4_persistence_sequential_details = {}
            self.validation_step4_persistence_score_details = None
            self.validation_step4_df_persistence_decision = None 

        for month in range(1, 13):
            candidates_years = self.candidate_months.get(month, [])
            if not candidates_years: continue

            # candidates_years is already sorted by FS (best first) - this is our starting point
            month_decisions = {y: "" for y in candidates_years}
            month_stats_list = []
            
            long_term_month_data = self.df_daily[self.df_daily.index.month == month]
            if long_term_month_data.empty: continue

            # ═══════════════════════════════════════════════════════════════════
            # STEP 4 (Part A): COMPUTE PERSISTENCE INDICATORS
            # ═══════════════════════════════════════════════════════════════════
            
            # Define thresholds for runs
            lower_p, upper_p = self.persistence_thresholds  # Default: 33rd and 67th percentiles
            
            t_col = 'T_air' if 'T_air' in long_term_month_data.columns else 'T_air_mean'
            ghi_col = 'GHI' if 'GHI' in long_term_month_data.columns else 'GHI_sum'

            if t_col not in long_term_month_data.columns or ghi_col not in long_term_month_data.columns:
                 print(f"  Warning: Persistence analysis requires Temp and GHI. Skipping Month {month}.")
                 selected_months[month] = candidates_years[0]
                 continue
            
            # Calculate quantiles for the entire long-term month data
            # For dry-bulb temperature: 67th percentile (warm runs) and 33rd percentile (cool runs)
            t_air_upper = long_term_month_data[t_col].quantile(upper_p)  # 67th percentile
            t_air_lower = long_term_month_data[t_col].quantile(lower_p)  # 33rd percentile
            # For GHI: 33rd percentile (low-radiation runs)
            ghi_lower = long_term_month_data[ghi_col].quantile(lower_p)  # 33rd percentile

            # Build initial persistence statistics for all candidates
            # For each candidate month, calculate:
            #   - Number of runs (frequency)
            #   - Longest run length
            month_stats_list = []
            for rank, year in enumerate(candidates_years):
                candidate_data = self.df_daily[(self.df_daily.index.month == month) & (self.df_daily.index.year == year)]
                if candidate_data.empty: continue
                
                # Temperature runs: consecutive days above 67th OR below 33rd percentile
                t_freq, t_dur = self._calculate_run_stats(candidate_data[t_col], t_air_upper, t_air_lower, self.min_run_length)
                # GHI runs: consecutive days below 33rd percentile
                ghi_freq, ghi_dur = self._calculate_run_stats(candidate_data[ghi_col], np.inf, ghi_lower, self.min_run_length)
                
                # Aggregate metrics
                total_runs = t_freq + ghi_freq        # Total number of runs
                max_run_len = max(t_dur, ghi_dur)     # Longest run length
                
                # Get FS value for reference
                fs_val_ranking = next((item for item in self.fs_ranking_results.get(month, []) if item['year'] == year), None)
                fs_val = fs_val_ranking['Total_W_FS'] if fs_val_ranking else np.nan

                month_stats_list.append({
                    'Year': year,
                    'Original_Rank': rank,  # 0 = best FS rank
                    'Total_Runs': total_runs,
                    'Max_Run_Len': max_run_len,
                    'FS': fs_val
                })


            
            # ═══════════════════════════════════════════════════════════════════
            # STEP 4 (Part B): SINGLE-PASS SEQUENTIAL EXCLUSION
            # ═══════════════════════════════════════════════════════════════════
            
            survivors = month_stats_list.copy()
            month_decisions = {s['Year']: "" for s in survivors}
            
            # Helper to find candidate with worst Proximity Rank among a list
            def get_worst_ranked(cands):
                return sorted(cands, key=lambda x: x['Original_Rank'])[-1]

            # ───────────────────────────────────────────────────────────────
            # PASS 1: NUMBER OF RUNS CRITERION
            # ───────────────────────────────────────────────────────────────
            # Logic:
            # Rule 1a: If all candidates have 0 runs -> Select Rank 1 immediately.
            # Rule 1b: If all candidates have EQUAL runs -> Check run lengths.
            #    Rule 1b.i: Unequal run lengths -> Exclude Longest Run.
            #    Rule 1b.ii: Equal run lengths -> Exclude Last in List (Worst Rank).
            # Rule 1c: Unequal runs -> Exclude Max Runs.
            
            runs_values = [s['Total_Runs'] for s in survivors]
            max_runs = max(runs_values)
            min_runs = min(runs_values)
            
            excluded_p1 = None
            
            if max_runs == 0:
                # Rule 1a: Immediate selection
                top_cand = sorted(survivors, key=lambda x: x['Original_Rank'])[0]
                month_decisions[top_cand['Year']] = "SELECTED (Rule 1a: No runs)"
                selected_months[month] = top_cand['Year']
                
                # Save details and continue to next month
                if self.save_validation_dfs:
                    self._save_persistence_details(month, month_stats_list, month_decisions)
                continue
                
            elif max_runs == min_runs:
                # Rule 1b: Equal runs
                max_lens = [s['Max_Run_Len'] for s in survivors]
                if max(max_lens) != min(max_lens):
                    # Rule 1b.i: Unequal lengths -> Exclude longest run
                    # Tie-breaker for longest run: Worst Rank (implied/common sense)
                    target_len = max(max_lens)
                    cands_target = [s for s in survivors if s['Max_Run_Len'] == target_len]
                    to_exclude = get_worst_ranked(cands_target)
                    excluded_p1 = to_exclude
                    month_decisions[to_exclude['Year']] = "Excluded Pass 1 (Rule 1b.i: Longest Run)"
                else:
                    # Rule 1b.ii: Equal lengths -> Exclude last in list
                    to_exclude = get_worst_ranked(survivors)
                    excluded_p1 = to_exclude
                    month_decisions[to_exclude['Year']] = "Excluded Pass 1 (Rule 1b.ii: Last in list)"
            else:
                # Rule 1c: Unequal runs -> Exclude Max Runs
                # Tie-breaker for max runs: Worst Rank
                cands_target = [s for s in survivors if s['Total_Runs'] == max_runs]
                to_exclude = get_worst_ranked(cands_target)
                excluded_p1 = to_exclude
                month_decisions[to_exclude['Year']] = "Excluded Pass 1 (Rule 1c: Max Runs)"

            if excluded_p1:
                survivors = [s for s in survivors if s['Year'] != excluded_p1['Year']]

            # ───────────────────────────────────────────────────────────────
            # PASS 2: LONGEST RUN LENGTH CRITERION
            # ───────────────────────────────────────────────────────────────
            # Logic:
            # Rule 2a: Unequal run lengths -> Exclude Longest Run Month.
            # Rule 2b: Equal run lengths -> Check number of runs.
            #    Rule 2b.i: Equal number of runs -> Exclude Last in List.
            #    Rule 2b.ii: Unequal number of runs -> Exclude Max Runs.

            excluded_p2 = None
            lens = [s['Max_Run_Len'] for s in survivors]
            if not lens: pass # Safety
            else:
                max_len = max(lens)
                min_len = min(lens)
                
                if max_len != min_len:
                    # Rule 2a: Unequal run lengths -> Exclude longest run
                    # Tie-breaker: Max Runs (from user prompt) then Worst Rank
                    cands_target = [s for s in survivors if s['Max_Run_Len'] == max_len]
                    # Sort primarily by Runs (desc), then by Rank (desc)
                    to_exclude = sorted(cands_target, key=lambda x: (x['Total_Runs'], x['Original_Rank']))[-1]
                    excluded_p2 = to_exclude
                    month_decisions[to_exclude['Year']] = "Excluded Pass 2 (Rule 2a: Longest Run)"
                else:
                    # Rule 2b: Equal run lengths
                    runs = [s['Total_Runs'] for s in survivors]
                    if max(runs) == min(runs):
                         # Rule 2b.i: Equal runs -> Exclude Last in List
                         to_exclude = get_worst_ranked(survivors)
                         excluded_p2 = to_exclude
                         month_decisions[to_exclude['Year']] = "Excluded Pass 2 (Rule 2b.i: Equal runs, last in list)"
                    else:
                         # Rule 2b.ii: Unequal runs -> Exclude Max Runs
                         target_runs = max(runs)
                         cands_target = [s for s in survivors if s['Total_Runs'] == target_runs]
                         to_exclude = get_worst_ranked(cands_target)
                         excluded_p2 = to_exclude
                         month_decisions[to_exclude['Year']] = "Excluded Pass 2 (Rule 2b.ii: Max Runs)"

            if excluded_p2:
                survivors = [s for s in survivors if s['Year'] != excluded_p2['Year']]

            # ───────────────────────────────────────────────────────────────
            # PASS 3: ZERO-RUN CRITERION
            # ───────────────────────────────────────────────────────────────
            # Logic: If exists, eliminate based on `zero_run_method`.
            
            zero_run_cands = [s for s in survivors if s['Total_Runs'] == 0]
            
            if zero_run_cands:
                if zero_run_method == 'eliminate_none':
                    pass # Do nothing
                
                elif zero_run_method == 'eliminate_all':
                     # Eliminate ALL candidates with zero runs
                     for cand in zero_run_cands:
                         month_decisions[cand['Year']] = "Excluded Pass 3 (Zero Run - All)"
                     
                     survivors = [s for s in survivors if s['Total_Runs'] > 0]
                     
                else: # 'eliminate_worst_ranked' (Default)
                    # Eliminate ONLY the worst-ranked candidate with 0 runs
                    to_exclude = get_worst_ranked(zero_run_cands)
                    month_decisions[to_exclude['Year']] = "Excluded Pass 3 (Zero Run - Worst Ranked)"
                    survivors = [s for s in survivors if s['Year'] != to_exclude['Year']]
            
            # ═══════════════════════════════════════════════════════════════════
            # STEP 5: FINAL SELECTION
            # ═══════════════════════════════════════════════════════════════════
            # Select the highest Proximity-ranked candidate among survivors (lowest Original_Rank index)
            
            if survivors:
                survivors.sort(key=lambda x: x['Original_Rank'])
                best_choice = survivors[0]['Year']
                selected_months[month] = best_choice
                month_decisions[best_choice] = "SELECTED TMY MONTH"
            else:
                # Fallback (should not happen with 5 candidates and 3 passes)
                print(f"  Warning: All candidates excluded for Month {month}. Selecting best Proximity Rank.")
                best_choice = candidates_years[0]
                selected_months[month] = best_choice
            
            if self.save_validation_dfs:
                self._save_persistence_details(month, month_stats_list, month_decisions)

        self.selected_months = selected_months

    def _save_persistence_details(self, month, stats_list, decisions):
        """Helper to save persistence details dataframe."""
        month_details = []
        for stat in stats_list:
            month_details.append({
                'Prox_Rank': stat['Original_Rank'] + 1,
                'Year': stat['Year'],
                'FS_Score': stat['FS'],
                'NumRuns': stat['Total_Runs'],
                'Max_run': stat['Max_Run_Len'],
                'Decision': decisions.get(stat['Year'], "")
            })
        df = pd.DataFrame(month_details).sort_values('Prox_Rank')
        self.validation_step4_persistence_sequential_details[month] = df

    def _select_months_by_fs_rank(self):
        """Selects months based purely on FS/Proximity rank, skipping persistence filtering (Step 4 & 5)."""
        print("\nSkipping persistence filtering. Selecting the best candidate by rank.")
        if self.candidate_months is None: raise RuntimeError("Run step_2_select_candidate_months() first.")
        self.selected_months = {month: candidates[0] for month, candidates in self.candidate_months.items() if candidates}

    def _generate_selected_months_summary(self):
        """Generates a simple dataframe showing the finally selected year for each month."""
        if self.selected_months is None: return
        df = pd.DataFrame(list(self.selected_months.items()), columns=['Month', 'Selected_Year'])
        self.validation_step5_selected_months_summary = df

    # --- PUBLIC WORKFLOWS ---

    def sandia_step_4_and_5_apply_persistence(self, thresholds=(0.33, 0.67), min_run_length=1, persistence_weights=None, persistence_method='score', zero_run_method='eliminate_worst_ranked'):
        """
        Step 4 & 5: Apply persistence criteria and Select Final Month.

        Args:
            thresholds (tuple): Lower and upper percentile thresholds to define runs.
            min_run_length (int): The minimum number of days for a period to be
                considered a persistence run.
            persistence_weights (dict, optional): A dictionary to customize the
                weights for persistence penalties (only for 'score' method).
            persistence_method (str): Method to use. 'score' (default) or 'sequential'.
            zero_run_method (str): Method for handling zero-run candidates (only for 'sequential').
                Options: 'eliminate_worst_ranked' (default), 'eliminate_all', 'eliminate_none'.

        Returns:
            TMYGenerator: ``self``, to allow method chaining.

        Raises:
            RuntimeError: If :meth:`sandia_step_3_proximity_ranking` has not
                been run yet.

        Example:
            >>> gen.sandia_step_3_proximity_ranking()  # doctest: +SKIP
            >>> gen.sandia_step_4_and_5_apply_persistence(persistence_method="sequential")  # doctest: +SKIP
        """
        if self.candidate_months is None: raise RuntimeError("Run sandia_step_3_proximity_ranking() first.")
        self.persistence_thresholds = thresholds
        self.min_run_length = min_run_length

        if persistence_method == 'sequential':
            self._apply_persistence_sequential_exclusion(zero_run_method=zero_run_method)
        else:
            # Default Score Method
            default_weights = {
                'w_t_longest_run': 0.002, 'w_t_total_runs': 0.001,
                'w_ghi_longest_run': 0.001, 'w_ghi_total_runs': 0.0005
            }

            final_weights = default_weights.copy()
            if persistence_weights:
                user_keys = set(persistence_weights.keys())
                valid_keys = set(final_weights.keys())
                invalid_keys = user_keys - valid_keys

                if invalid_keys:
                    print(f"\nWARNING: Found invalid keys in `persistence_weights`: {sorted(list(invalid_keys))}.")
                    print(f"These keys will be ignored. Valid keys are: {sorted(list(valid_keys))}")

                valid_user_weights = {k: v for k, v in persistence_weights.items() if k in valid_keys}
                final_weights.update(valid_user_weights)

            print("\nPersistence weights being used for the Score calculation:")
            print(final_weights)

            self._apply_persistence_scoring(final_weights)
        
        if self.save_validation_dfs:
            self._generate_selected_months_summary()
            
        return self

