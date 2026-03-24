from __future__ import annotations

from jdv.paths import canonical_json, format_display_path, format_identity_label


def test_canonical_json_distinguishes_numeric_type_but_not_equivalent_float_lexeme() -> None:
    assert canonical_json(1) != canonical_json(1.0)
    assert canonical_json(1.0) == canonical_json(1e0)
    assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})


def test_format_display_path_uses_safe_key_regex() -> None:
    assert format_display_path(("items", 0)) == "$.items[0]"
    assert format_display_path(("a-b", 2)) == '$["a-b"][2]'
    assert format_display_path(("空 格",)) == '$["空 格"]'


def test_format_identity_label_renders_json_scalars() -> None:
    assert format_identity_label("id", "a") == 'id="a"'
    assert format_identity_label("enabled", True) == "enabled=true"
    assert format_identity_label("count", 42) == "count=42"
