from json_diff_cli.testing import run_cli


def test_cli_returns_one_when_diff_exists(tmp_path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('{"capital": "Buenos Aires"}', encoding="utf-8")
    right.write_text('{"capital": "Rawson"}', encoding="utf-8")

    result = run_cli(str(left), str(right), "--view", "changed", "--color", "never")

    assert result.returncode == 1
    assert "capital (replace)" in result.stdout
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


def test_cli_honors_sort_keys_in_changed_mode(tmp_path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('{"b": 1, "a": 2}', encoding="utf-8")
    right.write_text('{"b": 3, "a": 4}', encoding="utf-8")

    result = run_cli(
        str(left),
        str(right),
        "--view",
        "changed",
        "--sort-keys",
        "--color",
        "never",
    )

    assert result.returncode == 1
    assert result.stdout.index("b (replace)") < result.stdout.index("a (replace)")


def test_cli_changed_view_uses_fragment_aware_string_preview(tmp_path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('{"word": "english"}', encoding="utf-8")
    right.write_text('{"word": "inglés"}', encoding="utf-8")

    result = run_cli(str(left), str(right), "--view", "changed", "--color", "never")

    assert result.returncode == 1
    assert 'old: "english"' not in result.stdout
    assert 'new: "inglés"' not in result.stdout
    assert "[-" in result.stdout
    assert "[+" in result.stdout


def test_cli_changed_view_sorts_added_object_preview(tmp_path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text("{}", encoding="utf-8")
    right.write_text('{"obj": {"b": 1, "a": 2}}', encoding="utf-8")

    result = run_cli(
        str(left),
        str(right),
        "--view",
        "changed",
        "--sort-keys",
        "--color",
        "never",
    )

    assert result.returncode == 1
    assert 'new: {"a": 2, "b": 1}' in result.stdout


def test_quiet_mode_still_returns_one_without_stdout(tmp_path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('{"capital": "Buenos Aires"}', encoding="utf-8")
    right.write_text('{"capital": "Rawson"}', encoding="utf-8")

    result = run_cli(str(left), str(right), "--quiet")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == ""


def test_invalid_yaml_config_returns_two_with_stderr(tmp_path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    config = tmp_path / "rules.yaml"
    left.write_text('{"capital": "Buenos Aires"}', encoding="utf-8")
    right.write_text('{"capital": "Rawson"}', encoding="utf-8")
    config.write_text("global_matches: [", encoding="utf-8")

    result = run_cli(
        str(left),
        str(right),
        "--match-config",
        str(config),
    )

    assert result.returncode == 2
    assert "Invalid YAML:" in result.stderr
    assert "line" in result.stderr
    assert result.stdout == ""


def test_invalid_match_config_shape_returns_two_with_file_path(tmp_path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    config = tmp_path / "rules.yaml"
    left.write_text('{"capital": "Buenos Aires"}', encoding="utf-8")
    right.write_text('{"capital": "Rawson"}', encoding="utf-8")
    config.write_text("global_matches: id\n", encoding="utf-8")

    result = run_cli(
        str(left),
        str(right),
        "--match-config",
        str(config),
    )

    assert result.returncode == 2
    assert "rules.yaml" in result.stderr
    assert "global_matches" in result.stderr
    assert result.stdout == ""
