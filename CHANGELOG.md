# Changelog

## 1.0.0 — 2026-06-10

First public release.

### Features
- Tkinter GUI for Linear Combination Fitting (LCF) of 1-D data, plus a
  command-line interface (`pylcf-cli` / `python -m pylcf.cli`) on the same core.
- Data entry: paste from Excel; import `.xlsx`/`.xlsm` (shared-grid or XY-pairs);
  import a folder of Excel files; load two-column text files. References on
  different x-grids are interpolated onto the common overlap automatically.
- Fit modes: `convex` (sum = 1 fractions), `nnls`, `linear`.
- Normalization: `area` / `max` / `none`; optional fit window.
- Uncertainties: residual bootstrap with 95 % CIs; block bootstrap for
  correlated residuals.
- Drop-one F-test for component significance, reporting both the full-N and
  effective-N (autocorrelation-adjusted) p-value.
- Optional Δx (trapezoidal) weighting for sampling-invariant fits on uneven grids.
- Interactive overlay with sliders and live fractions / R-factor / R².
- Export: `.dat`/`.csv` (provenance header), `.xlsx`, `.json`,
  plot (`.png`/`.pdf`/`.svg`); "Copy results" to the clipboard. Exports
  include the bootstrap CIs, both F-test p-values and the residual
  autocorrelation. The x-axis column name in the exports is configurable.
- Keyboard shortcuts, tooltips, last-directory memory.
- Bilingual manuals (English + German).

The package is organised around a shared numeric core (`pylcf/core.py`); the GUI
(`pylcf.gui`) and the CLI (`pylcf.cli`) build on it, so their results are
identical by construction (with Δx weighting off).
