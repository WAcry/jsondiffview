import pytest

from json_diff_cli.errors import UserInputError
from json_diff_cli.matcher import (
    canonical_object_path,
    canonical_primitive_path,
    resolve_object_key_rule,
)
from json_diff_cli.types import MatchRuleSet


def test_yaml_path_rule_beats_global_and_cli():
    rules = MatchRuleSet(
        cli_global_keys=["id"],
        yaml_global_keys=[["name"]],
        yaml_path_keys={"countries": [["iso2", "name"]]},
    )

    assert resolve_object_key_rule(
        "countries",
        [{"iso2": "AR", "name": "Argentina"}],
        rules,
    ) == ["iso2", "name"]


def test_cli_keys_fallback_in_declaration_order():
    rules = MatchRuleSet(
        cli_global_keys=["id", "name"],
        yaml_global_keys=[],
        yaml_path_keys={},
    )

    assert resolve_object_key_rule("countries", [{"name": "AR"}], rules) == ["name"]


def test_wildcard_yaml_path_rule_matches_nested_array():
    rules = MatchRuleSet(
        cli_global_keys=[],
        yaml_global_keys=[],
        yaml_path_keys={"countries.*.cities": [["id"]]},
    )

    assert resolve_object_key_rule("countries[0].cities", [{"id": 1}], rules) == ["id"]


def test_all_matching_yaml_path_candidates_are_considered_before_global_fallback():
    rules = MatchRuleSet(
        cli_global_keys=["id"],
        yaml_global_keys=[["code"]],
        yaml_path_keys={
            "countries.*.cities": [["id"]],
            "countries.0.cities": [["name"]],
        },
    )

    assert resolve_object_key_rule(
        "countries[0].cities",
        [{"name": "Buenos Aires"}],
        rules,
    ) == ["name"]


def test_wildcard_yaml_path_rule_matches_selector_value_containing_closing_bracket():
    rules = MatchRuleSet(
        cli_global_keys=[],
        yaml_global_keys=[],
        yaml_path_keys={"countries.*.cities": [["id"]]},
    )

    assert resolve_object_key_rule(
        'countries[name="a]b"].cities',
        [{"id": 1}],
        rules,
    ) == ["id"]


def test_dotted_key_path_is_allowed_in_yaml_rule_and_preserved():
    rules = MatchRuleSet(
        cli_global_keys=[],
        yaml_global_keys=[],
        yaml_path_keys={"countries": [["identity.id"]]},
    )

    assert resolve_object_key_rule(
        "countries",
        [{"identity": {"id": 1}}],
        rules,
    ) == ["identity.id"]


def test_canonical_object_path_uses_identity_selectors():
    path = canonical_object_path("countries", ["name"], ["Argentina"], "capital")

    assert path == 'countries[name="Argentina"].capital'


def test_canonical_object_path_supports_composite_keys():
    path = canonical_object_path(
        "countries",
        ["iso2", "name"],
        ["AR", "Argentina"],
        "capital",
    )

    assert path == 'countries[iso2="AR",name="Argentina"].capital'


def test_canonical_primitive_path_renders_json_literal_with_occurrence():
    path = canonical_primitive_path("languages", "english", 0)

    assert path == 'languages[value="english"#0]'


def test_canonical_object_path_rejects_non_scalar_identity_values():
    with pytest.raises(UserInputError, match="scalar"):
        canonical_object_path("countries", ["name"], [{"text": "Argentina"}], "capital")
