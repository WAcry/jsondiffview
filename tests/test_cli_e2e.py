from tests.conftest import run_cli


def test_cli_returns_one_when_diff_exists(tmp_path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('{"capital": "Buenos Aires"}', encoding="utf-8")
    right.write_text('{"capital": "Rawson"}', encoding="utf-8")

    result = run_cli(str(left), str(right), "--view", "focused", "--color", "never")

    assert result.returncode == 1
    assert "capital" in result.stdout
    assert result.stderr == ""


def test_cli_returns_zero_when_no_diff_exists(tmp_path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('{"capital": "Rawson"}', encoding="utf-8")
    right.write_text('{"capital": "Rawson"}', encoding="utf-8")

    result = run_cli(str(left), str(right), "--color", "never")

    assert result.returncode == 0
    assert '"capital": "Rawson"' in result.stdout
    assert result.stderr == ""


def test_invalid_json_returns_two(tmp_path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('{capital: "Rawson"}', encoding="utf-8")
    right.write_text('{"capital": "Rawson"}', encoding="utf-8")

    result = run_cli(str(left), str(right))

    assert result.returncode == 2


def test_cli_honors_sort_keys_in_focused_mode(tmp_path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('{"b": 1, "a": 2}', encoding="utf-8")
    right.write_text('{"b": 3, "a": 4}', encoding="utf-8")

    result = run_cli(
        str(left),
        str(right),
        "--view",
        "focused",
        "--sort-keys",
        "--color",
        "never",
    )

    assert result.returncode == 1
    assert result.stdout.index('"a": [-2-][+4+],') < result.stdout.index('"b": [-1-][+3+]')
