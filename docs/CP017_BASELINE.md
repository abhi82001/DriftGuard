# CP017 Baseline

Source: exact CP016 packaged tree.

Command: `PYTHONPATH=backend/src python -m pytest -q`

Measured baseline: **522 passed, 0 failed**.

Note: running pytest without the source path caused two collection import errors in CP016 generalization tests. This is a run-context issue, not a product regression.
