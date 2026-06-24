import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
# -*- coding: utf-8 -*-
import numpy as np, pylcf as G, tkinter as tk
XLSX = "/mnt/user-data/uploads/Programm_NIS-M1_M6_Spektren_Claude_ohne_negative_abgezogen.xlsx"
ok=[]
def check(n,c): ok.append(c); print(("PASS" if c else "FAIL"),"-",n)

sheets=G.read_excel_sheets(XLSX); (names,data)=next(iter(sheets.values()))
def pair(i,j):
    x,y=data[:,i],data[:,j]; m=np.isfinite(x)&np.isfinite(y); return x[m],y[m]
nx,ny=pair(0,1); m1=pair(2,3); m6=pair(4,5)

print("APP_VERSION =", G.APP_VERSION); check("version 1.0.0", G.APP_VERSION=="1.0.0")
root=tk.Tk(); root.withdraw(); app=G.App(root)
app.spectra=[{"name":"NIS","role":"measured","x":nx,"y":ny,"source":"Excel"},
             {"name":"M1","role":"reference","x":m1[0],"y":m1[1],"source":"Excel"},
             {"name":"M6","role":"reference","x":m6[0],"y":m6[1],"source":"Excel"}]
app.norm.set("area"); app.mode.set("convex"); app.xmin.set("20")
app.on_fit()
ov=G.OverlayDialog(root, app.prep, app.primary.weights, "Energy")

check("has number entries", len(ov.entries)==2 and hasattr(ov,"scale_w"))
check("entry shows initial weight", abs(float(ov.entries[0].get())-app.primary.weights[0])<5e-3)
check("area-match floor -> wmax>=2 (area norm)", all(w>=2-1e-9 for w in ov.wmax))
print("    wmax =", [round(w,3) for w in ov.wmax])

# type a value within range
ov.entries[0].set("0.20"); ov._on_entry(0)
check("typed in-range value applied", abs(ov.scales[0].get()-0.20)<2e-3)

# type a value beyond range -> auto-expand
big = ov.wmax[1]*5.0
ov.entries[1].set("%.6f"%big); ov._on_entry(1)
check("range auto-expanded", ov.wmax[1] >= big - 1e-9)
check("expanded value applied", abs(ov.scales[1].get()-big) < ov.wmax[1]/1000.0 + 1e-9)
check("scale widget 'to' updated", abs(float(ov.scale_w[1].cget("to"))-ov.wmax[1])<1e-6)
print("    after expand: wmax[1]=%.2f  weight[1]=%.2f" % (ov.wmax[1], ov.scales[1].get()))

# invalid input -> revert, weight unchanged
ov.scales[0].set(0.33); ov.entries[0].set("xyz"); ov._on_entry(0)
check("invalid reverts entry", abs(float(ov.entries[0].get())-0.33)<2e-3)
check("invalid keeps weight", abs(ov.scales[0].get()-0.33)<2e-3)

# German comma decimal accepted
ov.entries[0].set("0,40"); ov._on_entry(0)
check("comma decimal parsed", abs(ov.scales[0].get()-0.40)<2e-3)

# fractions + GoF still live
ov._update()
check("fraction label live", "%" in ov.frac_labels[0].cget("text"))
check("GoF live", "R-factor" in ov.gof_var.get())

# negative clamped to 0
ov.entries[1].set("-5"); ov._on_entry(1)
check("negative clamped to 0", ov.scales[1].get()==0.0)

# editable Y-axis: App has ylabel; plot + overlay use it
check("App has ylabel field", hasattr(app, "ylabel"))
app.ylabel.set("PVDOS (custom)")
app._update_plot()
yl = app.fig.axes[0].get_ylabel()
check("plot uses custom y-label", yl == "PVDOS (custom)")
ov2 = G.OverlayDialog(root, app.prep, app.primary.weights, "x", "PVDOS (custom)")
check("overlay uses passed y-label", ov2.ax1.get_ylabel() == "PVDOS (custom)")
ov2.top.destroy()

# spectrum renaming: unique-name helper + numbered defaults
check("unique-name dedup", app._unique_name("M1") == "M1 2")
_n0 = len(app.spectra)
app._add_specs([{"name": "", "role": "reference", "x": nx, "y": ny, "source": "T"},
                {"name": "", "role": "reference", "x": nx, "y": ny, "source": "T"}])
check("numbered default names",
      [s["name"] for s in app.spectra[_n0:]] == ["Reference 3", "Reference 4"])

root.destroy()


def test_all_checks_pass():
    assert all(ok), "%d/%d checks passed" % (sum(ok), len(ok))

if __name__ == "__main__":
    raise SystemExit(0 if all(ok) else 1)
