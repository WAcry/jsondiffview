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


def test_positional_array_replacement_uses_numeric_index_path():
    node = diff_values("languages", ["es", "en"], ["es", "fr"])

    assert node.kind is DiffKind.ARRAY
    assert len(node.children) == 2
    assert node.children[1].path == "languages[1]"
    assert node.children[1].kind is DiffKind.REPLACED
    assert node.children[1].left == "en"
    assert node.children[1].right == "fr"
