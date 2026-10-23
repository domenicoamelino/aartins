#!/usr/bin/env python3
"""Run independent stdlib suites without module-name/path collisions."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
commands = [(root, ["-m", "unittest", "discover", "-s", "review_tests", "-v"]),
            (root, ["-m", "unittest", "discover", "-s", "tests", "-v"]),
            (root / "ingestion", ["-m", "unittest", "-v", "test_ingestion"]),
            (root / "monitoring", ["-m", "unittest", "-v", "test_monitor", "test_telegram"])]
failed = []
for cwd, args in commands:
    print("Checking", cwd.name, flush=True)
    result = subprocess.run([sys.executable, *args], cwd=cwd)
    if result.returncode:
        failed.append(str(cwd))
if failed:
    print("Failed suites:", ", ".join(failed), flush=True)
    raise SystemExit(1)
print("All offline suites passed.")
