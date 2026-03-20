import os
from pathlib import Path
from subprocess import run
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def run_cli(*args: str):
    env = {**os.environ, "PYTHONPATH": str(SRC_ROOT)}
    return run(
        [sys.executable, "-m", "json_diff_cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )
