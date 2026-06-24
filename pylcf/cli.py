#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cli.py -- PyLCF command-line interface (built on :mod:`pylcf.core`).

Linear Combination Fitting of a measured 1-D data set from reference data sets,
without a GUI.  Run with ``pylcf-cli`` (installed) or ``python -m pylcf.cli``.

Because it uses the same numeric core as the GUI, the results are identical by
construction.  It also exposes the diagnostics that were added to the core
(moving-block bootstrap, drop-one F-test, Δx weighting).

Author:  Lukas Knauer (AG Schünemann, RPTU Kaiserslautern-Landau)
License: MIT
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from .core import (
    APP_VERSION, read_spectrum, read_xlsx_spectrum, prepare_arrays,
    run_fit, goodness_of_fit, _quadrature_weights, FitResult,
    export_data, build_json_payload, export_xlsx,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pylcf-cli",
        description="Linear combination fitting of a measured 1-D data set "
                    "(e.g. an NIS/NRVS spectrum) from reference data sets.",
        epilog="Notes: .xlsx/.xlsm inputs use the first two columns; "
               "--xcol/--ycol/--decimal-comma apply to text files only. "
               "Text files have no decimal auto-detection, so pass "
               "--decimal-comma for German-style numbers.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        fromfile_prefix_chars="@",
    )
    p.add_argument("--measured", required=True,
                   help="Path to the measured data set (text or .xlsx).")
    p.add_argument("--sub", nargs="+", required=True, metavar="FILE",
                   help="One or more reference files (text or .xlsx).")
    p.add_argument("--labels", nargs="+", metavar="NAME", default=None,
                   help="Optional labels for the references (default: file names).")
    p.add_argument("--mode",
                   choices=["convex", "nnls", "linear", "manual", "all"],
                   default="convex", help="Fitting mode.")
    p.add_argument("--weights", nargs="+", type=float, default=None,
                   help="Weights for --mode manual.")
    p.add_argument("--normalize", choices=["area", "max", "none"],
                   default="area",
                   help="Normalize each data set before fitting. 'area' makes "
                        "the convex weights true fractions.")
    p.add_argument("--xmin", type=float, default=None,
                   help="Lower limit of the fit window.")
    p.add_argument("--xmax", type=float, default=None,
                   help="Upper limit of the fit window.")
    p.add_argument("--xcol", type=int, default=0,
                   help="0-based column index of the x axis (text files).")
    p.add_argument("--ycol", type=int, default=1,
                   help="0-based column index of the y axis (text files).")
    p.add_argument("--decimal-comma", action="store_true",
                   help="Interpret ',' as the decimal separator (text files).")
    p.add_argument("--bootstrap", type=int, default=0, metavar="N",
                   help="Bootstrap error bars on the weights (N resamples; 0 = off).")
    p.add_argument("--block", action="store_true",
                   help="Use a moving-block bootstrap (for correlated residuals).")
    p.add_argument("--seed", type=int, default=0,
                   help="Random seed for the bootstrap.")
    p.add_argument("--ftest", action="store_true",
                   help="Drop-one-component F-test for each reference.")
    p.add_argument("--dx-weight", action="store_true",
                   help="Weight residuals by the local x spacing "
                        "(sampling-invariant fit).")
    p.add_argument("--out", default=None, metavar="PREFIX",
                   help="Output path prefix (default: <measured>_lcf).")
    p.add_argument("--xlabel", default="Energy (cm$^{-1}$)",
                   help="X-axis label for the plot.")
    p.add_argument("--ylabel", default="normalized intensity",
                   help="Y-axis label for the plot.")
    p.add_argument("--xname", default="energy",
                   help="Column name for the x axis in the .dat/Excel exports.")
    p.add_argument("--no-plot", action="store_true", help="Do not write a plot.")
    p.add_argument("--show", action="store_true",
                   help="Show the plot interactively in addition to saving it.")
    p.add_argument("--xlsx", action="store_true",
                   help="Also write an .xlsx workbook (summary + fit sheets; "
                        "needs pandas + openpyxl).")
    p.add_argument("--csv", action="store_true",
                   help="Write the data export comma-delimited (.csv) instead "
                        "of tab-delimited (.dat).")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress the console report and progress messages.")
    p.add_argument("--version", action="version", version=f"PyLCF {APP_VERSION}")
    return p


def _read_any(path, xcol, ycol, decimal_comma):
    """Read one data set; dispatch on the file extension."""
    if Path(path).suffix.lower() in (".xlsx", ".xlsm"):
        return read_xlsx_spectrum(path)
    return read_spectrum(path, xcol=xcol, ycol=ycol, decimal_comma=decimal_comma)


def _manual_fit(prep, weights, weighted: bool = False) -> FitResult:
    """Evaluate a user-supplied weight vector (``--mode manual``)."""
    if not weights:
        raise ValueError("--mode manual requires --weights.")
    coef = np.asarray(weights, float)
    if coef.size != prep.A.shape[1]:
        raise ValueError(f"--weights expects {prep.A.shape[1]} value(s), "
                         f"got {coef.size}.")
    wq = _quadrature_weights(prep.x) if weighted else None
    fit = prep.A @ coef
    gof = goodness_of_fit(prep.b, fit, n_params=coef.size, w=wq)
    return FitResult(mode="manual", labels=prep.labels, weights=coef, gof=gof,
                     weighted=weighted)


def _print_report(prep, results, measured_path) -> None:
    print(f"PyLCF {APP_VERSION} — linear combination fit")
    print(f"measured     : {measured_path}")
    print(f"fit window   : [{prep.window[0]:.4g}, {prep.window[1]:.4g}]   "
          f"points: {prep.x.size}   normalization: {prep.norm}")
    for res in results:
        tag = "  (Δx-weighted)" if res.weighted else ""
        print(f"\n[{res.mode}]{tag}")
        wsum = float(np.sum(res.weights))
        for i, lab in enumerate(res.labels):
            w = float(res.weights[i])
            frac = (100.0 * w / wsum) if wsum > 0 else float("nan")
            line = f"  {lab:<22s} {w: .4f}   ({frac:5.1f} %)"
            if res.wci is not None:
                lo, hi = res.wci[i]
                line += f"   CI[{lo:+.3f}, {hi:+.3f}]"
                if lo <= 0.0 <= hi:
                    line += " ~0"
            if res.fp is not None and np.isfinite(res.fp[i]):
                line += f"   p(F)={res.fp[i]:.2g}"
                if res.fp_eff is not None and np.isfinite(res.fp_eff[i]):
                    line += f" (eff.N {res.fp_eff[i]:.2g})"
            print(line)
        g = res.gof
        print(f"  R-factor = {g.r_factor:.4e}   RMSE = {g.rmse:.4e}   "
              f"R^2 = {g.r_squared:.5f}")
        if res.acf1 is not None:
            print(f"  residual lag-1 autocorrelation = {res.acf1:.3f}   "
                  f"effective N ~ {res.n_eff:.0f}")


def _make_plot(prep, res, out_png, xlabel, ylabel, show) -> None:
    import matplotlib
    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fit = prep.A @ res.weights
    fig, (ax1, ax2) = plt.subplots(
        2, 1, sharex=True, figsize=(8, 6),
        gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(prep.x, prep.b, "k-", lw=1.2, label="measured")
    ax1.plot(prep.x, fit, "r--", lw=1.5, label=f"sum ({res.mode})")
    wsum = float(np.sum(res.weights))
    for i, lab in enumerate(res.labels):
        frac = (100.0 * res.weights[i] / wsum) if wsum > 0 else float("nan")
        ax1.plot(prep.x, prep.A[:, i] * res.weights[i], lw=1.0,
                 label=f"{lab} ({frac:.0f} %)")
    ax1.set_ylabel(ylabel)
    ax1.legend(fontsize=8)
    ax2.axhline(0.0, color="0.6", lw=0.6)
    ax2.plot(prep.x, prep.b - fit, "b-", lw=0.8)
    ax2.set_ylabel("residual")
    ax2.set_xlabel(xlabel)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    if show:
        plt.show()
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        measured = _read_any(args.measured, args.xcol, args.ycol,
                             args.decimal_comma)
        subs = [_read_any(p, args.xcol, args.ycol, args.decimal_comma)
                for p in args.sub]
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    labels = args.labels or [Path(p).stem for p in args.sub]
    if len(labels) != len(subs):
        print("ERROR: number of --labels does not match number of --sub files.",
              file=sys.stderr)
        return 2

    try:
        prep = prepare_arrays(measured, subs, labels,
                              norm=args.normalize, xmin=args.xmin, xmax=args.xmax,
                              xname=args.xname)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    modes = ["convex", "nnls", "linear"] if args.mode == "all" else [args.mode]
    results: list[FitResult] = []
    try:
        for m in modes:
            if m == "manual":
                results.append(_manual_fit(prep, args.weights,
                                           weighted=args.dx_weight))
            else:
                results.append(run_fit(
                    prep, m, bootstrap=args.bootstrap, seed=args.seed,
                    block=args.block, ftest=args.ftest, weighted=args.dx_weight))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        _print_report(prep, results, args.measured)

    primary = (next((r for r in results if r.mode == "convex"), results[0])
               if args.mode == "all" else results[0])

    prefix = (Path(args.out) if args.out else
              Path(args.measured).with_suffix("").parent /
              (Path(args.measured).stem + "_lcf"))
    prefix.parent.mkdir(parents=True, exist_ok=True)

    if args.csv:
        data_path = prefix.with_name(prefix.name + "_fit.csv")
        export_data(prep, primary, data_path, delimiter=",")
    else:
        data_path = prefix.with_name(prefix.name + "_fit.dat")
        export_data(prep, primary, data_path)
    json_path = prefix.with_name(prefix.name + "_weights.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(build_json_payload(prep, results), fh, indent=2)
    if not args.quiet:
        print(f"\nWrote fit data : {data_path}")
        print(f"Wrote summary  : {json_path}")

    if args.xlsx:
        xlsx_path = prefix.with_name(prefix.name + ".xlsx")
        try:
            export_xlsx(prep, results, primary, xlsx_path)
            if not args.quiet:
                print(f"Wrote workbook : {xlsx_path}")
        except RuntimeError as exc:
            print(f"WARNING: could not write .xlsx ({exc})", file=sys.stderr)

    if not args.no_plot:
        png_path = prefix.with_name(prefix.name + ".png")
        _make_plot(prep, primary, png_path, args.xlabel, args.ylabel, args.show)
        if not args.quiet:
            print(f"Wrote plot     : {png_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
