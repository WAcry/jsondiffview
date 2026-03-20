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
            "countries.regions.cities": [["name"]],
        },
    )

    assert resolve_object_key_rule(
        "countries.regions.cities",
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


def test_escaped_literal_object_key_path_matches_yaml_rule():
    rules = MatchRuleSet(
        cli_global_keys=[],
        yaml_global_keys=[],
        yaml_path_keys={'parent["a.b"].cities': [["id"]]},
    )

    assert resolve_object_key_rule(
        'parent["a.b"].cities',
        [{"id": 1}],
        rules,
    ) == ["id"]


def test_adjacent_escaped_object_key_path_matches_yaml_rule():
    rules = MatchRuleSet(
        cli_global_keys=[],
        yaml_global_keys=[],
        yaml_path_keys={'["a.b"]["c d"].cities': [["id"]]},
    )

    assert resolve_object_key_rule(
        '["a.b"]["c d"].cities',
        [{"id": 1}],
        rules,
    ) == ["id"]


def test_wildcard_yaml_path_rule_does_not_match_literal_wildcard_object_key():
    rules = MatchRuleSet(
        cli_global_keys=[],
        yaml_global_keys=[],
        yaml_path_keys={"parent.*.cities": [["id"]]},
    )

    assert resolve_object_key_rule(
        'parent["*"].cities',
        [{"id": 1}],
        rules,
    ) is None


def test_literal_wildcard_object_key_rule_beats_wildcard_segment_rule():
    rules = MatchRuleSet(
        cli_global_keys=[],
        yaml_global_keys=[],
        yaml_path_keys={
            "parent.*.cities": [["id"]],
            'parent["*"].cities': [["slug"]],
        },
    )

    assert resolve_object_key_rule(
        'parent["*"].cities',
        [{"id": 1, "slug": "literal"}],
        rules,
    ) == ["slug"]


def test_runtime_escaped_numeric_object_key_matches_literal_yaml_path_segment():
    rules = MatchRuleSet(
        cli_global_keys=[],
        yaml_global_keys=[],
        yaml_path_keys={"reports.2024.items": [["id"]]},
    )

    assert resolve_object_key_rule(
        'reports["2024"].items',
        [{"id": 1}],
        rules,
    ) == ["id"]


def test_runtime_array_index_does_not_match_numeric_object_key_rule():
    rules = MatchRuleSet(
        cli_global_keys=[],
        yaml_global_keys=[],
        yaml_path_keys={"reports.2024.items": [["id"]]},
    )

    assert resolve_object_key_rule(
        "reports[2024].items",
        [{"id": 1}],
        rules,
    ) is None


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


@pytest.mark.parametrize(
    ("child_key", "expected_path"),
    [
        ("a.b", 'countries[id=1]["a.b"]'),
        ("c d", 'countries[id=1]["c d"]'),
        ("*", 'countries[id=1]["*"]'),
        ("", 'countries[id=1][""]'),
    ],
)
def test_canonical_object_path_escapes_ambiguous_child_keys(
    child_key: str,
    expected_path: str,
):
    path = canonical_object_path("countries", ["id"], [1], child_key)

    assert path == expected_path


def test_canonical_primitive_path_renders_json_literal_with_occurrence():
    path = canonical_primitive_path("languages", "english", 0)

    assert path == 'languages[value="english"#0]'


def test_canonical_object_path_rejects_non_scalar_identity_values():
    with pytest.raises(UserInputError, match="scalar"):
        canonical_object_path("countries", ["name"], [{"text": "Argentina"}], "capital")
