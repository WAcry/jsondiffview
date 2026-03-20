import sys

import pytest

from json_diff_cli.diff_engine import diff_values
from json_diff_cli.renderers.full import render_full


def diff_node_for(left, right):
    return diff_values("", left, right)


def test_full_renderer_shows_inline_scalar_replacement():
    rendered = render_full(
        diff_node_for({"capital": "Buenos Aires"}, {"capital": "Rawson"}),
        color="never",
    )

    assert '[-"Buenos Aires"-][+"Rawson"+]' in rendered


def test_full_renderer_uses_normalized_pretty_print_with_render_time_sorting():
    rendered = render_full(
        diff_node_for({"b": 1, "a": 2}, {"b": 1, "a": 3}),
        color="never",
        sort_keys=True,
    )

    lines = rendered.splitlines()

    assert lines[1].strip() == '"a": [-2-][+3+],'
    assert lines[2].strip() == '"b": 1'


def test_full_renderer_preserves_diff_tree_key_order_by_default():
    rendered = render_full(
        diff_node_for({"b": 1, "a": 2}, {"b": 1, "a": 3}),
        color="never",
    )

    assert rendered.splitlines()[1].strip() == '"b": 1,'


def test_full_renderer_formats_added_scalar_without_extra_indent_inside_markers():
    rendered = render_full(
        diff_node_for({"a": 1}, {"a": 2, "b": 3}),
        color="never",
    )

    assert '"b": [+3+]' in rendered


def test_full_renderer_auto_color_uses_plain_text_when_stdout_is_not_a_tty(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    rendered = render_full(
        diff_node_for({"capital": "Buenos Aires"}, {"capital": "Rawson"}),
        color="auto",
    )

    assert '[-"Buenos Aires"-][+"Rawson"+]' not in rendered
    assert "\x1b[" not in rendered
    assert '"capital": "Buenos Aires" -> "Rawson"' in rendered


def test_full_renderer_always_color_keeps_ansi_highlighting():
    rendered = render_full(
        diff_node_for({"capital": "Buenos Aires"}, {"capital": "Rawson"}),
        color="always",
    )

    assert "\x1b[31m" in rendered
    assert "\x1b[32m" in rendered


def test_full_renderer_always_color_separates_replacement_tokens():
    rendered = render_full(
        diff_node_for({"capital": "old"}, {"capital": "new"}),
        color="always",
    )

    assert '\x1b[31m"old"\x1b[0m -> \x1b[32m"new"\x1b[0m' in rendered


def test_full_renderer_preserves_parent_field_for_nested_replacement():
    rendered = render_full(
        diff_node_for({"root": {"a": 1}}, {"root": {"a": {"b": 2}}}),
        color="never",
    )

    assert '"a": [-1-]' in rendered
    assert '"a": [+{' in rendered
    assert '      "b": 2' in rendered


def test_full_renderer_preserves_array_item_structure_for_nested_replacement():
    rendered = render_full(
        diff_node_for([1], [[[]]]),
        color="never",
    )

    lines = rendered.splitlines()

    assert lines[1].strip() == "[-1-]"
    assert lines[2].strip() == "[+["
    assert lines[3].strip() == "[]"
    assert lines[4].strip() == "]+]"


def test_full_renderer_rejects_invalid_color_for_unchanged_diff():
    with pytest.raises(ValueError, match="Unsupported color mode: bogus"):
        render_full(diff_values("", 1, 1), color="bogus")


def test_full_renderer_separates_object_replacement_halves_with_commas():
    rendered = render_full(
        diff_node_for({"x": 1, "y": 9}, {"x": {"a": 2}, "y": 9}),
        color="never",
    )

    assert '"x": [-1-],' in rendered
    assert '  }+],' in rendered
    assert '  "y": 9' in rendered


def test_full_renderer_separates_array_replacement_halves_with_commas():
    rendered = render_full(
        diff_node_for([1, 9], [[[]], 9]),
        color="never",
    )

    lines = rendered.splitlines()

    assert lines[1].strip() == "[-1-],"
    assert lines[4].strip() == "]+],"
    assert lines[5].strip() == "9"


def test_full_renderer_does_not_repeat_parent_prefix_inside_nested_replacement():
    rendered = render_full(
        diff_node_for({"a": [1, 2]}, {"a": [1, {"x": 2}]}),
        color="never",
    )

    assert rendered.count('"a": ') == 1
    assert '    [+{' in rendered
    assert '  "a":   [+{' not in rendered


def test_full_renderer_auto_non_tty_formats_multiline_added_object_cleanly(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    rendered = render_full(
        diff_node_for({"y": 9}, {"y": 9, "x": {"a": 2}}),
        color="auto",
    )

    assert '"x": +{' in rendered
    assert '"a": 2' in rendered
    assert '+ "a": 2' not in rendered
    assert '+ }' not in rendered


def test_full_renderer_auto_non_tty_formats_multiline_removed_object_cleanly(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    rendered = render_full(
        diff_node_for({"x": {"a": 2}, "y": 9}, {"y": 9}),
        color="auto",
    )

    assert '"x": -{' in rendered
    assert '"a": 2' in rendered
    assert '- "a": 2' not in rendered
    assert '- }' not in rendered


def test_full_renderer_auto_non_tty_formats_multiline_replacement_cleanly(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    rendered = render_full(
        diff_node_for({"x": 1}, {"x": {"a": 2}}),
        color="auto",
    )

    assert '"x": -1' in rendered
    assert '"x": +{' in rendered
    assert '+ "a": 2' not in rendered


def test_full_renderer_auto_non_tty_separates_multiline_replacement_halves(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    rendered = render_full(
        diff_node_for({"x": {"a": 1}}, {"x": [1, 2]}),
        color="auto",
    )

    assert '\n\n  "x": +[' in rendered


def test_full_renderer_always_separates_multiline_replacement_halves():
    rendered = render_full(
        diff_node_for({"x": {"a": 1}}, {"x": [1, 2]}),
        color="always",
    )

    assert '\n\n  "x": \x1b[32m[\x1b[0m' in rendered
