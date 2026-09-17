#!/usr/bin/env python3
"""Run the backend evaluation-engine test suite (no third-party dependency).

Run:  python backend/tests/run_tests.py
Exit code 0 = pass, 1 = failures.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_evaluation_engine as engine_suite  # noqa: E402
import test_semantic_contract as semantic_suite  # noqa: E402
import test_semantic_execution as execution_suite  # noqa: E402
import test_claude_provider as claude_suite  # noqa: E402
import test_mvp_app as mvp_suite  # noqa: E402
import test_documents as documents_suite  # noqa: E402

if __name__ == "__main__":
    print("evaluation engine:")
    failed = engine_suite.run()
    print("\nsemantic contract:")
    failed += semantic_suite.run()
    print("\nsemantic execution:")
    failed += execution_suite.run()
    print("\nclaude provider adapter:")
    failed += claude_suite.run()
    print("\nmvp app:")
    failed += mvp_suite.run()
    print("\ndocument analysis:")
    failed += documents_suite.run()
    sys.exit(1 if failed else 0)
