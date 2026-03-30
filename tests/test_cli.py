from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import typer

from jdv.cli import main


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"


def test_help_runs(tmp_path) -> None:
    result = _run_cli(tmp_path, "--help")

    assert result.returncode == 0
    assert "--view" in result.stdout
    assert "--color" in result.stdout
    assert "--version" in result.stdout


def test_version_runs(tmp_path) -> None:
    result = _run_cli(tmp_path, "--version")

    assert result.returncode == 0
    assert result.stdout == "jdv 2.1.0\n"
    assert result.stderr == ""


def test_zero_diff_prints_nothing_in_non_tty(tmp_path, capsys) -> None:
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps({"b": 2, "a": 1}), encoding="utf-8")
    new_path.write_text(json.dumps({"a": 1, "b": 2}), encoding="utf-8")

    with pytest.raises(typer.Exit) as exit_info:
        main(str(old_path), str(new_path), color="auto", view="compact", quiet=False, match_key=None)

    captured = capsys.readouterr()
    assert exit_info.value.exit_code == 0
    assert captured.out == ""
    assert captured.err == ""


def test_zero_diff_tty_notice_respects_quiet(tmp_path, monkeypatch, capsys) -> None:
    path = tmp_path / "same.json"
    path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    with pytest.raises(typer.Exit) as exit_info:
        main(str(path), str(path), color="auto", view="compact", quiet=False, match_key=None)
    captured = capsys.readouterr()
    assert exit_info.value.exit_code == 0
    assert captured.out == ""
    assert captured.err == "No semantic differences.\n"

    with pytest.raises(typer.Exit) as exit_info:
        main(str(path), str(path), color="auto", view="compact", quiet=True, match_key=None)
    captured = capsys.readouterr()
    assert exit_info.value.exit_code == 0
    assert captured.out == ""
    assert captured.err == ""


def test_zero_diff_focus_and_full_print_nothing_in_non_tty(tmp_path) -> None:
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps({"b": 2, "a": 1}), encoding="utf-8")
    new_path.write_text(json.dumps({"a": 1, "b": 2}), encoding="utf-8")

    for view in ("focus", "full"):
        result = _run_cli(tmp_path, "--view", view, str(old_path), str(new_path))
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""


def test_zero_diff_focus_and_full_tty_notice(tmp_path, monkeypatch, capsys) -> None:
    path = tmp_path / "same.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    for view in ("focus", "full"):
        with pytest.raises(typer.Exit) as exit_info:
            main(str(path), str(path), color="auto", view=view, quiet=False, match_key=None)
        captured = capsys.readouterr()
        assert exit_info.value.exit_code == 0
        assert captured.out == ""
        assert captured.err == "No semantic differences.\n"


def test_invalid_view_returns_usage_error(tmp_path, capsys) -> None:
    path = tmp_path / "same.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(typer.Exit) as exit_info:
        main(str(path), str(path), color="auto", view="weird", quiet=False, match_key=None)

    captured = capsys.readouterr()
    assert exit_info.value.exit_code == 2
    assert "Invalid --view value" in captured.err


def test_invalid_color_returns_usage_error(tmp_path, capsys) -> None:
    path = tmp_path / "same.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(typer.Exit) as exit_info:
        main(str(path), str(path), color="weird", view="compact", quiet=False, match_key=None)

    captured = capsys.readouterr()
    assert exit_info.value.exit_code == 2
    assert "Invalid --color value" in captured.err


def test_match_key_tab_and_space_only_returns_usage_error(tmp_path) -> None:
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text("{}", encoding="utf-8")
    new_path.write_text("{}", encoding="utf-8")

    result = _run_cli(tmp_path, "--match-key", "\t  \t", str(old_path), str(new_path))

    assert result.returncode == 2
    assert "--match-key must not be empty" in result.stderr


def test_cli_renders_exact_value_move(tmp_path) -> None:
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps({"items": [{"x": 1}, {"y": 2}]}), encoding="utf-8")
    new_path.write_text(json.dumps({"items": [{"y": 2}, {"x": 1}]}), encoding="utf-8")

    result = _run_cli(tmp_path, str(old_path), str(new_path))

    assert result.returncode == 0
    assert "> moved $.items[0] -> $.items[1] (exact value)" in result.stdout


def test_cli_custom_match_key_matches_modified_object(tmp_path) -> None:
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps({"items": [{"sku": "svc-a", "v": 1}]}), encoding="utf-8")
    new_path.write_text(json.dumps({"items": [{"sku": "svc-a", "v": 2}]}), encoding="utf-8")

    result = _run_cli(tmp_path, "--match-key", "sku", str(old_path), str(new_path))

    assert result.returncode == 0
    assert '~ "v": 1 -> 2' in result.stdout
    assert '> removed ' not in result.stdout


def test_cli_numeric_type_difference_is_not_zero_diff(tmp_path) -> None:
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text("1", encoding="utf-8")
    new_path.write_text("1.0", encoding="utf-8")

    result = _run_cli(tmp_path, str(old_path), str(new_path))

    assert result.returncode == 0
    assert "~ $: 1 -> 1.0" in result.stdout


def test_cli_equivalent_float_lexemes_are_zero_diff(tmp_path) -> None:
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text("1.0", encoding="utf-8")
    new_path.write_text("1e0", encoding="utf-8")

    result = _run_cli(tmp_path, str(old_path), str(new_path))

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_color_always_emits_ansi_for_changed_lines(tmp_path) -> None:
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps({"v": 1}), encoding="utf-8")
    new_path.write_text(json.dumps({"v": 2}), encoding="utf-8")

    result = _run_cli(tmp_path, "--color", "always", str(old_path), str(new_path))

    assert result.returncode == 0
    assert "\x1b[" in result.stdout


def test_color_always_limits_string_ansi_to_label_and_changed_spans(tmp_path) -> None:
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps({"tier": "silver tier"}), encoding="utf-8")
    new_path.write_text(json.dumps({"tier": "gold tier"}), encoding="utf-8")

    result = _run_cli(tmp_path, "--color", "always", str(old_path), str(new_path))

    assert result.returncode == 0
    assert '\x1b[33m~ \x1b[0m\x1b[33m"tier": \x1b[0m' in result.stdout
    assert '\x1b[31m[-silver-]\x1b[0m' in result.stdout
    assert '\x1b[32m[+gold+]\x1b[0m tier' in result.stdout
    assert 'tier\x1b[0m"' not in result.stdout


def test_double_stdin_returns_usage_error(tmp_path) -> None:
    result = _run_cli(tmp_path, "-", "-")

    assert result.returncode == 2
    assert "Only one input may be read from stdin at a time" in result.stderr


def test_missing_file_returns_usage_error(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    existing = tmp_path / "existing.json"
    existing.write_text("{}", encoding="utf-8")
    result = _run_cli(tmp_path, str(missing), str(existing))

    assert result.returncode == 2
    assert (
        "unable to read file" in result.stderr
        or "cannot find the file" in result.stderr.lower()
        or "no such file or directory" in result.stderr.lower()
    )
    assert "old input (" in result.stderr


def test_missing_new_file_reports_new_role(tmp_path) -> None:
    existing = tmp_path / "existing.json"
    missing = tmp_path / "missing.json"
    existing.write_text("{}", encoding="utf-8")
    result = _run_cli(tmp_path, str(existing), str(missing))

    assert result.returncode == 2
    assert "new input (" in result.stderr


def test_invalid_json_returns_usage_error(tmp_path) -> None:
    invalid = tmp_path / "invalid.json"
    valid = tmp_path / "valid.json"
    invalid.write_text("{", encoding="utf-8")
    valid.write_text("{}", encoding="utf-8")

    result = _run_cli(tmp_path, str(invalid), str(valid))

    assert result.returncode == 2
    assert "old input (" in result.stderr
    assert "invalid JSON" in result.stderr


def test_invalid_utf8_returns_usage_error(tmp_path) -> None:
    invalid = tmp_path / "invalid.json"
    valid = tmp_path / "valid.json"
    invalid.write_bytes(b'\xff\xfe\x00')
    valid.write_text("{}", encoding="utf-8")

    result = _run_cli(tmp_path, str(invalid), str(valid))

    assert result.returncode == 2
    assert "old input (" in result.stderr
    assert "invalid UTF-8 input" in result.stderr


def test_invalid_utf8_stdin_returns_usage_error(tmp_path) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text("{}", encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_PATH) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "jdv", "-", str(valid)],
        cwd=tmp_path,
        input=b"\xff\xfe\x00",
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2
    assert b"old input (" in result.stderr
    assert b"invalid UTF-8 input" in result.stderr


def _run_cli(tmp_path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_PATH) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "jdv", *args],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
        env=env,
    )
