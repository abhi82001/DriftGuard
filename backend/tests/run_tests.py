#!/usr/bin/env python3
"""Run the backend evaluation-engine test suite (no third-party dependency).

Run:  python backend/tests/run_tests.py
Exit code 0 = pass, 1 = failures.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_evaluation_engine as suite  # noqa: E402

if __name__ == "__main__":
    print("evaluation engine:")
    sys.exit(1 if suite.run() else 0)
