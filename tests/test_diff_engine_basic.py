from json_diff_cli.diff_engine import diff_values
from json_diff_cli.types import DiffKind


def test_scalar_replacement_creates_replaced_node():
    node = diff_values("capital", "Buenos Aires", "Rawson")

    assert node.kind is DiffKind.REPLACED
    assert node.path == "capital"
    assert node.left == "Buenos Aires"
    assert node.right == "Rawson"
    assert node.children == ()


def test_object_field_addition_creates_added_child():
    node = diff_values("", {"name": "Argentina"}, {"name": "Argentina", "capital": "Rawson"})

    children_by_path = {child.path: child for child in node.children}

    assert node.kind is DiffKind.OBJECT
    assert "capital" in children_by_path
    assert children_by_path["capital"].kind is DiffKind.ADDED
    assert children_by_path["capital"].right == "Rawson"


def test_positional_array_replacement_uses_numeric_index_path():
    node = diff_values("languages", ["es", "en"], ["es", "fr"])

    children_by_path = {child.path: child for child in node.children}

    assert node.kind is DiffKind.ARRAY
    assert "languages[1]" in children_by_path
    assert children_by_path["languages[1]"].kind is DiffKind.REPLACED
    assert children_by_path["languages[1]"].left == "en"
    assert children_by_path["languages[1]"].right == "fr"
