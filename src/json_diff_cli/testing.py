import os
from pathlib import Path
from subprocess import run
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"


def run_cli(*args: str):
    env = {**os.environ, "PYTHONPATH": str(SRC_ROOT)}
    return run(
        [sys.executable, "-m", "json_diff_cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )
