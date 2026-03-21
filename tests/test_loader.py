import pytest

from jsondiffview_errors import UserInputError
from jsondiffview_loader import load_json_file, load_match_config


def test_load_json_file_reads_strict_json(tmp_path):
    path = tmp_path / "left.json"
    path.write_text('{"id": 1, "name": "Argentina"}', encoding="utf-8")

    assert load_json_file(path) == {"id": 1, "name": "Argentina"}


def test_invalid_json_raises_user_input_error(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{id: 1}", encoding="utf-8")

    with pytest.raises(UserInputError, match="Invalid JSON"):
        load_json_file(path)


def test_invalid_json_error_includes_line_and_column(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{\n  "a": 1,\n}\n', encoding="utf-8")

    with pytest.raises(UserInputError) as exc_info:
        load_json_file(path)

    message = str(exc_info.value)
    assert "broken.json" in message
    assert "line " in message
    assert "column " in message


def test_non_standard_json_constant_raises_user_input_error(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"value": NaN}', encoding="utf-8")

    with pytest.raises(UserInputError, match="Invalid JSON"):
        load_json_file(path)


def test_duplicate_json_object_keys_raise_user_input_error(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"a": 1, "a": 2}', encoding="utf-8")

    with pytest.raises(UserInputError, match="Invalid JSON"):
        load_json_file(path)


def test_load_match_config_reads_yaml_with_composite_groups(tmp_path):
    path = tmp_path / "match.yaml"
    path.write_text("global_matches:\n  - [id, source]\n  - id\n", encoding="utf-8")

    assert load_match_config(path).global_matches == [["id", "source"], ["id"]]


def test_dotted_key_path_group_is_preserved(tmp_path):
    path = tmp_path / "match.yaml"
    path.write_text(
        "path_matches:\n  countries:\n    - [identity.id, identity.source]\n",
        encoding="utf-8",
    )

    assert load_match_config(path).path_matches["countries"] == [
        ["identity.id", "identity.source"]
    ]


def test_invalid_yaml_raises_user_input_error(tmp_path):
    path = tmp_path / "match.yaml"
    path.write_text("global_matches: [", encoding="utf-8")

    with pytest.raises(UserInputError, match="Invalid YAML"):
        load_match_config(path)


def test_invalid_yaml_error_includes_line_and_column(tmp_path):
    path = tmp_path / "match.yaml"
    path.write_text("global_matches:\n  - [id,\n", encoding="utf-8")

    with pytest.raises(
        UserInputError,
        match=r"match\.yaml.*line 3.*column 1",
    ):
        load_match_config(path)


def test_duplicate_yaml_keys_raise_user_input_error(tmp_path):
    path = tmp_path / "match.yaml"
    path.write_text(
        "global_matches:\n  - id\npath_matches:\n  countries:\n    - id\npath_matches:\n"
        "  cities:\n    - name\n",
        encoding="utf-8",
    )

    with pytest.raises(UserInputError, match=r"match\.yaml.*Duplicate YAML key"):
        load_match_config(path)


def test_unhashable_yaml_key_raises_user_input_error(tmp_path):
    path = tmp_path / "match.yaml"
    path.write_text(
        "path_matches:\n  ? [countries, cities]\n  :\n    - id\n",
        encoding="utf-8",
    )

    with pytest.raises(UserInputError, match=r"match\.yaml.*YAML key"):
        load_match_config(path)


def test_invalid_match_config_shape_raises_user_input_error(tmp_path):
    path = tmp_path / "match.yaml"
    path.write_text("global_matches: id\n", encoding="utf-8")

    with pytest.raises(UserInputError, match=r"match\.yaml.*global_matches"):
        load_match_config(path)


def test_invalid_match_path_in_config_includes_file_path(tmp_path):
    path = tmp_path / "match.yaml"
    path.write_text(
        "path_matches:\n  countries[0].cities:\n    - id\n",
        encoding="utf-8",
    )

    with pytest.raises(UserInputError, match=r"match\.yaml.*countries\[0\]\.cities"):
        load_match_config(path)
