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

- [x] **Should `sandia_step_7_smooth_junctions()` keep `s_factor=0.0` as its default?**
  - Context: `s_factor` is passed verbatim to `scipy.interpolate.UnivariateSpline` as `s`. With `s=0` the spline interpolates exactly, so the values written back into each junction window are identical (max |diff| ~1e-14) to the raw ones: Step 7 runs but is a no-op, `tmy_final == tmy_raw`, and `plot_smoothing_comparison()` shows two perfectly overlapping curves. With `s_factor=None` (SciPy's automatic criterion) the same synthetic case changes 126 hours by up to ~1.4 degC.
  - Related evidence or files: `pyweatherfiles/tmy/_assembly_smoothing.py` (`_apply_smoothing`, `sandia_step_7_smooth_junctions`), `pyweatherfiles/tmy/_plotting.py` (`plot_smoothing_comparison`), `docs/source/jupyter_notebooks/tutorial_pyweatherfiles_case_study_v01.ipynb` (Step 7 cells).
  - Next step: —
  - Resolution: **No.** The default is now `s_factor='auto'` (variance-normalized, unit-invariant: `s = 0.02 * n * var(y)` per variable), decided on 2026-09-19 — see [[decisions#D-004 — Step 7 smooths by default, with a variance-normalized `s_factor='auto'`|D-004]]. SciPy's `s=None` was rejected because it is unit-dependent (it flattened wind speed on real data). `s_factor=0.0` remains available as an explicit no-op.

_No other open questions have been recorded yet._
