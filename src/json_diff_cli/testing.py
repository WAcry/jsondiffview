import os
from pathlib import Path
from subprocess import run
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"


def run_cli(*args: str):
    existing_pythonpath = os.environ.get("PYTHONPATH")
    pythonpath = (
        str(SRC_ROOT)
        if not existing_pythonpath
        else os.pathsep.join([str(SRC_ROOT), existing_pythonpath])
    )
    env = {**os.environ, "PYTHONPATH": pythonpath}
    return run(
        [sys.executable, "-m", "json_diff_cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )
