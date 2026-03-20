import pytest

from json_diff_cli.cli import build_parser
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
