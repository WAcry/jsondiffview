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
    assert node.children[0].kind is DiffKind.OBJECT
    assert node.children[0].children["capital"].path == 'countries[id=2,source="seed"].capital'
    assert node.children[0].children["capital"].kind is DiffKind.REPLACED


def test_duplicate_object_identity_raises_error():
    left = [{"id": 1}, {"id": 1}]
    right = [{"id": 1}]

    with pytest.raises(UserInputError, match="Duplicate object identity"):
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
    assert node.children[1].kind is DiffKind.REMOVED
    assert node.children[1].left == "english"
    assert node.children[2].path == 'languages[value="inglés"#0]'
    assert node.children[2].kind is DiffKind.ADDED
    assert node.children[2].right == "inglés"


def test_missing_declared_key_raises_error():
    left = [{"id": 1, "source": "seed"}]
    right = [{"id": 1}]

    with pytest.raises(UserInputError, match="Missing match key 'source'"):
        diff_values(
            "countries",
            left,
            right,
            array_mode="smart",
            match_rules=rules_for(path="countries", keys=[["id", "source"]]),
        )


def test_keyed_rule_on_non_object_items_raises_error():
    left = ["ar"]
    right = ["ar"]

    with pytest.raises(UserInputError, match="requires object items"):
        diff_values(
            "countries",
            left,
            right,
            array_mode="smart",
            match_rules=rules_for(path="countries", keys=[["id"]]),
        )


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
