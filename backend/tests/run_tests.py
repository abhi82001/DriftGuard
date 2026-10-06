#!/usr/bin/env python3
"""Run the complete DriftGuard test suite with a trustworthy aggregate summary."""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
env=os.environ.copy(); src=str(ROOT/'backend'/'src'); env['PYTHONPATH']=src+(os.pathsep+env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
try:
    import pytest  # noqa: F401
except ImportError:
    raise SystemExit("pytest is not installed. Run: pip install -r requirements-dev.txt")
cmd=[sys.executable,'-m','pytest','-ra','backend/tests','knowledge/soc2/tests']
print('DriftGuard complete test suite:', ' '.join(cmd), flush=True)
proc=subprocess.run(cmd,cwd=ROOT,env=env)
print(f"\nDRIFTGUARD TEST TOTAL: exit_code={proc.returncode} (pytest summary above is authoritative)", flush=True)
raise SystemExit(proc.returncode)
