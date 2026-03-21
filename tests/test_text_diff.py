from json_diff_cli.text_diff import diff_strings


def test_diff_strings_returns_equal_remove_add_fragments():
    fragments = diff_strings("english", "inglés")

    assert any(fragment.role == "equal" for fragment in fragments)
    assert any(fragment.role == "remove" for fragment in fragments)
    assert any(fragment.role == "add" for fragment in fragments)
