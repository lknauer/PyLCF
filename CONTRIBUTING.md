# Contributing to PyLCF

Thanks for your interest in improving PyLCF!

## Development setup

```bash
git clone https://github.com/lknauer/pylcf.git
cd pylcf
pip install -r requirements.txt
pip install ruff pytest          # development tools
```

On Linux you also need Tk: `sudo apt install python3-tk`.

## Running the tests

```bash
pytest                            # all tests
python tests/test_features.py     # numeric core only (no display needed)
```

The GUI tests (`test_overlay.py`, `test_slider.py`) require a display. On a
headless machine, use a virtual one:

```bash
xvfb-run -a pytest
```

## Linting

```bash
ruff check .
```

Library code (the `pylcf/` package) is kept lint-clean. Test files use a
relaxed style (configured in `pyproject.toml`).

## Code style & conventions

- Python ≥ 3.9; standard library plus numpy / scipy / matplotlib /
  pandas / openpyxl.
- User-facing strings and the GUI are in English.
- The GUI (`pylcf.gui`) and the CLI (`pylcf.cli`) share the numeric core in
  `pylcf/core.py`, so they stay in sync by construction. Put new numerics in
  `core.py` rather than in the front-ends.

## Releasing

Bump the version in **`pylcf/core.py`** (`APP_VERSION`) and **`pyproject.toml`**,
add an entry to `CHANGELOG.md`, then tag the release (`vX.Y.Z`).

## Reporting issues

Please use the issue templates and include your OS, Python version, PyLCF
version and — if possible — a small example that reproduces the problem.
