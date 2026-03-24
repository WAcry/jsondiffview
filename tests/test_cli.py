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


def test_invalid_view_returns_usage_error(tmp_path, capsys) -> None:
    path = tmp_path / "same.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(typer.Exit) as exit_info:
        main(str(path), str(path), color="auto", view="weird", quiet=False, match_key=None)

    captured = capsys.readouterr()
    assert exit_info.value.exit_code == 2
    assert "Invalid --view value" in captured.err


def test_cli_renders_exact_value_move(tmp_path) -> None:
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps({"items": [{"x": 1}, {"y": 2}]}), encoding="utf-8")
    new_path.write_text(json.dumps({"items": [{"y": 2}, {"x": 1}]}), encoding="utf-8")

    result = _run_cli(tmp_path, str(old_path), str(new_path))

    assert result.returncode == 0
    assert "> moved $.items[0] -> $.items[1] (exact value)" in result.stdout


def test_color_always_emits_ansi_for_changed_lines(tmp_path) -> None:
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps({"v": 1}), encoding="utf-8")
    new_path.write_text(json.dumps({"v": 2}), encoding="utf-8")

    result = _run_cli(tmp_path, "--color", "always", str(old_path), str(new_path))

    assert result.returncode == 0
    assert "\x1b[" in result.stdout


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
