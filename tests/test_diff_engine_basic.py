from json_diff_cli.diff_engine import diff_values
from json_diff_cli.types import DiffKind


def test_scalar_replacement_creates_replaced_node():
    node = diff_values("capital", "Buenos Aires", "Rawson")

    assert node.kind is DiffKind.REPLACED
    assert node.path == "capital"
    assert node.left == "Buenos Aires"
    assert node.right == "Rawson"
    assert node.children == {}


def test_equal_object_returns_unchanged_node():
    node = diff_values("", {"name": "Argentina"}, {"name": "Argentina"})

    assert node.kind is DiffKind.UNCHANGED
    assert node.left == {"name": "Argentina"}
    assert node.right == {"name": "Argentina"}
    assert node.children == {}


def test_equal_array_returns_unchanged_node():
    node = diff_values("languages", ["es", "en"], ["es", "en"])

    assert node.kind is DiffKind.UNCHANGED
    assert node.left == ["es", "en"]
    assert node.right == ["es", "en"]
    assert node.children == ()


def test_object_field_addition_creates_added_child():
    node = diff_values("", {"name": "Argentina"}, {"name": "Argentina", "capital": "Rawson"})

    assert node.kind is DiffKind.OBJECT
    assert set(node.children) == {"capital", "name"}
    assert node.children["capital"].kind is DiffKind.ADDED
    assert node.children["capital"].right == "Rawson"
    assert node.children["name"].kind is DiffKind.UNCHANGED


def test_object_children_preserve_input_key_order():
    node = diff_values("", {"b": 1, "a": 2}, {"b": 1, "a": 3, "c": 4})

    assert list(node.children) == ["b", "a", "c"]


def test_object_path_escapes_ambiguous_key_segments():
    node = diff_values("", {"a.b[c]": 1}, {"a.b[c]": 2})

    assert node.kind is DiffKind.OBJECT
    assert node.children["a.b[c]"].path == '["a.b[c]"]'


def test_object_path_escapes_empty_key_at_root():
    node = diff_values("", {"": 1}, {"": 2})

    assert node.kind is DiffKind.OBJECT
    assert node.children[""].path == '[""]'


def test_object_path_escapes_empty_key_under_parent():
    node = diff_values("", {"parent": {"": 1}}, {"parent": {"": 2}})

    assert node.kind is DiffKind.OBJECT
    assert node.children["parent"].kind is DiffKind.OBJECT
    assert node.children["parent"].children[""].path == 'parent[""]'


def test_object_path_escapes_key_with_space():
    node = diff_values("", {"a b": 1}, {"a b": 2})

    assert node.kind is DiffKind.OBJECT
    assert node.children["a b"].path == '["a b"]'


def test_object_path_escapes_key_with_quote():
    node = diff_values("", {'a"b': 1}, {'a"b': 2})

    assert node.kind is DiffKind.OBJECT
    assert node.children['a"b'].path == '["a\\"b"]'


def test_object_path_escapes_non_identifier_key_under_parent():
    node = diff_values("", {"parent": {"-": 1}}, {"parent": {"-": 2}})

    assert node.kind is DiffKind.OBJECT
    assert node.children["parent"].children["-"].path == 'parent["-"]'


def test_equal_object_comparison_keeps_nested_bool_number_distinction():
    node = diff_values("", {"x": 1}, {"x": True})

    assert node.kind is DiffKind.OBJECT
    assert node.children["x"].kind is DiffKind.REPLACED
    assert node.children["x"].left == 1
    assert node.children["x"].right is True


def test_equal_array_comparison_keeps_nested_bool_number_distinction():
    node = diff_values("values", [1], [True])

    assert node.kind is DiffKind.ARRAY
    assert node.children[0].kind is DiffKind.REPLACED
    assert node.children[0].left == 1
    assert node.children[0].right is True


def test_positional_array_replacement_uses_numeric_index_path():
    node = diff_values("languages", ["es", "en"], ["es", "fr"])

    assert node.kind is DiffKind.ARRAY
    assert len(node.children) == 2
    assert node.children[1].path == "languages[1]"
    assert node.children[1].kind is DiffKind.REPLACED
    assert node.children[1].left == "en"
    assert node.children[1].right == "fr"
