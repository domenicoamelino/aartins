#!/usr/bin/env python3
"""Run the current review/approval/report regression suite independently."""
from pathlib import Path
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
raise SystemExit(subprocess.run([sys.executable,'-m','unittest','discover','-s','review_tests','-v'],cwd=root).returncode)
