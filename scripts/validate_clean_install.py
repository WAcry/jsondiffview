"""Install the exact wheel outside the checkout and verify the v3 identity."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NAME = "jsondiffview"
VERSION = "3.0.0"
WHEEL_NAME = f"{NAME}-{VERSION}-py3-none-any.whl"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "wheel",
        nargs="?",
        type=Path,
        default=Path("dist"),
        help="Exact wheel or directory containing it.",
    )
    arguments = parser.parse_args()
    wheel = (
        arguments.wheel / WHEEL_NAME if arguments.wheel.is_dir() else arguments.wheel
    ).resolve()
    assert wheel.name == WHEEL_NAME
    assert wheel.is_file()

    with tempfile.TemporaryDirectory(prefix="jsondiffview-clean-") as raw:
        root = Path(raw)
        environment_path = root / "environment"
        work = root / "work"
        work.mkdir()
        subprocess.run(
            [sys.executable, "-m", "venv", str(environment_path)],
            check=True,
        )
        python, scripts = _environment_paths(environment_path)
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--only-binary=:all:",
                str(wheel),
            ],
            check=True,
        )
        subprocess.run(
            [str(python), "-m", "pip", "check"],
            check=True,
        )
        environment = _clean_environment(environment_path, scripts)
        _validate_metadata_identity(python, work, environment)
        _validate_entry_points(python, scripts, work, environment)
        _validate_negative_identities(python, scripts, work, environment)

    print(f"clean-install validation passed for {wheel.name}")
    return 0


def _environment_paths(environment: Path) -> tuple[Path, Path]:
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    assert python.is_file()
    return python, scripts


def _clean_environment(environment: Path, scripts: Path) -> dict[str, str]:
    result = os.environ.copy()
    result.pop("PYTHONHOME", None)
    result["PYTHONPATH"] = ""
    result["VIRTUAL_ENV"] = str(environment)
    result["PATH"] = str(scripts)
    result["NO_COLOR"] = "1"
    return result


def _validate_metadata_identity(
    python: Path,
    work: Path,
    environment: dict[str, str],
) -> None:
    code = """
import importlib.metadata
import importlib.util
import jsondiffview

assert importlib.metadata.version("jsondiffview") == "3.0.0"
assert jsondiffview.__version__ == "3.0.0"
assert importlib.util.find_spec("jsondiffview") is not None
for name in ("jdv", "jsondiff", "jsondiff_review"):
    assert importlib.util.find_spec(name) is None, name

distribution = importlib.metadata.distribution("jsondiffview")
assert distribution.metadata.get_all("Import-Name") == ["jsondiffview"]
scripts = [
    (entry.name, entry.value)
    for entry in distribution.entry_points
    if entry.group == "console_scripts"
]
assert scripts == [("jdv", "jsondiffview.cli:main")], scripts
for name in ("jdv", "jsondiff", "jsondiff-review", "jsondiff_review"):
    try:
        importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise AssertionError(f"legacy distribution alias is installed: {name}")
"""
    _run([str(python), "-c", code], work, environment, 0)


def _validate_entry_points(
    python: Path,
    scripts: Path,
    work: Path,
    environment: dict[str, str],
) -> None:
    command = scripts / ("jdv.exe" if os.name == "nt" else "jdv")
    assert command.is_file()
    old = work / "old.json"
    new = work / "new.json"
    invalid = work / "invalid.json"
    old.write_text('{"value":1}', encoding="utf-8")
    new.write_text('{"value":2}', encoding="utf-8")
    invalid.write_text('{"value":}', encoding="utf-8")

    for prefix in ([str(command)], [str(python), "-m", "jsondiffview"]):
        version = _run([*prefix, "--version"], work, environment, 0)
        assert version.stdout == b"jdv 3.0.0\n"
        assert version.stderr == b""
        for help_option in ("-h", "--help"):
            help_result = _run(
                [*prefix, help_option],
                work,
                environment,
                0,
            )
            assert b"Usage: jdv [OPTIONS] OLD_JSON NEW_JSON" in help_result.stdout
            assert help_result.stderr == b""

        equal = _run([*prefix, str(old), str(old)], work, environment, 0)
        assert equal.stdout == b""
        assert equal.stderr == b"No semantic differences.\n"
        different = _run(
            [*prefix, "--color", "never", str(old), str(new)],
            work,
            environment,
            1,
        )
        assert b'"value": 1 -> 2' in different.stdout
        assert different.stderr == b""
        error = _run(
            [*prefix, str(invalid), str(new)],
            work,
            environment,
            2,
        )
        assert error.stdout == b""
        assert error.stderr.startswith(b"jdv: error:")
        assert b"Traceback" not in error.stderr

        for legacy_view in ("compact", "focus"):
            legacy = _run(
                [
                    *prefix,
                    "--view",
                    legacy_view,
                    str(old),
                    str(new),
                ],
                work,
                environment,
                2,
            )
            assert legacy.stdout == b""
            assert b"Invalid value" in legacy.stderr


def _validate_negative_identities(
    python: Path,
    scripts: Path,
    work: Path,
    environment: dict[str, str],
) -> None:
    for module in ("jdv", "jsondiff", "jsondiff_review"):
        result = _run(
            [str(python), "-m", module],
            work,
            environment,
            None,
        )
        assert result.returncode != 0
    for command in ("jsondiff", "jsondiff-review", "jsondiff_review"):
        assert shutil.which(command, path=str(scripts)) is None


def _run(
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
    expected_status: int | None,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        check=False,
    )
    if expected_status is not None:
        assert result.returncode == expected_status, (
            command,
            result.returncode,
            result.stdout,
            result.stderr,
        )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
