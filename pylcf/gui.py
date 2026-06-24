#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gui.py -- PyLCF Tkinter graphical interface.

Builds on the shared numeric core in :mod:`pylcf.core`.  Launch with
``python -m pylcf`` (or the installed ``pylcf`` command).

Author:  Lukas Knauer (AG Schünemann, RPTU Kaiserslautern-Landau)
License: MIT
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .core import (
    APP_VERSION, trapz_area, read_spectrum, parse_table, read_excel_sheets,
    specs_from_shared_grid, specs_from_xy_pairs, read_xlsx_spectrum,
    specs_from_named, prepare_arrays, goodness_of_fit, FitResult, run_fit,
    export_data, build_json_payload, export_xlsx,
)

# GUI imports are guarded so the module imports even on machines without a Tk
# display (only instantiating the windows needs one).
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import (
        FigureCanvasTkAgg, NavigationToolbar2Tk)
    _GUI_OK = True
    _GUI_IMPORT_ERROR = None
except Exception as exc:                                   # pragma: no cover
    _GUI_OK = False
    _GUI_IMPORT_ERROR = exc

APP_TITLE = "PyLCF — Linear Combination Fit"


ROLE_LABELS = {"measured": "measured", "reference": "reference"}

_CONFIG_PATH = Path.home() / ".pylcf.json"
_PERSIST_VARS = ("mode", "norm", "xlabel", "ylabel", "xname",
                 "bootstrap", "seed", "block_boot", "dx_weight")
PASTE_ROLES = ["Energy", "Measured", "Reference", "Ignore"]


class PasteDialog:
    """Modal dialog: paste a table, assign a role to each column."""

    def __init__(self, parent, on_apply):
        self.on_apply = on_apply
        self.col_widgets = []      # list of (name_var, role_var)
        self.names = None
        self.data = None

        self.top = tk.Toplevel(parent)
        self.top.title("Paste table from Excel")
        self.top.transient(parent)
        self.top.bind("<Escape>", lambda e: self.top.destroy())
        self.top.grab_set()
        self.top.geometry("720x620")

        intro = ("Select the columns in Excel (ideally with a header), copy "
                 "with Ctrl+C, click into the field here and paste with Ctrl+V"
                 ". Then click 'Detect columns' and give each "
                 "column its role.")
        ttk.Label(self.top, text=intro, wraplength=690,
                  justify="left").pack(anchor="w", padx=10, pady=(10, 6))

        # paste area -------------------------------------------------------
        txt_frame = ttk.Frame(self.top)
        txt_frame.pack(fill="both", expand=False, padx=10)
        self.text = tk.Text(txt_frame, height=10, wrap="none",
                            font=("Consolas", 9), undo=True)
        ysb = ttk.Scrollbar(txt_frame, orient="vertical",
                            command=self.text.yview)
        xsb = ttk.Scrollbar(txt_frame, orient="horizontal",
                            command=self.text.xview)
        self.text.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        txt_frame.rowconfigure(0, weight=1)
        txt_frame.columnconfigure(0, weight=1)

        # controls ---------------------------------------------------------
        ctl = ttk.Frame(self.top)
        ctl.pack(fill="x", padx=10, pady=8)
        ttk.Button(ctl, text="Paste from clipboard",
                   command=self._paste_clip).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(ctl, text="Clear",
                   command=lambda: self.text.delete("1.0", "end")
                   ).grid(row=0, column=1, padx=6)

        ttk.Label(ctl, text="Delimiter:").grid(row=0, column=2, padx=(18, 4))
        self.delim_var = tk.StringVar(value="Auto")
        ttk.Combobox(ctl, textvariable=self.delim_var, width=11,
                     state="readonly",
                     values=["Auto", "Tab", "Semicolon", "Comma", "Space"]
                     ).grid(row=0, column=3)
        ttk.Label(ctl, text="Decimal:").grid(row=0, column=4, padx=(12, 4))
        self.dec_var = tk.StringVar(value="Auto")
        ttk.Combobox(ctl, textvariable=self.dec_var, width=8,
                     state="readonly",
                     values=["Auto", "Point", "Comma"]
                     ).grid(row=0, column=5)

        ttk.Button(self.top, text="Detect columns",
                   command=self._detect).pack(anchor="w", padx=10)

        # column-role table ------------------------------------------------
        self.cols_outer = ttk.LabelFrame(self.top, text="Columns and roles")
        self.cols_outer.pack(fill="both", expand=True, padx=10, pady=8)
        self.cols_frame = ttk.Frame(self.cols_outer)
        self.cols_frame.pack(fill="both", expand=True, padx=6, pady=6)
        ttk.Label(self.cols_frame,
                  text="(nothing detected yet)").grid(row=0, column=0)

        # action buttons ---------------------------------------------------
        act = ttk.Frame(self.top)
        act.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(act, text="Apply",
                   command=self._apply).pack(side="right")
        ttk.Button(act, text="Cancel",
                   command=self.top.destroy).pack(side="right", padx=6)

    # -- helpers -----------------------------------------------------------
    def _paste_clip(self):
        try:
            clip = self.top.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("Clipboard empty",
                                   "The clipboard contains no text.",
                                   parent=self.top)
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", clip)
        self._detect()

    def _opts(self):
        d = {"Auto": "auto", "Tab": "tab", "Semicolon": "semicolon",
             "Comma": "comma", "Space": "space"}[self.delim_var.get()]
        dec = {"Auto": "auto", "Point": "point",
               "Comma": "comma"}[self.dec_var.get()]
        return d, dec

    def _detect(self):
        raw = self.text.get("1.0", "end")
        if not raw.strip():
            return
        d, dec = self._opts()
        try:
            names, data, n_skip = parse_table(raw, delimiter=d, decimal=dec)
        except ValueError as exc:
            messagebox.showerror("Table not readable", str(exc),
                                 parent=self.top)
            return
        self.names, self.data = names, data
        self._build_col_table(names, data, n_skip)

    def _build_col_table(self, names, data, n_skip):
        for w in self.cols_frame.winfo_children():
            w.destroy()
        self.col_widgets = []

        info = f"{data.shape[0]} rows × {data.shape[1]} columns detected."
        if n_skip:
            info += f"  ({n_skip} row(s) skipped)"
        ttk.Label(self.cols_frame, text=info).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        ttk.Label(self.cols_frame, text="Column name", width=22,
                  font=("TkDefaultFont", 9, "bold")).grid(row=1, column=0, sticky="w")
        ttk.Label(self.cols_frame, text="Role",
                  font=("TkDefaultFont", 9, "bold")).grid(row=1, column=1, sticky="w")
        ttk.Label(self.cols_frame, text="Preview (first values)",
                  font=("TkDefaultFont", 9, "bold")).grid(row=1, column=2, sticky="w")

        for j, name in enumerate(names):
            name_var = tk.StringVar(value=name)
            ttk.Entry(self.cols_frame, textvariable=name_var, width=22).grid(
                row=2 + j, column=0, sticky="w", pady=1)
            # default roles: col0 = energy, col1 = measured, rest = reference
            default = "Energy" if j == 0 else ("Measured" if j == 1 else "Reference")
            role_var = tk.StringVar(value=default)
            ttk.Combobox(self.cols_frame, textvariable=role_var, width=12,
                         state="readonly", values=PASTE_ROLES).grid(
                row=2 + j, column=1, sticky="w", padx=8)
            preview = ", ".join(f"{v:g}" for v in data[:3, j])
            ttk.Label(self.cols_frame, text=preview + " …",
                      foreground="#555").grid(row=2 + j, column=2, sticky="w")
            self.col_widgets.append((name_var, role_var))

    def _apply(self):
        if self.data is None:
            messagebox.showwarning("Nothing detected",
                                   "Please paste data first and click "
                                   "'Detect columns'.",
                                   parent=self.top)
            return
        roles = [rv.get() for _, rv in self.col_widgets]
        energy_idx = [i for i, r in enumerate(roles) if r == "Energy"]
        if len(energy_idx) != 1:
            messagebox.showerror("Energy column",
                                 "Exactly one column must be marked as "
                                 "'Energy'.", parent=self.top)
            return
        meas_idx = [i for i, r in enumerate(roles) if r == "Measured"]
        if len(meas_idx) > 1:
            messagebox.showerror("Measured spectrum",
                                 "At most one column may be marked "
                                 "'Measured'.", parent=self.top)
            return
        used = [i for i, r in enumerate(roles) if r in ("Measured", "Reference")]
        if not used:
            messagebox.showerror("No spectra",
                                 "At least one column must be 'Measured' or "
                                 "'Reference'.", parent=self.top)
            return

        ex = energy_idx[0]
        x = self.data[:, ex]
        specs = []
        for i in used:
            specs.append({
                "name": self.col_widgets[i][0].get().strip() or f"Column {i + 1}",
                "role": "measured" if roles[i] == "Measured" else "reference",
                "x": x.copy(),
                "y": self.data[:, i].copy(),
                "source": "Excel",
            })
        self.on_apply(specs)
        self.top.destroy()


EXCEL_PAIR_ROLES = ["Measured", "Reference", "Ignore"]


class ExcelImportDialog:
    """Modal dialog: import spectra from an .xlsx/.xlsm workbook.

    Two layouts are offered:
      * "Shared grid"  - one Energy column + Measured/Reference columns
        (all spectra share one grid), like the paste dialog.
      * "XY pairs"            - consecutive (E, I) column pairs; each pair is a
        spectrum on its own grid, so the spectra may differ in sampling.
    """

    def __init__(self, parent, sheets, filename, on_apply):
        self.sheets = sheets                       # {name: (names, data)}
        self.sheet_names = list(sheets.keys())
        self.on_apply = on_apply
        self.row_widgets = []                      # (name_var, role_var)

        self.top = tk.Toplevel(parent)
        self.top.title(f"Import Excel — {filename}")
        self.top.transient(parent)
        self.top.bind("<Escape>", lambda e: self.top.destroy())
        self.top.grab_set()
        self.top.geometry("780x660")

        intro = ("Import data from an Excel file. Choose the sheet "
                 "and the layout. With 'XY pairs' each spectrum may have its "
                 "own energy grid (different x/y values) — the "
                 "spectra are automatically interpolated onto the common "
                 "overlap region for the fit.")
        ttk.Label(self.top, text=intro, wraplength=750,
                  justify="left").pack(anchor="w", padx=10, pady=(10, 6))

        # sheet + layout selectors -----------------------------------------
        sel = ttk.Frame(self.top)
        sel.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Label(sel, text="Sheet:").grid(row=0, column=0, sticky="w")
        self.sheet_var = tk.StringVar(value=self.sheet_names[0])
        sheet_cb = ttk.Combobox(sel, textvariable=self.sheet_var, width=24,
                                state="readonly", values=self.sheet_names)
        sheet_cb.grid(row=0, column=1, sticky="w", padx=(4, 18))
        sheet_cb.bind("<<ComboboxSelected>>", lambda e: self._rebuild())

        self.layout = tk.StringVar(value="shared")
        ttk.Label(sel, text="Layout:").grid(row=0, column=2, sticky="w")
        ttk.Radiobutton(sel, text="Shared grid (1x energy + n x intensity)",
                        variable=self.layout, value="shared",
                        command=self._rebuild).grid(row=1, column=0, columnspan=3,
                                                     sticky="w", pady=(6, 0))
        ttk.Radiobutton(sel, text="XY pairs:  E, I, E, I, ...  (different grids allowed)",
                        variable=self.layout, value="pairs",
                        command=self._rebuild).grid(row=2, column=0, columnspan=3,
                                                     sticky="w")

        # mapping table ----------------------------------------------------
        self.map_outer = ttk.LabelFrame(self.top, text="Columns / pairs and roles")
        self.map_outer.pack(fill="both", expand=True, padx=10, pady=8)
        self.map_frame = ttk.Frame(self.map_outer)
        self.map_frame.pack(fill="both", expand=True, padx=6, pady=6)

        # action buttons ---------------------------------------------------
        act = ttk.Frame(self.top)
        act.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(act, text="Apply", command=self._apply).pack(side="right")
        ttk.Button(act, text="Cancel",
                   command=self.top.destroy).pack(side="right", padx=6)

        self._rebuild()

    # -- helpers -----------------------------------------------------------
    def _current(self):
        return self.sheets[self.sheet_var.get()]

    @staticmethod
    def _fmt(v):
        return "—" if v != v else f"{v:g}"        # v!=v is True for NaN

    @staticmethod
    def _looks_measured(name):
        n = (name or "").lower()
        return ("gemess" in n) or ("measur" in n)

    def _rebuild(self):
        for w in self.map_frame.winfo_children():
            w.destroy()
        self.row_widgets = []
        names, data = self._current()
        info = f"{data.shape[0]} rows × {data.shape[1]} columns."

        if self.layout.get() == "shared":
            self._build_shared(names, data, info)
        else:
            self._build_pairs(names, data, info)

    def _build_shared(self, names, data, info):
        ttk.Label(self.map_frame, text=info + "  Exactly ONE column = 'Energy'.",
                  ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(self.map_frame, text="Column name", width=22,
                  font=("TkDefaultFont", 9, "bold")).grid(row=1, column=0, sticky="w")
        ttk.Label(self.map_frame, text="Role",
                  font=("TkDefaultFont", 9, "bold")).grid(row=1, column=1, sticky="w")
        ttk.Label(self.map_frame, text="Preview",
                  font=("TkDefaultFont", 9, "bold")).grid(row=1, column=2, sticky="w")
        for j, name in enumerate(names):
            name_var = tk.StringVar(value=name)
            ttk.Entry(self.map_frame, textvariable=name_var, width=22).grid(
                row=2 + j, column=0, sticky="w", pady=1)
            default = "Energy" if j == 0 else ("Measured" if j == 1 else "Reference")
            role_var = tk.StringVar(value=default)
            ttk.Combobox(self.map_frame, textvariable=role_var, width=12,
                         state="readonly", values=PASTE_ROLES).grid(
                row=2 + j, column=1, sticky="w", padx=8)
            preview = ", ".join(self._fmt(v) for v in data[:3, j])
            ttk.Label(self.map_frame, text=preview + " …",
                      foreground="#555").grid(row=2 + j, column=2, sticky="w")
            self.row_widgets.append((name_var, role_var))

    def _build_pairs(self, names, data, info):
        npairs = data.shape[1] // 2
        note = info + f"  -> {npairs} pair(s)."
        if data.shape[1] % 2:
            note += "  (last column without a partner is ignored)"
        ttk.Label(self.map_frame, text=note).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(self.map_frame, text="Spectrum (name)", width=22,
                  font=("TkDefaultFont", 9, "bold")).grid(row=1, column=0, sticky="w")
        ttk.Label(self.map_frame, text="Role",
                  font=("TkDefaultFont", 9, "bold")).grid(row=1, column=1, sticky="w")
        ttk.Label(self.map_frame, text="Preview (E -> I)",
                  font=("TkDefaultFont", 9, "bold")).grid(row=1, column=2, sticky="w")

        y_names = [names[2 * k + 1] if 2 * k + 1 < len(names) else f"Spectrum {k + 1}"
                   for k in range(npairs)]
        any_meas = any(self._looks_measured(n) for n in y_names)
        for k in range(npairs):
            name_var = tk.StringVar(value=y_names[k])
            ttk.Entry(self.map_frame, textvariable=name_var, width=22).grid(
                row=2 + k, column=0, sticky="w", pady=1)
            if any_meas:
                default = "Measured" if self._looks_measured(y_names[k]) else "Reference"
            else:
                default = "Measured" if k == 0 else "Reference"
            role_var = tk.StringVar(value=default)
            ttk.Combobox(self.map_frame, textvariable=role_var, width=12,
                         state="readonly", values=EXCEL_PAIR_ROLES).grid(
                row=2 + k, column=1, sticky="w", padx=8)
            ex, iy = data[:, 2 * k], data[:, 2 * k + 1]
            preview = f"{self._fmt(ex[0])} → {self._fmt(iy[0])}, " \
                      f"{self._fmt(ex[1])} → {self._fmt(iy[1])} …"
            ttk.Label(self.map_frame, text=preview,
                      foreground="#555").grid(row=2 + k, column=2, sticky="w")
            self.row_widgets.append((name_var, role_var))

    def _apply(self):
        names, data = self._current()
        try:
            if self.layout.get() == "shared":
                edited = [nv.get().strip() or names[i]
                          for i, (nv, _) in enumerate(self.row_widgets)]
                roles = [rv.get() for _, rv in self.row_widgets]
                specs = specs_from_shared_grid(edited, data, roles)
            else:
                pair_names = [nv.get().strip() for nv, _ in self.row_widgets]
                pair_roles = [rv.get() for _, rv in self.row_widgets]
                specs = specs_from_xy_pairs(names, data, pair_roles,
                                            pair_names=pair_names)
        except ValueError as exc:
            messagebox.showerror("Import not possible", str(exc), parent=self.top)
            return
        self.on_apply(specs)
        self.top.destroy()


class FolderImportDialog:
    """Modal dialog: assign roles to spectra read from a folder of Excel files.

    Each file is one spectrum on its own grid.  The user marks which file is
    Measured and which are Reference (or Ignore); a filename that
    contains "gemessen"/"measured" is pre-selected as the measured spectrum.
    """

    def __init__(self, parent, spectra, foldername, on_apply):
        self.spectra = spectra                     # [{name, x, y, source}]
        self.on_apply = on_apply
        self.row_widgets = []

        self.top = tk.Toplevel(parent)
        self.top.title(f"Import Excel folder — {foldername}")
        self.top.transient(parent)
        self.top.bind("<Escape>", lambda e: self.top.destroy())
        self.top.grab_set()
        self.top.geometry("760x620")

        intro = (f"{len(spectra)} Excel file(s) found. Each file is one "
                 "spectrum with its own energy grid. Please give each file a role: "
                 "at most one 'Measured', any number of 'Reference'. "
                 "The fit automatically interpolates onto the common overlap "
                 "region.")
        ttk.Label(self.top, text=intro, wraplength=730,
                  justify="left").pack(anchor="w", padx=10, pady=(10, 8))

        outer = ttk.LabelFrame(self.top, text="Files and roles")
        outer.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        # scrollable list (a folder may hold many files) -------------------
        canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.rows = ttk.Frame(canvas)
        self.rows.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.rows, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        vsb.pack(side="right", fill="y")

        ttk.Label(self.rows, text="File / name", width=30,
                  font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(self.rows, text="Role",
                  font=("TkDefaultFont", 9, "bold")).grid(row=0, column=1, sticky="w")
        ttk.Label(self.rows, text="Points",
                  font=("TkDefaultFont", 9, "bold")).grid(row=0, column=2, sticky="w", padx=8)
        ttk.Label(self.rows, text="Preview (E -> I)",
                  font=("TkDefaultFont", 9, "bold")).grid(row=0, column=3, sticky="w")

        names = [sp["name"] for sp in spectra]
        any_meas = any(ExcelImportDialog._looks_measured(n) for n in names)
        for k, sp in enumerate(spectra):
            name_var = tk.StringVar(value=sp["name"])
            ttk.Entry(self.rows, textvariable=name_var, width=30).grid(
                row=1 + k, column=0, sticky="w", pady=1)
            if any_meas:
                default = ("Measured" if ExcelImportDialog._looks_measured(sp["name"])
                           else "Reference")
            else:
                default = "Measured" if k == 0 else "Reference"
            role_var = tk.StringVar(value=default)
            ttk.Combobox(self.rows, textvariable=role_var, width=12,
                         state="readonly", values=EXCEL_PAIR_ROLES).grid(
                row=1 + k, column=1, sticky="w", padx=8)
            x = np.asarray(sp["x"], float)
            y = np.asarray(sp["y"], float)
            ttk.Label(self.rows, text=str(x.size),
                      foreground="#555").grid(row=1 + k, column=2, sticky="w", padx=8)
            preview = (f"{x[0]:g} → {y[0]:g}, {x[1]:g} → {y[1]:g} …"
                       if x.size >= 2 else "—")
            ttk.Label(self.rows, text=preview,
                      foreground="#555").grid(row=1 + k, column=3, sticky="w")
            self.row_widgets.append((name_var, role_var))

        act = ttk.Frame(self.top)
        act.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(act, text="Apply", command=self._apply).pack(side="right")
        ttk.Button(act, text="Cancel",
                   command=self.top.destroy).pack(side="right", padx=6)

    def _apply(self):
        spectra = [{"name": nv.get().strip(), "x": sp["x"], "y": sp["y"],
                    "source": sp.get("source", "Excel")}
                   for (nv, _), sp in zip(self.row_widgets, self.spectra)]
        roles = [rv.get() for _, rv in self.row_widgets]
        try:
            specs = specs_from_named(spectra, roles)
        except ValueError as exc:
            messagebox.showerror("Import not possible", str(exc), parent=self.top)
            return
        self.on_apply(specs)
        self.top.destroy()


class OverlayDialog:
    """Interactive overlay: scale each reference with a slider and watch the
    summed model, the live fractions and the live R-factor / R^2 update.

    Sliders are scale-invariant: each runs from 0 to a data-driven maximum
    (about twice the weight that would make that component's peak match the
    measured peak, and at least twice its auto-fit weight), so the controls are
    sensible whether the data is area-, max- or un-normalized.  Plot and
    controls are split by a draggable divider, so the slider area can be
    enlarged whenever more components need room.  The current state can be
    exported (image + .xlsx/.csv/.dat/.json) like the auto-fit.
    The manual overlay is for exploration; report the automatic fit.
    """

    def __init__(self, parent, prep, init_weights, xlabel="Energy (cm^-1)",
                 ylabel="normalized intensity"):
        self.prep = prep
        self.x, self.b, self.A = prep.x, prep.b, prep.A
        self.labels = list(prep.labels)
        self.n = self.A.shape[1]
        self.xlabel = xlabel
        self.ylabel = ylabel

        self.top = tk.Toplevel(parent)
        self.top.title("Interactive overlay")
        self.top.transient(parent)
        self.top.bind("<Escape>", lambda e: self.top.destroy())
        # The final window size is computed at the END of __init__ from the
        # natural (requested) height of the assembled widgets, so the weight
        # panel is never clipped regardless of component count, theme or
        # platform.  Here we only allow resizing; geometry and minsize follow
        # once every control exists (see "size to content" at end of __init__).
        self.top.resizable(True, True)

        # Sensible, scale-invariant slider ranges.  Each slider runs 0 .. 2x a
        # data-driven "natural" weight: the largest of the auto-fit weight, the
        # area-match weight (this component alone carrying the full measured
        # area) and the peak-match weight.  The area-match floor keeps a slider
        # usable even for a component the fit set to ~0; the per-slider number
        # field can push past the range when more headroom is needed.
        bmax = float(np.max(self.b)) if self.b.size else 1.0
        barea = trapz_area(self.b, self.x)
        self.wmax, self.init_weights = [], []
        for i in range(self.n):
            amax = float(np.max(self.A[:, i]))
            aarea = trapz_area(self.A[:, i], self.x)
            w_peak = bmax / amax if amax > 0 else 1.0
            w_area = barea / aarea if aarea > 0 else 1.0
            w0 = (float(init_weights[i])
                  if init_weights is not None and i < len(init_weights) else w_peak)
            self.wmax.append(2.0 * max(abs(w0), w_peak, w_area, 1e-12))
            self.init_weights.append(
                float(init_weights[i])
                if init_weights is not None and i < len(init_weights) else 0.0)

        # The plot and the control panel sit in a vertical paned window joined
        # by a draggable divider (sash).  Drag the divider down to shrink the
        # plot and give the weight sliders as much room as you need, or up for a
        # larger plot -- so the controls are always reachable, whatever the
        # window or screen size.  (This replaces the old fixed split, where the
        # sliders could end up clipped below the window edge.)
        pane = ttk.PanedWindow(self.top, orient="vertical")
        pane.pack(fill="both", expand=True)
        self.pane = pane

        # plot pane --------------------------------------------------------
        plot_pane = ttk.Frame(pane)
        pane.add(plot_pane, weight=4)
        self.fig = Figure(figsize=(8.4, 4.3), dpi=100)
        self.ax1 = self.fig.add_subplot(2, 1, 1)
        self.ax2 = self.fig.add_subplot(2, 1, 2, sharex=self.ax1)
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_pane)
        tb = ttk.Frame(plot_pane)
        tb.pack(side="bottom", fill="x")
        NavigationToolbar2Tk(self.canvas, tb)
        self.canvas.get_tk_widget().pack(side="top", fill="both", expand=True,
                                         padx=6, pady=(6, 0))

        # control pane -----------------------------------------------------
        ctrl = ttk.Frame(pane)
        pane.add(ctrl, weight=1)

        sl = ttk.LabelFrame(
            ctrl, text="Component weights  (slide, or type an exact value)")
        sl.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)
        self.scales, self.scale_w = [], []
        self.entries, self.frac_labels = [], []
        self.colors = ["C%d" % i for i in range(self.n)]
        for i in range(self.n):
            ttk.Label(sl, text=self.labels[i], width=16).grid(
                row=i, column=0, sticky="w", pady=2)
            var = tk.DoubleVar(value=self.init_weights[i])
            scw = tk.Scale(sl, from_=0.0, to=self.wmax[i],
                           resolution=self.wmax[i] / 1000.0, orient="horizontal",
                           variable=var, showvalue=False, length=300,
                           command=lambda _v: self._update())
            scw.grid(row=i, column=1, sticky="we", padx=6)
            ev = tk.StringVar(value="%.4g" % self.init_weights[i])
            ent = ttk.Entry(sl, textvariable=ev, width=9, justify="right")
            ent.grid(row=i, column=2, sticky="w", padx=(0, 4))
            ent.bind("<Return>", lambda e, idx=i: self._on_entry(idx))
            ent.bind("<FocusOut>", lambda e, idx=i: self._on_entry(idx))
            flab = ttk.Label(sl, text="", width=9, foreground="#555")
            flab.grid(row=i, column=3, sticky="w")
            self.scales.append(var)
            self.scale_w.append(scw)
            self.entries.append(ev)
            self.frac_labels.append(flab)
        sl.columnconfigure(1, weight=1)

        right = ttk.Frame(ctrl)
        right.pack(side="left", fill="y", padx=(12, 8), pady=6)
        self.gof_var = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.gof_var, justify="left",
                  font=("Consolas", 9)).pack(anchor="w")
        brow = ttk.Frame(right)
        brow.pack(anchor="w", pady=(6, 0))
        ttk.Button(brow, text="Load from auto-fit",
                   command=self._load_auto).pack(side="left")
        ttk.Button(brow, text="Reset", command=self._reset).pack(side="left", padx=4)
        erow = ttk.Frame(right)
        erow.pack(anchor="w", pady=(8, 0))
        ttk.Button(erow, text="Save image", command=self._save_image).pack(side="left")
        ttk.Button(erow, text="Data (.dat/.csv)",
                   command=self._save_data).pack(side="left", padx=4)
        ttk.Button(erow, text="Excel (.xlsx)", command=self._save_xlsx).pack(side="left")
        ttk.Button(erow, text="JSON", command=self._save_json).pack(side="left", padx=4)

        # plot artists -----------------------------------------------------
        self.ax1.set_ylabel(self.ylabel)
        zero = self.b * 0
        (self.l_meas,) = self.ax1.plot(self.x, self.b, color="k", lw=1.4,
                                       label="measured")
        (self.l_fit,) = self.ax1.plot(self.x, zero, color="crimson", lw=1.6,
                                      ls="--", label="sum (manual)")
        self.l_comp = []
        for i in range(self.n):
            (ln,) = self.ax1.plot(self.x, zero, lw=1.0, color=self.colors[i])
            self.l_comp.append(ln)
        self.ax2.axhline(0.0, color="0.6", lw=0.8)
        (self.l_resid,) = self.ax2.plot(self.x, zero, color="navy", lw=1.0)
        self.ax2.set_ylabel("residual")
        self.ax2.set_xlabel(self.xlabel)
        self.fig.tight_layout()
        self._update()

        # -- size to content -------------------------------------------------
        # Let the window size itself to the natural (requested) size of its
        # contents: Tk fits a Toplevel to its children when no explicit
        # geometry is set, so the plot, toolbar and every slider row are fully
        # visible on open -- regardless of component count, theme or platform,
        # and without the fragile hand-tuned height formula this replaces.
        # We intervene only if the content would be taller than the screen:
        # then we cap the height.  The plot canvas is packed last with
        # expand=True and the control panel + toolbar are packed at the bottom
        # (expand=False), so any height shortfall is taken from the plot first
        # -- the slider rows always keep their full height.  The minimum size
        # keeps the controls visible if the window is shrunk manually.
        self.top.update_idletasks()
        ctrl_h = ctrl.winfo_reqheight() + tb.winfo_reqheight()
        cap_h = max(520, self.top.winfo_screenheight() - 80)
        if self.top.winfo_reqheight() > cap_h:
            self.top.geometry("%dx%d" % (self.top.winfo_reqwidth(), cap_h))
        self.top.minsize(820, min(cap_h, max(480, ctrl_h + 140)))

    # -- live update -------------------------------------------------------
    def _weights(self):
        return np.array([v.get() for v in self.scales], dtype=float)

    def _update(self):
        w = self._weights()
        fitv = self.A @ w
        total = float(w.sum())
        for i in range(self.n):
            frac = 100.0 * w[i] / total if total > 0 else float("nan")
            if self.top.focus_get() is not self.scale_w[i]:
                self.entries[i].set("%.4g" % w[i])
            self.frac_labels[i].config(text="%.1f %%" % frac)
            self.l_comp[i].set_ydata(w[i] * self.A[:, i])
            self.l_comp[i].set_label("%s (%.0f %%)" % (self.labels[i], frac))
        self.l_fit.set_ydata(fitv)
        self.l_resid.set_ydata(self.b - fitv)
        g = goodness_of_fit(self.b, fitv)
        self.gof_var.set("sum of weights = %.4f\nR-factor = %.4e\nR\u00b2       = %.5f"
                         % (total, g.r_factor, g.r_squared))
        self.ax1.legend(fontsize=8, frameon=False)
        for ax in (self.ax1, self.ax2):
            ax.relim()
            ax.autoscale_view(scalex=False)
        self.canvas.draw_idle()

    def _load_auto(self):
        for i, v in enumerate(self.scales):
            v.set(min(self.init_weights[i], self.wmax[i]))
        self._update()

    def _reset(self):
        for v in self.scales:
            v.set(0.0)
        self._update()

    def _on_entry(self, i):
        """Apply an exact value typed into a slider's number field, extending
        the slider range automatically if the value exceeds it."""
        s = self.entries[i].get().strip().replace(",", ".")
        try:
            val = float(s)
        except ValueError:
            self.entries[i].set("%.4g" % self.scales[i].get())
            return
        if val < 0:
            val = 0.0
        if val > self.wmax[i]:
            self.wmax[i] = 1.25 * val
            self.scale_w[i].config(to=self.wmax[i],
                                   resolution=self.wmax[i] / 1000.0)
        self.scales[i].set(val)
        self._update()

    # -- export (reuses the same writers as the auto-fit) ------------------
    def _result(self):
        w = self._weights()
        gof = goodness_of_fit(self.b, self.A @ w, n_params=self.n)
        return FitResult(mode="manual", labels=self.labels, weights=w, gof=gof)

    def _save_image(self):
        p = filedialog.asksaveasfilename(
            title="Save image", defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")])
        if p:
            self.fig.savefig(p, dpi=150, bbox_inches="tight")

    def _save_data(self):
        p = filedialog.asksaveasfilename(
            title="Save fit data", defaultextension=".dat",
            filetypes=[("Tab-separated (.dat)", "*.dat"), ("CSV (.csv)", "*.csv")])
        if not p:
            return
        delim = "," if p.lower().endswith(".csv") else "\t"
        export_data(self.prep, self._result(), Path(p), delimiter=delim)

    def _save_xlsx(self):
        p = filedialog.asksaveasfilename(
            title="Save Excel", defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")])
        if not p:
            return
        try:
            res = self._result()
            export_xlsx(self.prep, [res], res, Path(p))
        except Exception as exc:                                # pragma: no cover
            messagebox.showerror("Excel export not possible", str(exc),
                                 parent=self.top)

    def _save_json(self):
        p = filedialog.asksaveasfilename(
            title="Save summary", defaultextension=".json",
            filetypes=[("JSON", "*.json")])
        if not p:
            return
        payload = build_json_payload(self.prep, [self._result()])
        Path(p).write_text(json.dumps(payload, indent=2), encoding="utf-8")


class _Tooltip:
    """Minimal hover tooltip for a widget."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event=None):
        if self.tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 14
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, justify="left", background="#ffffe0",
                 relief="solid", borderwidth=1, wraplength=320,
                 font=("TkDefaultFont", 8)).pack(ipadx=3, ipady=2)

    def _hide(self, _event=None):
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"{APP_TITLE}  v{APP_VERSION}")
        root.geometry("1180x760")
        root.minsize(960, 620)

        self.spectra = []      # dicts: name, role, x, y, source
        self.prep = None
        self.results = []
        self.primary = None

        self._build_ui()
        self._refresh_tree()
        self.last_dir = str(Path.home())
        self._load_config()
        self._bind_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _bind_shortcuts(self):
        self.root.bind("<F5>", lambda e: self.on_fit())
        self.root.bind("<Control-s>", lambda e: self.on_export_data())
        self.root.bind("<Control-o>", lambda e: self._open_excel())
        self.root.bind("<Control-p>", lambda e: self._open_paste())

    def _load_config(self):
        """Restore last-used folder and option preferences (best effort)."""
        try:
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        d = data.get("last_dir")
        if isinstance(d, str) and Path(d).is_dir():
            self.last_dir = d
        for name in _PERSIST_VARS:
            var = getattr(self, name, None)
            if var is not None and name in data:
                try:
                    var.set(data[name])
                except Exception:
                    pass

    def _save_config(self):
        """Persist last-used folder and option preferences (best effort)."""
        try:
            data = {"last_dir": self.last_dir}
            for name in _PERSIST_VARS:
                var = getattr(self, name, None)
                if var is not None:
                    data[name] = var.get()
            _CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _on_close(self):
        self._save_config()
        self.root.destroy()

    # -- UI construction ---------------------------------------------------
    def _build_ui(self):
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=8)

        # The left control column can be taller than the window (small screens,
        # many references), so it lives in a scrollable canvas with a vertical
        # scrollbar: drag the scrollbar -- or use the mouse wheel over the
        # column -- to reach every section, including the Export buttons at the
        # very bottom.  Without this the lowest controls were clipped off the
        # window and could not be clicked.
        left_outer = ttk.Frame(paned, width=492)
        left_outer.pack_propagate(False)
        paned.add(left_outer, weight=0)

        self._left_canvas = tk.Canvas(left_outer, highlightthickness=0,
                                      borderwidth=0)
        left_vsb = ttk.Scrollbar(left_outer, orient="vertical",
                                 command=self._left_canvas.yview)
        self._left_canvas.configure(yscrollcommand=left_vsb.set)
        left_vsb.pack(side="right", fill="y")
        self._left_canvas.pack(side="left", fill="both", expand=True)

        left = ttk.Frame(self._left_canvas)
        left_win = self._left_canvas.create_window((0, 0), window=left,
                                                   anchor="nw")
        left.bind(
            "<Configure>",
            lambda e: self._left_canvas.configure(
                scrollregion=self._left_canvas.bbox("all")))
        self._left_canvas.bind(
            "<Configure>",
            lambda e: self._left_canvas.itemconfigure(left_win, width=e.width))
        self._bind_mousewheel(self._left_canvas)

        right = ttk.Frame(paned)
        paned.add(right, weight=1)

        self._build_data_section(left)
        self._build_options_section(left)
        self._build_run_section(left)
        self._build_results_section(left)
        self._build_export_section(left)
        self._build_plot(right)

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self.root, textvariable=self.status, relief="sunken",
                  anchor="w").pack(fill="x", side="bottom")

    def _bind_mousewheel(self, canvas):
        """Scroll ``canvas`` with the mouse wheel while the pointer is over it
        (Windows/macOS send <MouseWheel>; X11 sends Button-4/5)."""
        def _wheel(e):
            if getattr(e, "num", 0) == 4:
                d = -1
            elif getattr(e, "num", 0) == 5:
                d = 1
            else:
                d = int(-e.delta / 120) if e.delta else 0
            if d:
                canvas.yview_scroll(d, "units")
        canvas.bind("<Enter>", lambda e: (
            canvas.bind_all("<MouseWheel>", _wheel),
            canvas.bind_all("<Button-4>", _wheel),
            canvas.bind_all("<Button-5>", _wheel)))
        canvas.bind("<Leave>", lambda e: (
            canvas.unbind_all("<MouseWheel>"),
            canvas.unbind_all("<Button-4>"),
            canvas.unbind_all("<Button-5>")))

    def _build_data_section(self, parent):
        f = ttk.LabelFrame(parent, text="1 - Data")
        f.pack(fill="x", pady=(0, 6))

        cols = ("name", "role", "n", "src")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=6)
        for c, txt, w in (("name", "Name", 150), ("role", "Role", 90),
                          ("n", "Points", 60), ("src", "Source", 80)):
            self.tree.heading(c, text=txt)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="x", padx=6, pady=(6, 4))
        self.tree.bind("<Double-1>", lambda e: self._rename_selected())

        b1 = ttk.Frame(f)
        b1.pack(fill="x", padx=6)
        ttk.Button(b1, text="Paste table ...",
                   command=self._open_paste).pack(side="left")
        ttk.Button(b1, text="Excel file ...",
                   command=self._open_excel).pack(side="left", padx=4)
        ttk.Button(b1, text="Excel folder ...",
                   command=self._open_excel_folder).pack(side="left")

        b1b = ttk.Frame(f)
        b1b.pack(fill="x", padx=6, pady=(4, 0))
        ttk.Button(b1b, text="Load measured ...",
                   command=lambda: self._load_files("measured")
                   ).pack(side="left")
        ttk.Button(b1b, text="Load references ...",
                   command=lambda: self._load_files("reference")
                   ).pack(side="left", padx=4)

        b2 = ttk.Frame(f)
        b2.pack(fill="x", padx=6, pady=(4, 6))
        ttk.Button(b2, text="Switch role",
                   command=self._toggle_role).pack(side="left")
        ttk.Button(b2, text="Rename",
                   command=self._rename_selected).pack(side="left", padx=4)
        ttk.Button(b2, text="Remove",
                   command=self._remove_selected).pack(side="left", padx=4)
        ttk.Button(b2, text="Clear all",
                   command=self._clear_all).pack(side="left")
        self.decimal_comma = tk.BooleanVar(value=False)
        ttk.Checkbutton(b2, text="Decimal comma (files)",
                        variable=self.decimal_comma).pack(side="right")

    def _build_options_section(self, parent):
        f = ttk.LabelFrame(parent, text="2 - Options")
        f.pack(fill="x", pady=6)
        g = ttk.Frame(f)
        g.pack(fill="x", padx=6, pady=6)

        mode_lab = ttk.Label(g, text="Mode:")
        mode_lab.grid(row=0, column=0, sticky="w")
        self.mode = tk.StringVar(value="convex")
        ttk.Combobox(g, textvariable=self.mode, width=10, state="readonly",
                     values=["convex", "nnls", "linear", "all"]
                     ).grid(row=0, column=1, sticky="w", padx=(4, 16))
        _Tooltip(mode_lab,
                 "convex: weights >= 0 and sum to 1 -> fractions (default).\n"
                 "nnls: weights >= 0, no sum constraint.\n"
                 "linear: unconstrained, may give negative weights.\n"
                 "all: compute all three; the plot shows convex.")

        norm_lab = ttk.Label(g, text="Normalization:")
        norm_lab.grid(row=0, column=2, sticky="w")
        self.norm = tk.StringVar(value="area")
        ttk.Combobox(g, textvariable=self.norm, width=8, state="readonly",
                     values=["area", "max", "none"]
                     ).grid(row=0, column=3, sticky="w", padx=4)
        _Tooltip(norm_lab,
                 "area: area = 1, so convex weights are true fractions "
                 "(recommended).\nmax: maximum = 1.\nnone: values used as-is.")

        emin_lab = ttk.Label(g, text="Energy min:")
        emin_lab.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.xmin = tk.StringVar(value="")
        ttk.Entry(g, textvariable=self.xmin, width=10).grid(
            row=1, column=1, sticky="w", padx=(4, 16), pady=(6, 0))
        ttk.Label(g, text="Energy max:").grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.xmax = tk.StringVar(value="")
        ttk.Entry(g, textvariable=self.xmax, width=8).grid(
            row=1, column=3, sticky="w", padx=4, pady=(6, 0))
        _Tooltip(emin_lab, "Optional fit window in x-units. Leave both empty "
                 "for the automatic overlap of all spectra.")

        boot_lab = ttk.Label(g, text="Bootstrap N:")
        boot_lab.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.bootstrap = tk.StringVar(value="0")
        ttk.Entry(g, textvariable=self.bootstrap, width=10).grid(
            row=2, column=1, sticky="w", padx=(4, 16), pady=(6, 0))
        ttk.Label(g, text="Seed:").grid(row=2, column=2, sticky="w", pady=(6, 0))
        self.seed = tk.StringVar(value="0")
        ttk.Entry(g, textvariable=self.seed, width=8).grid(
            row=2, column=3, sticky="w", padx=4, pady=(6, 0))
        _Tooltip(boot_lab,
                 "Number of residual-bootstrap resamples for weight error bars "
                 "(e.g. 500). 0 = off. Seed makes it reproducible.")

        self.block_boot = tk.BooleanVar(value=False)
        blk = ttk.Checkbutton(
            g, text="Block bootstrap (correlated residuals)",
            variable=self.block_boot)
        blk.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        _Tooltip(blk,
                 "Resample contiguous residual blocks (~sqrt(n)) instead of "
                 "single points. Spectral residuals are correlated, so this "
                 "gives more honest (usually wider) confidence intervals.")

        self.dx_weight = tk.BooleanVar(value=False)
        dxw = ttk.Checkbutton(
            g, text="Δx weighting (uneven grids)", variable=self.dx_weight)
        dxw.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        _Tooltip(dxw,
                 "Weight each point by its x-spacing (trapezoidal) so the fit "
                 "approximates the integral and no longer depends on sampling "
                 "density. Off = equal weights (identical to the CLI). For an "
                 "even grid the effect is negligible.")

        xlab_l = ttk.Label(g, text="X axis:")
        xlab_l.grid(row=5, column=0, sticky="w", pady=(6, 0))
        self.xlabel = tk.StringVar(value="Energy (cm⁻¹)")
        xlab_e = ttk.Entry(g, textvariable=self.xlabel, width=30)
        xlab_e.grid(row=5, column=1, columnspan=3, sticky="we", padx=4, pady=(6, 0))
        _Tooltip(xlab_l, "Plot x-axis label only (units / LaTeX allowed). "
                         "The export column name is set below.")

        ylab_l = ttk.Label(g, text="Y axis:")
        ylab_l.grid(row=6, column=0, sticky="w", pady=(6, 0))
        self.ylabel = tk.StringVar(value="normalized intensity")
        ylab_e = ttk.Entry(g, textvariable=self.ylabel, width=30)
        ylab_e.grid(row=6, column=1, columnspan=3, sticky="we", padx=4, pady=(6, 0))
        _Tooltip(ylab_l, "Plot y-axis label only. Does not affect the exported "
                         "columns (measured / fit / residual / components).")

        xname_l = ttk.Label(g, text="x column name:")
        xname_l.grid(row=7, column=0, sticky="w", pady=(6, 0))
        self.xname = tk.StringVar(value="energy")
        xname_e = ttk.Entry(g, textvariable=self.xname, width=16)
        xname_e.grid(row=7, column=1, sticky="w", padx=4, pady=(6, 0))
        _Tooltip(xname_l, "Name of the x column in the .dat / Excel exports "
                          "(e.g. energy, wavenumber). Not the plot label.")

    def _build_run_section(self, parent):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=4)
        style = ttk.Style()
        try:
            style.configure("Run.TButton", font=("TkDefaultFont", 11, "bold"))
        except tk.TclError:
            pass
        ttk.Button(f, text="\u25b6  Run fit", style="Run.TButton",
                   command=self.on_fit).pack(fill="x", ipady=4)

    def _build_results_section(self, parent):
        f = ttk.LabelFrame(parent, text="3 - Result")
        f.pack(fill="both", expand=True, pady=6)

        cols = ("comp", "w", "pct", "err", "ci", "p")
        self.res_tree = ttk.Treeview(f, columns=cols, show="headings", height=5)
        for c, txt, w in (("comp", "Component", 118), ("w", "Weight", 62),
                          ("pct", "Fraction", 56), ("err", "\u00b1", 50),
                          ("ci", "95% CI", 102), ("p", "p (F)", 58)):
            self.res_tree.heading(c, text=txt)
            self.res_tree.column(c, width=w, anchor="w")
        self.res_tree.pack(fill="x", padx=6, pady=(6, 4))

        self.gof_text = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.gof_text, justify="left",
                  font=("Consolas", 9)).pack(anchor="w", padx=8, pady=(0, 6))
        ttk.Button(f, text="Copy results", command=self._copy_results).pack(
            anchor="w", padx=8, pady=(0, 6))

    def _build_export_section(self, parent):
        f = ttk.LabelFrame(parent, text="4 - Export")
        f.pack(fill="x", pady=(0, 4))
        row = ttk.Frame(f)
        row.pack(fill="x", padx=6, pady=6)
        ttk.Button(row, text="Fit data (.dat/.csv)",
                   command=self.on_export_data).pack(side="left")
        ttk.Button(row, text="Excel (.xlsx)",
                   command=self.on_export_xlsx).pack(side="left", padx=4)
        ttk.Button(row, text="Summary (.json)",
                   command=self.on_export_json).pack(side="left")
        row2 = ttk.Frame(f)
        row2.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(row2, text="Plot (.png)",
                   command=self.on_export_png).pack(side="left")
        ttk.Button(row2, text="Interactive overlay",
                   command=self.on_overlay).pack(side="left", padx=4)
        ttk.Button(row2, text="Show guide",
                   command=self.on_help).pack(side="right")

    def _build_plot(self, parent):
        self.fig = Figure(figsize=(7.2, 6.0), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(self.canvas, parent)
        toolbar.update()
        self._draw_empty()

    # -- data management ---------------------------------------------------
    def _open_paste(self):
        PasteDialog(self.root, self._add_specs)

    def _open_excel(self):
        p = filedialog.askopenfilename(
            title="Import Excel file", initialdir=self.last_dir,
            filetypes=[("Excel files", "*.xlsx *.xlsm"),
                       ("All files", "*.*")])
        if not p:
            return
        self.last_dir = str(Path(p).parent)
        try:
            sheets = read_excel_sheets(p)
        except ImportError:
            messagebox.showerror(
                "openpyxl missing",
                "The Excel import needs the 'openpyxl' package.\n"
                "Install with:  pip install openpyxl")
            return
        except Exception as exc:                                # pragma: no cover
            messagebox.showerror("Excel not readable", str(exc))
            return
        ExcelImportDialog(self.root, sheets, Path(p).name, self._add_specs)

    def _open_excel_folder(self):
        d = filedialog.askdirectory(title="Choose a folder with Excel files",
                                    initialdir=self.last_dir)
        if not d:
            return
        self.last_dir = d
        paths = sorted(p for p in Path(d).iterdir()
                       if p.is_file() and not p.name.startswith("~$")
                       and p.suffix.lower() in (".xlsx", ".xlsm"))
        if not paths:
            messagebox.showwarning(
                "No Excel files",
                "No .xlsx/.xlsm files were found in the selected folder.")
            return
        spectra, errors = [], []
        for p in paths:
            try:
                x, y = read_xlsx_spectrum(str(p))
            except ImportError:
                messagebox.showerror(
                    "openpyxl missing",
                    "The Excel import needs the 'openpyxl' package.\n"
                    "Install with:  pip install openpyxl")
                return
            except Exception as exc:
                errors.append(f"{p.name}: {exc}")
                continue
            spectra.append({"name": p.stem, "x": x, "y": y, "source": "Excel"})
        if errors:
            messagebox.showwarning("Some files not readable",
                                   "\n".join(errors))
        if spectra:
            FolderImportDialog(self.root, spectra, Path(d).name, self._add_specs)

    def _add_specs(self, specs):
        for sp in specs:
            if sp["role"] == "measured":
                for s in self.spectra:        # only one measured at a time
                    if s["role"] == "measured":
                        s["role"] = "reference"
            base = (sp.get("name") or "").strip()
            if not base:
                if sp["role"] == "reference":
                    n = sum(1 for s in self.spectra
                            if s["role"] == "reference") + 1
                    base = f"Reference {n}"
                else:
                    base = "Measured"
            self.spectra.append({
                "name": self._unique_name(base), "role": sp["role"],
                "x": np.asarray(sp["x"], float), "y": np.asarray(sp["y"], float),
                "source": sp.get("source", "—"),
            })
        self._refresh_tree()
        self.status.set(f"{len(specs)} spectrum/spectra added.")

    def _load_files(self, role):
        multi = (role == "reference")
        kw = dict(title="Load spectrum" if not multi else "Load references",
                  initialdir=self.last_dir,
                  filetypes=[("Spectra", "*.dat *.csv *.txt *.fio *.don"),
                             ("All files", "*.*")])
        if multi:
            paths = filedialog.askopenfilenames(**kw)
        else:
            p = filedialog.askopenfilename(**kw)
            paths = [p] if p else []
        if not paths:
            return
        self.last_dir = str(Path(paths[0]).parent)
        added, errors = [], []
        for p in paths:
            try:
                x, y = read_spectrum(p, decimal_comma=self.decimal_comma.get())
            except (FileNotFoundError, ValueError) as exc:
                errors.append(f"{Path(p).name}: {exc}")
                continue
            added.append({"name": Path(p).stem, "role": role,
                          "x": x, "y": y, "source": "File"})
        if added:
            self._add_specs(added)
        if errors:
            messagebox.showwarning("Some files not readable",
                                   "\n".join(errors))

    def _selected_indices(self):
        return [self.tree.index(i) for i in self.tree.selection()]

    def _toggle_role(self):
        idx = self._selected_indices()
        if not idx:
            self.status.set("Please select a spectrum in the list first.")
            return
        for i in idx:
            s = self.spectra[i]
            if s["role"] == "reference":
                for o in self.spectra:    # keep a single measured
                    if o["role"] == "measured":
                        o["role"] = "reference"
                s["role"] = "measured"
            else:
                s["role"] = "reference"
        self._refresh_tree()

    def _remove_selected(self):
        idx = sorted(self._selected_indices(), reverse=True)
        for i in idx:
            del self.spectra[i]
        self._refresh_tree()

    def _clear_all(self):
        if self.spectra and messagebox.askyesno(
                "Clear all", "Remove all loaded spectra?"):
            self.spectra.clear()
            self._refresh_tree()

    def _unique_name(self, base, exclude=None):
        """Return a non-empty name unique among the other spectra."""
        base = (str(base).strip() or "Spectrum")
        existing = {s["name"] for k, s in enumerate(self.spectra)
                    if k != exclude}
        if base not in existing:
            return base
        k = 2
        while f"{base} {k}" in existing:
            k += 1
        return f"{base} {k}"

    def _rename_selected(self):
        idx = self._selected_indices()
        if not idx:
            self.status.set("Please select a spectrum in the list first.")
            return
        i = idx[0]
        new = simpledialog.askstring(
            "Rename spectrum", "New name:",
            initialvalue=self.spectra[i]["name"], parent=self.root)
        if new is None:
            return
        new = new.strip()
        if not new:
            self.status.set("Name cannot be empty.")
            return
        self.spectra[i]["name"] = self._unique_name(new, exclude=i)
        self._refresh_tree()

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for s in self.spectra:
            self.tree.insert("", "end", values=(
                s["name"], ROLE_LABELS[s["role"]], s["x"].size, s["source"]))
        n_meas = sum(1 for s in self.spectra if s["role"] == "measured")
        n_ref = sum(1 for s in self.spectra if s["role"] == "reference")
        self.status.set(f"{len(self.spectra)} spectra - "
                        f"{n_meas} measured - {n_ref} reference(s)")

    # -- fitting -----------------------------------------------------------
    def _parse_float(self, var, name):
        s = var.get().strip().replace(",", ".")
        if s == "":
            return None
        try:
            return float(s)
        except ValueError:
            raise ValueError(f"{name}: '{var.get()}' is not a number.")

    def _parse_int(self, var, name):
        s = var.get().strip()
        if s == "":
            return 0
        try:
            return int(s)
        except ValueError:
            raise ValueError(f"{name}: '{var.get()}' is not an integer.")

    def on_fit(self):
        try:
            meas = [s for s in self.spectra if s["role"] == "measured"]
            refs = [s for s in self.spectra if s["role"] == "reference"]
            if len(meas) != 1:
                raise ValueError("Exactly one spectrum must have the role "
                                 "'measured'.")
            if len(refs) < 1:
                raise ValueError("At least one reference is required.")

            xmin = self._parse_float(self.xmin, "Energy min")
            xmax = self._parse_float(self.xmax, "Energy max")
            if xmin is not None and xmax is not None and xmin >= xmax:
                raise ValueError("Energy min must be smaller than Energy max.")
            n_boot = self._parse_int(self.bootstrap, "Bootstrap N")
            seed = self._parse_int(self.seed, "Seed")

            m = meas[0]
            prep = prepare_arrays(
                (m["x"], m["y"]),
                [(r["x"], r["y"]) for r in refs],
                [r["name"] for r in refs],
                norm=self.norm.get(), xmin=xmin, xmax=xmax,
                xname=self.xname.get(),
            )

            self.status.set("Running fit"
                            + (f" (bootstrap N={n_boot})" if n_boot else "")
                            + " \u2026")
            self.root.config(cursor="watch")
            self.root.update_idletasks()

            modes = ["convex", "nnls", "linear"] if self.mode.get() == "all" \
                else [self.mode.get()]
            results = [run_fit(prep, md, bootstrap=n_boot, seed=seed,
                               block=self.block_boot.get(), ftest=True,
                               weighted=self.dx_weight.get())
                       for md in modes]
            primary = next((r for r in results if r.mode == "convex"),
                           results[0])
        except ValueError as exc:
            messagebox.showerror("Fit not possible", str(exc))
            self.status.set(f"Error: {exc}")
            return
        except Exception as exc:                                # pragma: no cover
            messagebox.showerror("Unexpected error", str(exc))
            self.status.set(f"Error: {exc}")
            return
        finally:
            self.root.config(cursor="")

        self.prep, self.results, self.primary = prep, results, primary
        self._update_results()
        self._update_plot()
        self.status.set(f"Fit done ({primary.mode}) - "
                        f"R-factor = {primary.gof.r_factor:.3e} - "
                        f"{prep.x.size} points in window "
                        f"{prep.window[0]:.1f}–{prep.window[1]:.1f}")

    def _update_results(self):
        self.res_tree.delete(*self.res_tree.get_children())
        self.res_tree.tag_configure("weak", foreground="#9a9a9a")
        r = self.primary
        total = float(r.weights.sum())
        any_weak = False
        any_ns = False
        for i, lab in enumerate(r.labels):
            pct = 100.0 * r.weights[i] / total if total else float("nan")
            err = f"{r.werr[i]:.4f}" if r.werr is not None else ""
            ci = (f"[{r.wci[i, 0]:.3f}, {r.wci[i, 1]:.3f}]"
                  if r.wci is not None else "")
            weak_ci = r.wci is not None and r.wci[i, 0] <= 1e-9
            if weak_ci:
                any_weak = True
                ci += "  ~0"
            pcell, ns = "", False
            if r.fp is not None and not np.isnan(r.fp[i]):
                pv = float(r.fp[i])
                pcell = "<1e-4" if pv < 1e-4 else f"{pv:.3g}"
                if pv >= 0.05:
                    ns = True
                    any_ns = True
            grey = weak_ci or ns
            self.res_tree.insert("", "end", tags=(("weak",) if grey else ()),
                                 values=(lab, f"{r.weights[i]:.4f}",
                                         f"{pct:.1f} %", err, ci, pcell))
        self.res_tree.insert("", "end", values=(
            "Sum", f"{total:.4f}", "100.0 %", "", "", ""))

        g = r.gof
        lines = [f"Mode {r.mode}:" + ("  · Δx-weighted" if r.weighted else ""),
                 f"  R-factor = {g.r_factor:.4e}   (Σ(meas−fit)² / Σmeas²)",
                 f"  RMSE     = {g.rmse:.4e}",
                 f"  R²       = {g.r_squared:.5f}"]
        if len(self.results) > 1:
            lines.append("")
            lines.append("Comparison (by R-factor):")
            for rr in sorted(self.results, key=lambda x: x.gof.r_factor):
                ws = " ".join(f"{v:.3f}" for v in rr.weights)
                lines.append(f"  {rr.mode:<7} R={rr.gof.r_factor:.3e}  [{ws}]")
            lines.append("Note: smallest R-factor != best model.")
        if r.wci is not None:
            lines.append("")
            lines.append("± = bootstrap std,  [..] = 95% CI"
                         + ("  (block)" if self.block_boot.get() else ""))
            if any_weak:
                lines.append("~0 = CI includes 0; component may be unnecessary.")
            if r.mode == "convex":
                lines.append("(near 0/1 the convex-weight CI is one-sided.)")
        if r.fp is not None:
            lines.append("")
            lines.append(f"p (F): drop-one F-test (full N), df=1,{r.fdof[1]};"
                         "  < 0.05 = component justified.")
            if any_ns:
                lines.append("grey row = not significant (p >= 0.05).")
            lines.append(f"  residuals: lag-1 ρ={r.acf1:.2f}, eff. N≈"
                         f"{r.n_eff:.0f} of {self.prep.x.size}"
                         "  -> full-N p is optimistic.")
            if r.fp_eff is not None:
                pe = ", ".join(
                    f"{lab} {'n/a' if np.isnan(r.fp_eff[i]) else format(r.fp_eff[i], '.2g')}"
                    for i, lab in enumerate(r.labels))
                lines.append(f"  p with eff. N (autocorr-adjusted): {pe}")
            lines.append("  (rigorous for linear; approximate for nnls/convex.)")
        self.gof_text.set("\n".join(lines))

    # -- plotting ----------------------------------------------------------
    def _draw_empty(self):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.text(0.5, 0.5, "Load data and click 'Run fit'",
                ha="center", va="center", color="0.5", fontsize=11)
        ax.set_xticks([])
        ax.set_yticks([])
        self.canvas.draw()

    def _update_plot(self):
        prep, res = self.prep, self.primary
        A, b, x = prep.A, prep.b, prep.x
        fit = res.fit_curve(A)
        resid = b - fit

        self.fig.clear()
        gs = self.fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.05)
        ax1 = self.fig.add_subplot(gs[0])
        ax2 = self.fig.add_subplot(gs[1], sharex=ax1)

        ax1.plot(x, b, color="k", lw=1.4, label="measured")
        ax1.plot(x, fit, color="crimson", lw=1.6, ls="--", label="fit")
        for i, lab in enumerate(res.labels):
            ax1.plot(x, res.weights[i] * A[:, i], lw=1.0, alpha=0.85,
                     label=f"{lab}  ({res.weights[i]:.3f})")
        ax1.set_ylabel(self.ylabel.get())
        ax1.legend(frameon=False, fontsize=9)
        ax1.set_title(f"PyLCF  ·  mode: {res.mode}   "
                      f"R-factor = {res.gof.r_factor:.3e}", fontsize=10)
        ax1.tick_params(labelbottom=False)

        ax2.axhline(0.0, color="0.6", lw=0.8)
        ax2.plot(x, resid, color="navy", lw=1.0)
        ax2.set_ylabel("residual")
        ax2.set_xlabel(self.xlabel.get())
        ax2.set_xlim(x.min(), x.max())

        self.fig.tight_layout()
        self.canvas.draw()

    # -- export ------------------------------------------------------------
    def on_overlay(self):
        if not self._need_fit():
            return
        OverlayDialog(self.root, self.prep, self.primary.weights,
                      self.xlabel.get(), self.ylabel.get())

    def _need_fit(self):
        if self.prep is None or self.primary is None:
            messagebox.showinfo("No fit yet",
                                "Please run a fit first.")
            return False
        return True

    def _copy_results(self):
        if not self._need_fit():
            return
        r = self.primary
        total = float(r.weights.sum())
        out = [f"PyLCF {APP_VERSION} - {r.mode} fit"
               + ("  (dx-weighted)" if r.weighted else ""),
               f"normalization: {self.norm.get()};  window "
               f"[{self.prep.window[0]:.6g}, {self.prep.window[1]:.6g}];  "
               f"{self.prep.x.size} points"]
        hdr = ["component", "weight", "fraction_%"]
        if r.werr is not None:
            hdr += ["std", "ci_low", "ci_high"]
        if r.fp is not None:
            hdr += ["p_Ftest_fullN"]
            if r.fp_eff is not None:
                hdr += ["p_Ftest_effN"]
        out.append("\t".join(hdr))
        for i, lab in enumerate(r.labels):
            row = [lab, f"{r.weights[i]:.6g}",
                   (f"{100.0 * r.weights[i] / total:.2f}" if total else "nan")]
            if r.werr is not None:
                row += [f"{r.werr[i]:.6g}",
                        f"{r.wci[i, 0]:.6g}", f"{r.wci[i, 1]:.6g}"]
            if r.fp is not None:
                row += ["" if np.isnan(r.fp[i]) else f"{r.fp[i]:.3g}"]
                if r.fp_eff is not None:
                    row += ["" if np.isnan(r.fp_eff[i])
                            else f"{r.fp_eff[i]:.3g}"]
            out.append("\t".join(row))
        g = r.gof
        out += [f"R-factor\t{g.r_factor:.6e}",
                f"RMSE\t{g.rmse:.6e}",
                f"R^2\t{g.r_squared:.6f}"]
        text = "\n".join(out)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status.set("Results copied to clipboard.")

    def on_export_data(self):
        if not self._need_fit():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".dat",
            filetypes=[("Text data (tab)", "*.dat"), ("CSV (comma)", "*.csv")],
            initialdir=self.last_dir, initialfile="pylcf_fit.dat")
        if not path:
            return
        self.last_dir = str(Path(path).parent)
        delim = "," if path.lower().endswith(".csv") else "\t"
        try:
            export_data(self.prep, self.primary, Path(path), delimiter=delim)
        except Exception as exc:                                # pragma: no cover
            messagebox.showerror("Export failed", str(exc))
            return
        self.status.set(f"Wrote: {path}")

    def on_export_json(self):
        if not self._need_fit():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")],
            initialdir=self.last_dir, initialfile="pylcf_weights.json")
        if not path:
            return
        self.last_dir = str(Path(path).parent)
        payload = build_json_payload(self.prep, self.results)
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.status.set(f"Wrote: {path}")

    def on_export_xlsx(self):
        if not self._need_fit():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
            initialdir=self.last_dir, initialfile="pylcf_fit.xlsx")
        if not path:
            return
        self.last_dir = str(Path(path).parent)
        try:
            export_xlsx(self.prep, self.results, self.primary, Path(path))
        except RuntimeError as exc:
            messagebox.showerror("Excel export failed", str(exc))
            return
        self.status.set(f"Wrote: {path}")

    def on_export_png(self):
        if not self._need_fit():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")],
            initialdir=self.last_dir, initialfile="pylcf.png")
        if not path:
            return
        self.last_dir = str(Path(path).parent)
        self.fig.savefig(path, dpi=150, bbox_inches="tight")
        self.status.set(f"Wrote: {path}")

    def on_help(self):
        win = tk.Toplevel(self.root)
        win.title("Kurzanleitung")
        win.geometry("680x560")
        txt = tk.Text(win, wrap="word", font=("TkDefaultFont", 10),
                      padx=12, pady=12)
        sb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("1.0", HELP_TEXT)
        txt.configure(state="disabled")


HELP_TEXT = """PyLCF — Quick guide
===================

Goal
----
A measured dataset — a curve y(x) sampled over some axis x (energy, 2theta,
time, wavelength, m/z, ...) — is described as a weighted sum of reference
datasets on the same axis:   y_meas(x) ≈ Σ wᵢ · yᵢ(x).
The program finds the weights wᵢ (e.g. population fractions). An NIS/NRVS
spectrum decomposed into component PVDOS is the running example, but any data
that is plausibly a linear combination of references works (XAS/XANES LCF,
diffraction patterns, chromatograms, kinetic traces, ...).

1 - Entering data
-----------------
Variant A — paste a table from Excel (recommended):
  • Select the columns in Excel (ideally with a header),
    e.g.  Energy | Measured | WT | DM | Red.
  • Ctrl+C, then here "Paste table ..." -> "Paste from clipboard".
  • Click "Detect columns" and give each column a role:
    exactly ONE "Energy", at most ONE "Measured", any number of
    "Reference", the rest "Ignore". Names are editable.
  • German decimal commas and tabs are auto-detected
    (force via "Delimiter" / "Decimal" if needed).

Variant B — import an Excel file (.xlsx/.xlsm):
  • "Excel file ..." -> choose a file, then sheet and layout.
  • Layout "Shared grid": 1x energy + n x intensity (like Variant A).
  • Layout "XY pairs": consecutive column pairs E, I, E, I, ... —
    each pair is its own spectrum and may have its OWN energy grid
    (different x/y values). The fit interpolates onto the common
    overlap region automatically.

Variant C — import an Excel folder:
  • "Excel folder ..." -> choose a folder. Each .xlsx/.xlsm in it is ONE
    spectrum (first two columns = energy, intensity); the files may have
    different grids. Assign a role to each file in the dialog.

Variant D — load files:
  • "Load measured ..." (one file) and "Load references ..." (several).
  • Two-column text files (.dat/.csv/.txt). For German decimal commas
    tick "Decimal comma (files)" first.

"Switch role" toggles a row between measured/reference. Only one
"measured" spectrum is active at a time.

2 - Options
-----------
Mode:
  convex  — weights >= 0 and sum = 1  -> population fractions (default).
  nnls    — weights >= 0 (non-negative amplitudes, no sum constraint).
  linear  — unconstrained least squares; may give unphysical negative
            weights. A smaller R-factor does NOT mean a better model.
  all     — convex/nnls/linear side by side; the plot shows convex.
Normalization: "area" (area = 1) makes the convex weights true fractions.
Energy min/max: optional fit window (empty = automatic overlap).
Bootstrap N: error bars (95% CI) of the weights by residual bootstrap
            (e.g. 500). 0 = off. Seed makes the result reproducible.
Block bootstrap: resample contiguous residual blocks (~sqrt(n)) for
            correlated spectral residuals -> more honest, wider CIs.
Δx weighting: weight each point by its x-spacing (trapezoidal) so the fit
            approximates the integral and no longer depends on sampling
            density. Off = equal weights (identical to the CLI); for an even
            grid the effect is negligible.

3 - Result
----------
Table with weight/fraction (±/CI with bootstrap, p from the F-test) plus
R-factor = Σ(meas−fit)² / Σmeas², RMSE and R².
  • Column "p (F)": drop-one F-test — is each component justified? p < 0.05
    = yes; larger (grey row) = not significant. It assumes independent
    residuals; spectral residuals are correlated (ρ and effective N are
    shown), so p-values are optimistic — a relative guide, rigorous for
    linear. The bootstrap CI is the more trustworthy uncertainty.
  • "~0": a bootstrap CI that includes 0 -> component may be unnecessary.
"Copy results" copies the table + goodness-of-fit to the clipboard.
The plot shows measured, fit and the weighted components on top and the
residual below. The toolbar allows zoom/pan/save.

Interactive overlay
-------------------
"Interactive overlay" opens a window with one slider per reference. Move a
slider to scale that component up/down; the overlaid sum, the live fractions
(% of the total) and the live R-factor/R² update immediately. Use it to
explore by eye what fits best. Next to each slider a number field shows the
exact weight and lets you type one; a value beyond the slider's range extends
it automatically. "Load from auto-fit" sets the sliders to the convex weights,
"Reset" clears them. The overlay can save the image and the
data (.xlsx/.csv/.dat/.json), exactly like the main export. Note: the manual
overlay is for exploration — the numbers to report come from the automatic
fit (with bootstrap CIs).

4 - Export
----------
• Fit data (.dat = tab, .csv = comma): energy, measured, fit, residual and
  the weighted components — directly importable into Origin.
• Excel (.xlsx): sheet "fit" with the columns, sheet "summary" with weights
  and goodness-of-fit (needs pandas + openpyxl).
• Summary (.json): all weights, sums and goodness-of-fit.
• Plot (.png/.pdf/.svg).

Shortcuts
---------
F5 = run fit · Ctrl+S = export fit data · Ctrl+O = Excel file ·
Ctrl+P = paste table · Esc = close dialogs. The last folder is remembered.

Common problems
---------------
• "Empty fit window": energy ranges do not overlap or Emin/Emax too narrow.
• Wrongly parsed numbers: set delimiter/decimal separator explicitly in the
  paste dialog.
• "exactly one measured spectrum": check the roles in the list.
• "area normalization not meaningful": the net area is <= 0 (as much negative
  as positive) — use max/none or a positive window.
• Excel cells empty after import: formula cells need cached values (open and
  save the file in Excel once).

Note: for batch processing/scripting the command-line interface pylcf-cli
(python -m pylcf.cli), on the same core, remains available.
"""


def main():
    if not _GUI_OK:
        msg = ("The graphical interface needs Tkinter and Matplotlib.\n"
               f"Import failed: {_GUI_IMPORT_ERROR}\n\n"
               "On Windows/macOS, Tkinter ships with the standard Python.\n"
               "On Linux if needed:  sudo apt install python3-tk\n"
               "Matplotlib:        pip install matplotlib")
        print(msg)
        raise SystemExit(1)
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
