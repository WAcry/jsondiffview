import pytest

from json_diff_cli.cli import build_parser, main
from json_diff_cli.testing import run_cli


def test_help_exits_zero():
    result = run_cli("--help")
    assert result.returncode == 0
    assert "json-diff FILE_A FILE_B" in result.stdout


def test_missing_args_exits_two():
    result = run_cli()
    assert result.returncode == 2


def test_version_exits_zero():
    result = run_cli("--version")
    assert result.returncode == 0


def test_parser_default_view_and_array_mode():
    parser = build_parser()
    args = parser.parse_args(["left.json", "right.json"])
    assert args.view == "full"
    assert args.array_match == "position"


def test_parser_accepts_full_option_surface():
    parser = build_parser()
    args = parser.parse_args(
        [
            "left.json",
            "right.json",
            "--view",
            "focused",
            "--color",
            "never",
            "--array-match",
            "smart",
            "--match",
            "id",
            "--match",
            "name",
            "--match-config",
            "rules.yaml",
            "--context-lines",
            "2",
            "--sort-keys",
            "--quiet",
        ]
    )
    assert args.view == "focused"
    assert args.color == "never"
    assert args.array_match == "smart"
    assert args.match == ["id", "name"]
    assert args.match_config == "rules.yaml"
    assert args.context_lines == 2
    assert args.sort_keys is True
    assert args.quiet is True


def test_parser_rejects_negative_context_lines():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["left.json", "right.json", "--context-lines", "-1"])


def test_renderer_failure_returns_three_without_raising(tmp_path, monkeypatch):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('{"value": 1}', encoding="utf-8")
    right.write_text('{"value": 2}', encoding="utf-8")

    def raise_render_failure(*args, **kwargs):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr("json_diff_cli.cli.render_full", raise_render_failure)

    result = main([str(left), str(right), "--color", "never"])

    assert result == 3


def test_print_failure_returns_three_without_raising(tmp_path, monkeypatch):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('{"value": 1}', encoding="utf-8")
    right.write_text('{"value": 2}', encoding="utf-8")

    def raise_print_failure(*args, **kwargs):
        raise OSError("stdout closed")

    monkeypatch.setattr("builtins.print", raise_print_failure)

    result = main([str(left), str(right), "--color", "never"])

    assert result == 3
