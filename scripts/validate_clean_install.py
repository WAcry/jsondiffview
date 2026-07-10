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
        help="Exact wheel or directory containing it.",
    )
    parser.add_argument(
        "--pypi-version",
        help="Install this exact version from the production PyPI index.",
    )
    arguments = parser.parse_args()
    if arguments.pypi_version is not None:
        assert arguments.wheel is None, (
            "wheel and --pypi-version are mutually exclusive"
        )
        assert arguments.pypi_version == VERSION
        wheel: Path | None = None
        version = arguments.pypi_version
    else:
        wheel_argument = arguments.wheel or Path("dist")
        wheel = (
            wheel_argument / WHEEL_NAME if wheel_argument.is_dir() else wheel_argument
        ).resolve()
        assert wheel.name == WHEEL_NAME
        assert wheel.is_file()
        version = VERSION

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
        environment = _clean_environment(environment_path, scripts)
        index_arguments = [
            "--index-url",
            "https://pypi.org/simple/",
            "--no-cache-dir",
            "--retries",
            "5",
            "--timeout",
            "15",
        ]
        install_target = f"{NAME}=={version}" if wheel is None else str(wheel)
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "--isolated",
                "install",
                *index_arguments,
                "--keyring-provider",
                "disabled",
                "--no-input",
                "--only-binary=:all:",
                install_target,
            ],
            env=environment,
            check=True,
        )
        subprocess.run(
            [str(python), "-m", "pip", "--isolated", "check"],
            env=environment,
            check=True,
        )
        _validate_metadata_identity(python, work, environment, version)
        _validate_entry_points(python, scripts, work, environment, version)
        _validate_negative_identities(python, scripts, work, environment)

    source = wheel.name if wheel is not None else f"PyPI {NAME}=={version}"
    print(f"clean-install validation passed for {source}")
    return 0


def _environment_paths(environment: Path) -> tuple[Path, Path]:
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    assert python.is_file()
    return python, scripts


def _clean_environment(environment: Path, scripts: Path) -> dict[str, str]:
    result = os.environ.copy()
    result.pop("PYTHONHOME", None)
    for name in tuple(result):
        if name.startswith(("PIP_", "UV_INDEX", "UV_DEFAULT_INDEX")):
            result.pop(name)
    result["PYTHONPATH"] = ""
    result["PYTHONNOUSERSITE"] = "1"
    home = environment.parent / "home"
    home.mkdir()
    result["HOME"] = str(home)
    result["USERPROFILE"] = str(home)
    result["XDG_CONFIG_HOME"] = str(home / ".config")
    result["VIRTUAL_ENV"] = str(environment)
    result["PATH"] = str(scripts)
    result["NO_COLOR"] = "1"
    return result


def _validate_metadata_identity(
    python: Path,
    work: Path,
    environment: dict[str, str],
    version: str,
) -> None:
    code = f"""
import importlib.metadata
import importlib.util
import jsondiffview

assert importlib.metadata.version("jsondiffview") == {version!r}
assert jsondiffview.__version__ == {version!r}
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
        raise AssertionError(f"legacy distribution alias is installed: {{name}}")
"""
    _run([str(python), "-c", code], work, environment, 0)


def _validate_entry_points(
    python: Path,
    scripts: Path,
    work: Path,
    environment: dict[str, str],
    version: str,
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
        version_result = _run([*prefix, "--version"], work, environment, 0)
        assert version_result.stdout == f"jdv {version}\n".encode()
        assert version_result.stderr == b""
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
