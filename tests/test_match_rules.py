import pytest

from json_diff_cli.errors import UserInputError
from json_diff_cli.match_rules import MatchConfig, build_match_rule_set


def test_match_config_from_mapping_normalizes_scalar_and_composite_candidates():
    config = MatchConfig.from_mapping(
        {
            "global_matches": [["id", "source"], "id"],
            "path_matches": {
                "countries": [["identity.id", "identity.source"]],
            },
        }
    )

    assert config.global_matches == [["id", "source"], ["id"]]
    assert config.path_matches == {
        "countries": [["identity.id", "identity.source"]],
    }


def test_match_config_from_mapping_rejects_non_mapping_root():
    with pytest.raises(UserInputError, match="mapping"):
        MatchConfig.from_mapping(["id"])


def test_build_match_rule_set_uses_empty_config_when_none():
    rules = build_match_rule_set(["id"], None)

    assert rules.cli_global_keys == ["id"]
    assert rules.yaml_global_keys == []
    assert rules.yaml_path_keys == {}


def test_build_match_rule_set_rejects_dotted_cli_match_keys():
    with pytest.raises(UserInputError, match="identity\\.id"):
        build_match_rule_set(["identity.id"], None)


def test_build_match_rule_set_preserves_yaml_and_cli_priority_data():
    config = MatchConfig(
        global_matches=[["name"]],
        path_matches={"countries.*.cities": [["id"]]},
    )

    rules = build_match_rule_set(["id"], config)

    assert rules.yaml_path_keys["countries.*.cities"] == [["id"]]
    assert rules.yaml_global_keys == [["name"]]
    assert rules.cli_global_keys == ["id"]


def test_build_match_rule_set_rejects_numeric_path_segments():
    config = MatchConfig(
        global_matches=[],
        path_matches={"countries.0.cities": [["id"]]},
    )

    with pytest.raises(UserInputError, match="countries.0.cities"):
        build_match_rule_set([], config)


def test_build_match_rule_set_rejects_indexed_path_syntax():
    config = MatchConfig(
        global_matches=[],
        path_matches={"countries[0].cities": [["id"]]},
    )

    with pytest.raises(UserInputError, match="countries\\[0\\]\\.cities"):
        build_match_rule_set([], config)


def test_build_match_rule_set_rejects_wildcard_inside_literal_segment():
    config = MatchConfig(
        global_matches=[],
        path_matches={"countries*.cities": [["id"]]},
    )

    with pytest.raises(UserInputError, match="countries\\*\\.cities"):
        build_match_rule_set([], config)


def test_build_match_rule_set_rejects_wildcard_prefixed_literal_segment():
    config = MatchConfig(
        global_matches=[],
        path_matches={"countries.*foo.cities": [["id"]]},
    )

    with pytest.raises(UserInputError, match="countries\\.\\*foo\\.cities"):
        build_match_rule_set([], config)
