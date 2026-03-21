import pytest

from json_diff_cli.diff_engine import diff_values
from json_diff_cli.errors import UserInputError
from json_diff_cli.types import DiffKind, MatchRuleSet


def rules_for(*, path: str | None = None, keys: list[list[str]] | None = None) -> MatchRuleSet:
    return MatchRuleSet(
        cli_global_keys=[],
        yaml_global_keys=[],
        yaml_path_keys={} if path is None or keys is None else {path: keys},
    )


def test_smart_object_array_matches_by_yaml_rule():
    left = [{"id": 2, "source": "seed", "capital": "Buenos Aires"}]
    right = [{"id": 2, "source": "seed", "capital": "Rawson"}]

    node = diff_values(
        "countries",
        left,
        right,
        array_mode="smart",
        match_rules=rules_for(path="countries", keys=[["id", "source"]]),
    )

    assert node.kind is DiffKind.ARRAY
    assert node.children[0].path == 'countries[id=2,source="seed"]'
    assert node.children[0].display_path == 'countries[id=2,source="seed"]'
    assert node.children[0].match_info is not None
    assert node.children[0].match_info.mode == "object-smart"
    assert node.children[0].match_info.identity_keys == ("id", "source")
    assert node.children[0].match_info.identity_values == (2, "seed")
    assert node.children[0].kind is DiffKind.OBJECT
    assert node.children[0].children["capital"].path == 'countries[id=2,source="seed"].capital'
    assert node.children[0].children["capital"].kind is DiffKind.REPLACED


def test_smart_object_array_matches_by_bracket_literal_candidate_key_path():
    left = [{"identity": {"a.b": 1}, "capital": "Buenos Aires"}]
    right = [{"identity": {"a.b": 1}, "capital": "Rawson"}]

    node = diff_values(
        "countries",
        left,
        right,
        array_mode="smart",
        match_rules=rules_for(path="countries", keys=[['identity["a.b"]']]),
    )

    assert node.kind is DiffKind.ARRAY
    assert node.children[0].path == 'countries[identity["a.b"]=1]'
    assert node.children[0].kind is DiffKind.OBJECT
    assert node.children[0].children["capital"].kind is DiffKind.REPLACED


def test_duplicate_object_identity_raises_error():
    left = [{"id": 1}, {"id": 1}]
    right = [{"id": 1}]

    with pytest.raises(
        UserInputError,
        match=r"Duplicate object identity at countries\[id=1\]",
    ):
        diff_values(
            "countries",
            left,
            right,
            array_mode="smart",
            match_rules=rules_for(path="countries", keys=[["id"]]),
        )


def test_duplicate_primitive_values_are_matched_by_occurrence_order():
    node = diff_values(
        "languages",
        ["english", "english"],
        ["english", "inglés"],
        array_mode="smart",
    )

    assert node.kind is DiffKind.ARRAY
    assert node.children[1].path == 'languages[value="english"#1]'
    assert node.children[1].display_path == 'languages[value="english"#1]'
    assert node.children[1].match_info is not None
    assert node.children[1].match_info.mode == "primitive-smart"
    assert node.children[1].match_info.identity_values == ("english",)
    assert node.children[1].match_info.occurrence == 1
    assert node.children[1].kind is DiffKind.REMOVED
    assert node.children[1].left == "english"
    assert node.children[2].path == 'languages[value="inglés"#0]'
    assert node.children[2].kind is DiffKind.ADDED
    assert node.children[2].right == "inglés"


def test_empty_smart_array_with_configured_rule_remains_unchanged():
    node = diff_values(
        "countries",
        [],
        [],
        array_mode="smart",
        match_rules=rules_for(path="countries", keys=[["id"]]),
    )

    assert node.kind is DiffKind.UNCHANGED
    assert node.left == []
    assert node.right == []
    assert node.children == ()


def test_numeric_primitive_arrays_match_by_json_number_equality():
    node = diff_values(
        "numbers",
        [1, 2],
        [2.0, 1.0],
        array_mode="smart",
    )

    assert node.kind is DiffKind.ARRAY
    assert [child.path for child in node.children] == [
        "numbers[value=1#0]",
        "numbers[value=2#0]",
    ]
    assert all(child.kind is DiffKind.UNCHANGED for child in node.children)


def test_smart_primitive_matching_keeps_bool_distinct_from_numbers():
    node = diff_values(
        "values",
        [True],
        [1.0],
        array_mode="smart",
    )

    assert node.kind is DiffKind.ARRAY
    assert [child.path for child in node.children] == [
        "values[value=true#0]",
        "values[value=1.0#0]",
    ]
    assert node.children[0].kind is DiffKind.REMOVED
    assert node.children[1].kind is DiffKind.ADDED


def test_smart_primitive_arrays_ignore_global_object_match_candidates():
    node = diff_values(
        "languages",
        ["english"],
        ["inglés"],
        array_mode="smart",
        match_rules=MatchRuleSet(
            cli_global_keys=["name"],
            yaml_global_keys=[],
            yaml_path_keys={},
        ),
    )

    assert node.kind is DiffKind.ARRAY
    assert [child.path for child in node.children] == [
        'languages[value="english"#0]',
        'languages[value="inglés"#0]',
    ]
    assert node.children[0].kind is DiffKind.REMOVED
    assert node.children[1].kind is DiffKind.ADDED


def test_inapplicable_candidate_with_missing_keys_falls_back_to_positional():
    left = [{"id": 1, "source": "seed"}]
    right = [{"id": 1}]

    node = diff_values(
        "countries",
        left,
        right,
        array_mode="smart",
        match_rules=rules_for(path="countries", keys=[["id", "source"]]),
    )

    assert node.kind is DiffKind.ARRAY
    assert node.children[0].path == "countries[0]"
    assert node.children[0].kind is DiffKind.OBJECT


def test_non_scalar_match_key_error_includes_array_path():
    left = [{"identity": {"id": {"value": 1}}}]
    right = [{"identity": {"id": {"value": 1}}}]

    with pytest.raises(
        UserInputError,
        match=r"countries.*identity\.id.*scalar",
    ):
        diff_values(
            "countries",
            left,
            right,
            array_mode="smart",
            match_rules=rules_for(path="countries", keys=[["identity.id"]]),
        )


def test_keyed_rule_on_non_object_items_is_ignored_for_primitive_matching():
    left = ["ar"]
    right = ["ar"]

    node = diff_values(
        "countries",
        left,
        right,
        array_mode="smart",
        match_rules=rules_for(path="countries", keys=[["id"]]),
    )

    assert node.kind is DiffKind.UNCHANGED
    assert node.left == ["ar"]
    assert node.right == ["ar"]


def test_smart_mode_falls_back_to_positional_when_no_rule_applies():
    left = [{"capital": "Buenos Aires"}]
    right = [{"capital": "Rawson"}]

    node = diff_values(
        "countries",
        left,
        right,
        array_mode="smart",
        match_rules=rules_for(path="regions", keys=[["id"]]),
    )

    assert node.kind is DiffKind.ARRAY
    assert node.children[0].path == "countries[0]"
    assert node.children[0].kind is DiffKind.OBJECT
    assert node.children[0].children["capital"].path == "countries[0].capital"


def test_mixed_array_without_object_match_candidate_falls_back_to_positional():
    left = [{"code": 1}, "legacy"]
    right = [{"code": 2}, "legacy"]

    node = diff_values(
        "countries",
        left,
        right,
        array_mode="smart",
    )

    assert node.kind is DiffKind.ARRAY
    assert node.children[0].path == "countries[0]"
    assert node.children[0].kind is DiffKind.OBJECT
    assert node.children[1].kind is DiffKind.UNCHANGED


def test_smart_mode_falls_back_to_positional_when_higher_priority_candidates_are_inapplicable():
    left = [{"code": 1}]
    right = [{"code": 2}]

    node = diff_values(
        "countries",
        left,
        right,
        array_mode="smart",
        match_rules=MatchRuleSet(
            cli_global_keys=["id"],
            yaml_global_keys=[],
            yaml_path_keys={},
        ),
    )

    assert node.kind is DiffKind.ARRAY
    assert node.children[0].path == "countries[0]"
    assert node.children[0].kind is DiffKind.OBJECT
    assert node.children[0].children["code"].kind is DiffKind.REPLACED


def test_mixed_array_with_explicit_object_match_candidate_fails_fast():
    left = [{"id": 1}, "legacy"]
    right = [{"id": 1}, "legacy"]

    with pytest.raises(UserInputError, match=r"countries.*requires object items"):
        diff_values(
            "countries",
            left,
            right,
            array_mode="smart",
            match_rules=MatchRuleSet(
                cli_global_keys=["id"],
                yaml_global_keys=[],
                yaml_path_keys={},
            ),
        )
