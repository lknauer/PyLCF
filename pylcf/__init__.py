"""PyLCF -- Linear Combination Fitting (GUI + CLI) on a shared numeric core.

The numeric core lives in :mod:`pylcf.core`; the Tkinter GUI in :mod:`pylcf.gui`
(launched with ``python -m pylcf``); the command-line interface in
:mod:`pylcf.cli` (``pylcf-cli`` / ``python -m pylcf.cli``).

Author:  Lukas Knauer (AG Schünemann, RPTU Kaiserslautern-Landau)
License: MIT
"""
from .core import (  # noqa: F401  (re-exported public + internal API)
    APP_VERSION,
    trapz_area, read_spectrum, parse_table, read_excel_sheets,
    specs_from_shared_grid, specs_from_xy_pairs, read_xlsx_spectrum,
    specs_from_named, PreparedData, prepare_arrays, _normalize,
    fit_linear, fit_nnls, fit_convex, _quadrature_weights, _fit_weighted,
    GoF, goodness_of_fit, bootstrap_weights, _resid_autocorr1,
    f_test_components, FitResult, run_fit,
    export_data, build_json_payload, export_xlsx,
)

__version__ = APP_VERSION

try:  # the GUI needs tkinter; keep the package importable without it
    from .gui import (  # noqa: F401
        App, OverlayDialog, PasteDialog, ExcelImportDialog,
        FolderImportDialog, APP_TITLE, HELP_TEXT, main,
    )
except Exception as _gui_exc:                              # pragma: no cover
    _GUI_IMPORT_ERROR = _gui_exc
