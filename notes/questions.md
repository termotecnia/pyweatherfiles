---
aliases:
  - Open questions
tags:
  - pyweatherfiles
  - questions
---

# Open questions

Record issues that require research, validation, or a future decision. When resolved, link the evidence or decision and move the task to the canonical `TODO` if it needs formal tracking.

## Quick template

- [ ] **Question:**
  - Context:
  - Related evidence or files:
  - Next step:
  - Resolution:

---

- [ ] **Should Step 1 refuse (or flag) to interpolate across gaps longer than a given length?**
  - Context: `_load_and_prepare_real_data()` does `df.resample('h').mean().interpolate(method='linear')`, which rebuilds a strict, gap-free grid between the first and the last timestamp of the file. Any hole is filled, *including a whole absent calendar year*: the Seville case-study series has no 2020, and Step 1 reconstructs it as a linear ramp between 2019-12-31 23:00 and 2021-01-01 00:00. That synthetic year then has 100% "completeness" (no NaNs left), so Step 2's `completeness_threshold` cannot exclude it and it is counted among the candidate years. In practice its distribution is so far from the long-term one that the FS ranking never selects it, but that is luck rather than design.
  - Related evidence or files: `pyweatherfiles/tmy/_data_loading.py`, `pyweatherfiles/tmy/_validation.py` (`validate_step_1_data_loading`, `Interpolated_Years` column), `docs/source/jupyter_notebooks/tutorial_pyweatherfiles_case_study_v03.ipynb` (Step 1 cells).
  - Next step: decide between (a) status quo + the new `Interpolated_Years` report (done on 2026-09-20), (b) a `max_gap` argument that leaves longer holes as NaN so the completeness threshold can drop them, or (c) dropping years absent from `source_years` altogether unless explicitly requested.
  - Resolution: partially mitigated — the gap is now *reported* (`Interpolated_Years`, plus a console warning and a README caveat in §3.2), but not prevented. See [[decisions#D-005 — `validate_*`/`summarize_*` return DataFrames instead of printing them|D-005]].

- [x] **Should `sandia_step_7_smooth_junctions()` keep `s_factor=0.0` as its default?**
  - Context: `s_factor` is passed verbatim to `scipy.interpolate.UnivariateSpline` as `s`. With `s=0` the spline interpolates exactly, so the values written back into each junction window are identical (max |diff| ~1e-14) to the raw ones: Step 7 runs but is a no-op, `tmy_final == tmy_raw`, and `plot_smoothing_comparison()` shows two perfectly overlapping curves. With `s_factor=None` (SciPy's automatic criterion) the same synthetic case changes 126 hours by up to ~1.4 degC.
  - Related evidence or files: `pyweatherfiles/tmy/_assembly_smoothing.py` (`_apply_smoothing`, `sandia_step_7_smooth_junctions`), `pyweatherfiles/tmy/_plotting.py` (`plot_smoothing_comparison`), `docs/source/jupyter_notebooks/tutorial_pyweatherfiles_case_study_v01.ipynb` (Step 7 cells).
  - Next step: —
  - Resolution: **No.** The default is now `s_factor='auto'` (variance-normalized, unit-invariant: `s = 0.02 * n * var(y)` per variable), decided on 2026-09-19 — see [[decisions#D-004 — Step 7 smooths by default, with a variance-normalized `s_factor='auto'`|D-004]]. SciPy's `s=None` was rejected because it is unit-dependent (it flattened wind speed on real data). `s_factor=0.0` remains available as an explicit no-op.

