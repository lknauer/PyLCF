import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
# -*- coding: utf-8 -*-
"""Focused tests for the v1.0.0 improvements (core-level, headless)."""
import os, tempfile
from pathlib import Path
import numpy as np
import pylcf as G

ok = []
def chk(name, cond):
    ok.append(bool(cond))
    print(("PASS" if cond else "FAIL") + " - " + name)

# --- area <= 0 guard ---
x = np.linspace(0, 10, 101)
y_neg = x - 8.0                       # net area = -30 (clearly negative)
try:
    G._normalize(y_neg, x, "area"); chk("negative-area raises ValueError", False)
except ValueError:
    chk("negative-area raises ValueError", True)
# positive-area still works
chk("positive area normalizes",
    np.isfinite(G._normalize(np.abs(np.sin(x)) + 0.1, x, "area")).all())

# --- block bootstrap ---
rng = np.random.default_rng(0)
xg = np.linspace(0, 1, 200)
A = np.column_stack([np.exp(-((xg - 0.3) / 0.1) ** 2),
                     np.exp(-((xg - 0.7) / 0.1) ** 2)])
b = 0.6 * A[:, 0] + 0.4 * A[:, 1] + 0.01 * rng.standard_normal(200)
prep = G.PreparedData(x=xg, b=b, A=A, labels=["a", "b"], norm="none",
                      raw_areas={}, window=(0.0, 1.0))
rb = G.run_fit(prep, "nnls", bootstrap=200, seed=1, block=True)
chk("block bootstrap werr shape (2,)", rb.werr is not None and rb.werr.shape == (2,))
chk("block bootstrap ci shape (2,2)", rb.wci is not None and rb.wci.shape == (2, 2))
chk("block bootstrap values finite",
    np.all(np.isfinite(rb.werr)) and np.all(np.isfinite(rb.wci)))
rp = G.run_fit(prep, "nnls", bootstrap=200, seed=1, block=False)
chk("plain bootstrap still runs", rp.werr is not None and np.all(np.isfinite(rp.werr)))

# --- irrelevant component -> weight ~0, CI low ~0 (drives 'weak' marking) ---
A3 = np.column_stack([A[:, 0], A[:, 1], rng.standard_normal(200)])
b3 = 0.6 * A3[:, 0] + 0.4 * A3[:, 1]          # exact: no need for the junk col
prep3 = G.PreparedData(x=xg, b=b3, A=A3, labels=["a", "b", "junk"], norm="none",
                       raw_areas={}, window=(0.0, 1.0))
r3 = G.run_fit(prep3, "nnls", bootstrap=100, seed=2, block=False)
chk("irrelevant component weight ~0", abs(r3.weights[2]) < 1e-3)
chk("irrelevant component CI low ~0 (<=1e-9)", r3.wci[2, 0] <= 1e-9)

# --- export metadata header ---
r4 = G.run_fit(prep, "convex", bootstrap=0, seed=0)
d = tempfile.mkdtemp()
p = os.path.join(d, "t.dat")
G.export_data(prep, r4, Path(p), delimiter="\t")
hl = [l for l in open(p).read().splitlines() if l.startswith("#")]
chk("export header has PyLCF/version", any("PyLCF" in l for l in hl))
chk("export header has mode", any("mode:" in l for l in hl))
chk("export header has fit window", any("fit window" in l for l in hl))
chk("export header has normalization", any("normalization:" in l for l in hl))
chk("export column line intact (a,b,residual)",
    any(("a" in l and "b" in l and "residual" in l) for l in hl))
# data still numeric / loadable
arr = np.genfromtxt(p, comments="#")
chk("export data rows numeric", arr.ndim == 2 and arr.shape[0] == xg.size)

# --- F-test (drop-one component significance) ---
g1 = np.exp(-((xg - 0.3) / 0.08) ** 2)
g2 = np.exp(-((xg - 0.7) / 0.08) ** 2)
Af = np.column_stack([g1, g2, g1.copy()])     # 3rd column duplicates g1 (redundant)
bf = 0.6 * g1 + 0.4 * g2 + 0.005 * rng.standard_normal(200)
F, pv, dof = G.f_test_components(Af, bf, "linear")
chk("F-test df1 == 1", dof[0] == 1)
chk("F-test df2 == n-m (linear)", dof[1] == 200 - 3)
chk("unique component significant (p<0.05)", pv[1] < 0.05)
chk("redundant g1 not individually significant", pv[0] > 0.05)
chk("redundant duplicate not significant", pv[2] > 0.05)
_, p1, _ = G.f_test_components(g1.reshape(-1, 1), bf, "linear")
chk("single component -> NaN p", np.isnan(p1[0]))
_, _, dofc = G.f_test_components(np.column_stack([g1, g2]), bf, "convex")
chk("convex F-test df2 == n-(m-1)", dofc[1] == 200 - 1)
prep_f = G.PreparedData(x=xg, b=bf, A=Af, labels=["g1", "g2", "dup"],
                        norm="none", raw_areas={}, window=(0.0, 1.0))
rf = G.run_fit(prep_f, "linear", ftest=True)
chk("run_fit attaches fp (shape 3)", rf.fp is not None and rf.fp.shape == (3,))
chk("run_fit attaches autocorr+n_eff",
    rf.acf1 is not None and rf.n_eff is not None and 2.0 <= rf.n_eff <= 200.0)
chk("ftest off -> fp None", G.run_fit(prep_f, "linear").fp is None)
chk("neff-corrected df2 <= naive df2",
    G.f_test_components(Af, bf, "linear", use_neff=True)[2][1] <= dof[1])
chk("run_fit attaches fp_eff (shape 3)",
    rf.fp_eff is not None and rf.fp_eff.shape == (3,))
chk("eff-N p >= full-N p (more conservative)",
    bool(np.all(rf.fp_eff >= rf.fp - 1e-9)))
_e0 = G.build_json_payload(prep_f, [rf])["results"][0]
chk("JSON carries f_test (full + eff N)",
    "f_test" in _e0 and "p_full_N" in _e0["f_test"] and "p_eff_N" in _e0["f_test"])
chk("JSON carries residual autocorrelation",
    "residual_autocorrelation" in _e0
    and "effective_N" in _e0["residual_autocorrelation"])
# --- configurable x-axis column name in exports ---
_pw = G.prepare_arrays((xg, bf), [(xg, g1)], ["a"], norm="none",
                       xname="wavenumber")
chk("xname stored on PreparedData", _pw.xname == "wavenumber")
chk("xname defaults to energy",
    G.prepare_arrays((xg, bf), [(xg, g1)], ["a"], norm="none").xname == "energy")
chk("export x-column header uses xname",
    G.core._fit_columns(_pw, G.run_fit(_pw, "nnls"))[0][0] == "wavenumber")


# --- Δx weighting (uneven-grid invariance) ---
qw = G._quadrature_weights(np.linspace(0, 1, 11))
chk("quadrature weights mean ~1", abs(qw.mean() - 1.0) < 1e-9)
chk("quadrature weights sum == n", abs(qw.sum() - 11.0) < 1e-9)
xnu = np.sort(np.concatenate([np.linspace(0, 0.5, 50), np.linspace(0.55, 1, 5)]))
qnu = G._quadrature_weights(xnu)
chk("dense region -> smaller weights", qnu[:40].mean() < qnu[-4:].mean())

xu = np.linspace(0, 1, 201)
h1 = np.exp(-((xu - 0.3) / 0.07) ** 2)
h2 = np.exp(-((xu - 0.7) / 0.07) ** 2)
bump = np.exp(-((xu - 0.15) / 0.05) ** 2)   # feature h1,h2 cannot represent
bu = 0.55 * h1 + 0.45 * h2 + 0.20 * bump + 0.003 * rng.standard_normal(xu.size)
prep_u = G.PreparedData(x=xu, b=bu, A=np.column_stack([h1, h2]),
                        labels=["h1", "h2"], norm="none", raw_areas={},
                        window=(0.0, 1.0))
chk("weighted=False == plain fit (CLI parity)",
    np.allclose(G.run_fit(prep_u, "nnls", weighted=False).weights,
                G.fit_nnls(prep_u.A, prep_u.b)))
wu_w = G.run_fit(prep_u, "linear", weighted=True).weights
wu_p = G.run_fit(prep_u, "linear", weighted=False).weights

# densify the left third heavily (true measure of [0,0.3] is unchanged)
xd = np.unique(np.concatenate([xu, np.linspace(0.0, 0.3, 400)]))
A_d = np.column_stack([np.interp(xd, xu, h1), np.interp(xd, xu, h2)])
b_d = np.interp(xd, xu, bu)
prep_d = G.PreparedData(x=xd, b=b_d, A=A_d, labels=["h1", "h2"],
                        norm="none", raw_areas={}, window=(0.0, 1.0))
wd_w = G.run_fit(prep_d, "linear", weighted=True).weights
wd_p = G.run_fit(prep_d, "linear", weighted=False).weights
chk("weighted fit ~invariant to densification",
    np.max(np.abs(wd_w - wu_w)) < np.max(np.abs(wd_p - wu_p)))
chk("unweighted fit drifts with densification",
    np.max(np.abs(wd_p - wu_p)) > 1e-3)
chk("run_fit sets weighted flag", G.run_fit(prep_u, "convex", weighted=True).weighted)

# --- read_spectrum: German decimal comma with thousands dot ---
_d = tempfile.mkdtemp()
_fp = os.path.join(_d, "de.dat")
open(_fp, "w").write("# header line\n1.234,5\t0,75\n2.000,0\t1,25\n3,5\t2,0\n")
xx, yy = G.read_spectrum(_fp, decimal_comma=True)
chk("decimal thousands-dot parsed", np.allclose(xx, [3.5, 1234.5, 2000.0]))
chk("decimal-comma y parsed", np.allclose(yy, [2.0, 0.75, 1.25]))



def test_all_checks_pass():
    assert all(ok), "%d/%d checks passed" % (sum(ok), len(ok))

if __name__ == "__main__":
    raise SystemExit(0 if all(ok) else 1)
