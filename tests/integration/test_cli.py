from __future__ import annotations

import errno
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Any, BinaryIO

import pytest

import jsondiffview
from jsondiffview import cli
from jsondiffview.model import ColorMode, OutputError
from jsondiffview.parser import CONTAINER_DEPTH_LIMIT, DECIMAL_LEXEME_LIMIT

_ANSI_PATTERN = re.compile(rb"\x1b\[[0-9;]*m")


def run_module(
    arguments: list[str],
    *,
    input_bytes: bytes | None = None,
    cwd: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    if environment is not None:
        env.update(environment)
    return subprocess.run(
        [sys.executable, "-m", "jsondiffview", *arguments],
        input=input_bytes,
        capture_output=True,
        cwd=cwd,
        env=env,
        check=False,
    )


def write_pair(tmp_path: Path, old: bytes, new: bytes) -> tuple[Path, Path]:
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_bytes(old)
    new_path.write_bytes(new)
    return old_path, new_path


def test_project_metadata_exposes_only_current_identity() -> None:
    project_root = Path(__file__).parents[2]
    metadata = tomllib.loads(
        (project_root / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert metadata["project"]["name"] == "jsondiffview"
    assert metadata["project"]["version"] == "3.0.0"
    assert metadata["project"]["license"] == "MIT"
    assert metadata["project"]["license-files"] == ["LICENSE"]
    assert metadata["project"]["import-names"] == ["jsondiffview"]
    assert metadata["project"]["scripts"] == {"jdv": "jsondiffview.cli:main"}
    assert metadata["project"]["dependencies"] == [
        "click>=8.4.2,<8.5",
        "regex==2026.6.28",
        "wcwidth==0.8.2",
    ]
    assert metadata["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/jsondiffview"
    ]
    assert (
        metadata["tool"]["hatch"]["build"]["targets"]["wheel"]["core-metadata-version"]
        == "2.5"
    )
    assert (
        metadata["tool"]["hatch"]["build"]["targets"]["sdist"]["core-metadata-version"]
        == "2.5"
    )
    assert metadata["tool"]["hatch"]["build"]["targets"]["sdist"]["include"] == [
        "/LICENSE",
        "/MIGRATING.md",
        "/README.md",
        "/benchmarks",
        "/playground",
        "/pyproject.toml",
        "/src",
        "/tests",
        "/uv.lock",
    ]
    assert (project_root / "LICENSE").is_file()
    assert (project_root / "MIGRATING.md").is_file()
    assert (project_root / "src" / "jsondiffview").is_dir()
    assert not (project_root / "src" / "jdv").exists()
    assert not (project_root / "src" / "jsondiff").exists()
    assert not (project_root / "src" / "jsondiff_review").exists()
    assert importlib.util.find_spec("jsondiffview") is not None
    assert importlib.util.find_spec("jdv") is None
    assert importlib.util.find_spec("jsondiff") is None
    assert importlib.util.find_spec("jsondiff_review") is None


def test_readme_uses_public_screenshot_url() -> None:
    project_root = Path(__file__).parents[2]
    readme = (project_root / "README.md").read_text(encoding="utf-8")
    screenshot = project_root / "playground" / "jdv-review.png"
    screenshot_url = (
        "https://raw.githubusercontent.com/WAcry/jsondiffview/"
        "main/playground/jdv-review.png"
    )
    screenshot_markdown = (
        "![Terminal screenshot of jdv reviewing nested JSON changes, moves, "
        f"additions, and removals]({screenshot_url})"
    )

    assert readme.count(screenshot_markdown) == 1
    assert readme.count("jdv-review.png") == 1
    assert (
        readme.index("The output is annotated review text")
        < readme.index(screenshot_markdown)
        < readme.index("> The package published on PyPI")
    )
    assert hashlib.sha256(screenshot.read_bytes()).hexdigest() == (
        "a9afbbd91e16f750fa6e7bdf2e78b9d940826715451cee79702d9c36d1dbb281"
    )


def test_authored_and_installed_versions_agree() -> None:
    project_root = Path(__file__).parents[2]
    metadata = tomllib.loads(
        (project_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert metadata["project"]["version"] == "3.0.0"
    assert distribution_version("jsondiffview") == "3.0.0"
    assert jsondiffview.__version__ == "3.0.0"
    assert (project_root / "uv.lock").read_text(encoding="utf-8").count(
        'name = "jsondiffview"\nversion = "3.0.0"'
    ) == 1


def test_equal_and_quiet_stream_status_contract(tmp_path: Path) -> None:
    old, new = write_pair(tmp_path, b'{"value":1}', b'{"value":1}')

    result = run_module([str(old), str(new)])
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b"No semantic differences.\n"

    quiet = run_module(["--quiet", str(old), str(new)])
    assert quiet.returncode == 0
    assert quiet.stdout == b""
    assert quiet.stderr == b""


def test_difference_uses_stdout_lf_and_status_one(tmp_path: Path) -> None:
    old, new = write_pair(
        tmp_path,
        '{"name":"caf\u00e9","count":1}'.encode(),
        '{"name":"caf\u00e9 team","count":2}'.encode(),
    )
    result = run_module(["--color", "never", str(old), str(new)])
    assert result.returncode == 1
    assert result.stderr == b""
    assert b"caf\xc3\xa9" in result.stdout
    assert result.stdout.endswith(b"\n")
    assert b"\r\n" not in result.stdout


def test_stdin_and_optional_bom_follow_the_file_decode_path(tmp_path: Path) -> None:
    _, new = write_pair(
        tmp_path,
        b"unused",
        b'\xef\xbb\xbf{"value":2}',
    )
    result = run_module(["-", str(new)], input_bytes=b'{"value":1}')
    assert result.returncode == 1
    assert b'"value": 1 -> 2' in result.stdout
    assert result.stderr == b""


def test_both_inputs_cannot_use_stdin() -> None:
    result = run_module(["-", "-"], input_bytes=b"{}")
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == (
        b"jdv: error: OLD_JSON and NEW_JSON cannot both use stdin.\n"
    )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b'{"id":1,"id":2}', b"duplicate object key"),
        (b"NaN", b"non-finite number"),
        (b"1e999", b"supported finite range"),
        (b'{"broken":}', b"invalid JSON at line"),
        (b'"\xff"', b"invalid UTF-8"),
    ],
)
def test_invalid_inputs_are_concise_status_two_errors(
    tmp_path: Path,
    payload: bytes,
    message: bytes,
) -> None:
    old, new = write_pair(tmp_path, payload, b"null")
    result = run_module([str(old), str(new)])
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr.startswith(b"jdv: error: ")
    assert message in result.stderr
    assert result.stderr.endswith(b"\n")
    assert b"Traceback" not in result.stderr


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            (
                "[" * (CONTAINER_DEPTH_LIMIT + 1)
                + "0"
                + "]" * (CONTAINER_DEPTH_LIMIT + 1)
            ).encode(),
            b"container nesting exceeds",
        ),
        (
            ("0." + "1" * (DECIMAL_LEXEME_LIMIT - 1)).encode(),
            b"decimal lexeme exceeds",
        ),
    ],
)
def test_resource_limit_errors_are_status_two(
    tmp_path: Path,
    payload: bytes,
    message: bytes,
) -> None:
    old, new = write_pair(tmp_path, payload, b"null")
    result = run_module([str(old), str(new)])
    assert result.returncode == 2
    assert result.stdout == b""
    assert message in result.stderr
    assert b"Traceback" not in result.stderr


def test_missing_file_is_a_stable_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    result = run_module([str(missing), str(missing)])
    assert result.returncode == 2
    assert result.stdout == b""
    assert b"input file was not found" in result.stderr


def test_duplicate_match_keys_and_case_sensitive_choices_are_errors(
    tmp_path: Path,
) -> None:
    old, new = write_pair(tmp_path, b"{}", b'{"new":1}')
    duplicate = run_module(["-k", "id", "-k", "id", str(old), str(new)])
    assert duplicate.returncode == 2
    assert b"duplicate --match-key value 'id'" in duplicate.stderr

    long_key = "k" * 1_000
    long_duplicate = run_module(["-k", long_key, "-k", long_key, str(old), str(new)])
    assert long_duplicate.returncode == 2
    assert len(long_duplicate.stderr) < 500
    assert b"920 code points omitted" in long_duplicate.stderr

    invalid_choice = run_module(["--view", "Review", str(old), str(new)])
    assert invalid_choice.returncode == 2
    assert b"Invalid value for '-v' / '--view'" in invalid_choice.stderr

    oversized_choice = "R" * 10_000
    oversized = run_module(["--view", oversized_choice, str(old), str(new)])
    assert oversized.returncode == 2
    assert len(oversized.stderr) < 1_000
    assert b"code points omitted" in oversized.stderr
    assert oversized_choice.encode() not in oversized.stderr


@pytest.mark.parametrize("legacy_view", ["compact", "focus"])
def test_legacy_views_are_hard_errors(
    tmp_path: Path,
    legacy_view: str,
) -> None:
    old, new = write_pair(tmp_path, b"1", b"2")
    result = run_module(["--view", legacy_view, str(old), str(new)])
    assert result.returncode == 2
    assert result.stdout == b""
    assert b"Invalid value for '-v' / '--view'" in result.stderr


def test_custom_match_key_replaces_defaults(tmp_path: Path) -> None:
    old, new = write_pair(
        tmp_path,
        b'[{"id":"old","sku":"x","value":1}]',
        b'[{"id":"new","sku":"x","value":2}]',
    )
    default = run_module([str(old), str(new)])
    custom = run_module(["-k", "sku", str(old), str(new)])
    assert default.returncode == custom.returncode == 1
    assert b"[old 0]" in default.stdout
    assert b"[old 0]" not in custom.stdout
    assert b'"value": 1 -> 2' in custom.stdout


def test_summary_review_and_full_options_change_only_projection(
    tmp_path: Path,
) -> None:
    old, new = write_pair(
        tmp_path,
        b'{"a":0,"b":1,"c":2,"d":3,"e":4}',
        b'{"a":0,"b":1,"c":20,"d":3,"e":4}',
    )
    summary = run_module(["-v", "summary", str(old), str(new)])
    review = run_module(["-v", "review", str(old), str(new)])
    full = run_module(["-v", "full", str(old), str(new)])
    assert summary.returncode == review.returncode == full.returncode == 1
    assert b"2 unchanged fields omitted" in summary.stdout
    assert b"1 unchanged field omitted" in review.stdout
    assert b"omitted" not in full.stdout
    assert b'"c": 2 -> 20' in summary.stdout
    assert b'"c": 2 -> 20' in review.stdout
    assert b'"c": 2 -> 20' in full.stdout


def test_plain_output_is_hash_seed_and_terminal_environment_deterministic(
    tmp_path: Path,
) -> None:
    old, new = write_pair(
        tmp_path,
        (
            b'{"items":["a","b","a","b"],'
            b'"payload":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
            b'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}'
        ),
        (
            b'{"items":["b","a","b","a"],'
            b'"payload":"BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB'
            b'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"}'
        ),
    )
    outputs = []
    for seed, terminal in [("1", "Apple_Terminal"), ("7", "WezTerm"), ("99", "")]:
        result = run_module(
            ["--color", "never", str(old), str(new)],
            environment={
                "PYTHONHASHSEED": seed,
                "TERM_PROGRAM": terminal,
            },
        )
        assert result.returncode == 1
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1] == outputs[2]


def test_representative_plain_stream_baseline_hashes(tmp_path: Path) -> None:
    corpus = Path(__file__).parents[1] / "corpus" / "baseline_hashes.jsonl"
    for line in corpus.read_text(encoding="utf-8").splitlines():
        record: dict[str, Any] = json.loads(line)
        case = tmp_path / record["id"]
        case.mkdir()
        old, new = write_pair(
            case,
            record["old_json"].encode(),
            record["new_json"].encode(),
        )
        old_argument = "-" if record.get("old_stdin") else str(old)
        input_bytes = old.read_bytes() if record.get("old_stdin") else None
        result = run_module(
            [*record["options"], old_argument, str(new)],
            input_bytes=input_bytes,
        )
        assert result.returncode == record["status"], record["id"]
        assert hashlib.sha256(result.stdout).hexdigest() == record["stdout_sha256"], (
            record["id"]
        )
        assert hashlib.sha256(result.stderr).hexdigest() == record["stderr_sha256"], (
            record["id"]
        )


def test_color_always_never_and_auto_no_color(tmp_path: Path) -> None:
    old, new = write_pair(tmp_path, b'{"a":"old"}', b'{"a":"new"}')
    colored = run_module(["-c", "always", str(old), str(new)])
    plain = run_module(["-c", "never", str(old), str(new)])
    automatic = run_module(
        [str(old), str(new)],
        environment={"NO_COLOR": "1"},
    )
    assert b"\x1b[" in colored.stdout
    assert b"\x1b[" not in plain.stdout
    assert b"\x1b[" not in automatic.stdout
    assert _ANSI_PATTERN.sub(b"", colored.stdout) == plain.stdout


@pytest.mark.parametrize(
    ("mode", "tty", "no_color", "expected"),
    [
        (ColorMode.AUTO, True, "", True),
        (ColorMode.AUTO, True, "1", False),
        (ColorMode.AUTO, False, "", False),
        (ColorMode.ALWAYS, False, "1", True),
        (ColorMode.NEVER, True, "", False),
    ],
)
def test_color_policy(
    mode: ColorMode,
    tty: bool,
    no_color: str,
    expected: bool,
) -> None:
    class Stream:
        def isatty(self) -> bool:
            return tty

    assert cli.color_enabled(mode, Stream(), {"NO_COLOR": no_color}) is expected


def test_color_policy_reports_terminal_probe_failures() -> None:
    class BrokenStream:
        def isatty(self) -> bool:
            raise OSError("closed")

    with pytest.raises(OutputError, match="inspect review output"):
        cli.color_enabled(ColorMode.AUTO, BrokenStream(), {})


def test_help_version_and_console_entry_point_do_not_read_inputs() -> None:
    help_result = run_module(["-h"])
    version_result = run_module(["--version"])
    assert help_result.returncode == 0
    assert b"Usage: jdv [OPTIONS] OLD_JSON NEW_JSON" in help_result.stdout
    assert b"-h, --help" in help_result.stdout
    assert help_result.stderr == b""
    assert version_result.returncode == 0
    assert version_result.stdout == b"jdv 3.0.0\n"
    assert version_result.stderr == b""

    readme = (Path(__file__).parents[2] / "README.md").read_text(encoding="utf-8")
    assert f"```text\n{help_result.stdout.decode()}```" in readme

    executable = shutil.which("jdv")
    assert executable is not None
    console = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        check=False,
    )
    assert console.returncode == 0
    assert console.stdout == b"jdv 3.0.0\n"


def test_double_dash_allows_option_like_paths(tmp_path: Path) -> None:
    old = tmp_path / "-old.json"
    new = tmp_path / "-new.json"
    old.write_text("1", encoding="utf-8")
    new.write_text("2", encoding="utf-8")
    result = run_module(["--", old.name, new.name], cwd=tmp_path)
    assert result.returncode == 1
    assert result.stdout == b"~ 1 -> 2\n"


class _BrokenBuffer(io.BytesIO):
    def write(self, _data: Any) -> int:
        raise BrokenPipeError(errno.EPIPE, "closed")


class _BrokenStdout(io.StringIO):
    buffer: BinaryIO = _BrokenBuffer()

    def isatty(self) -> bool:
        return False


def test_windows_einval_pipe_mapping_is_classified_narrowly() -> None:
    error = OSError(errno.EINVAL, "invalid argument")
    assert cli._is_broken_pipe(error) is (os.name == "nt")


def test_broken_stdout_pipe_is_silent_status_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old, new = write_pair(tmp_path, b"1", b"2")
    stdout = _BrokenStdout()
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    assert cli.main([str(old), str(new)]) == 2
    assert stderr.getvalue() == ""


def test_preclosed_stdout_is_silent_status_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old, new = write_pair(tmp_path, b"1", b"2")
    stdout = io.StringIO()
    stdout.close()
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    assert cli.main([str(old), str(new)]) == 2
    assert stderr.getvalue() == ""


def test_equality_notice_write_failure_returns_status_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old, new = write_pair(tmp_path, b"1", b"1")
    stdout = io.StringIO()
    stderr = _BrokenStdout()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    assert cli.main([str(old), str(new)]) == 2
    assert stdout.getvalue() == ""


def test_quiet_does_not_suppress_differences_or_errors(tmp_path: Path) -> None:
    old, new = write_pair(tmp_path, b"1", b"2")
    difference = run_module(["--quiet", str(old), str(new)])
    error = run_module(["--quiet", str(tmp_path / "missing"), str(new)])
    assert difference.returncode == 1
    assert difference.stdout
    assert error.returncode == 2
    assert error.stderr
