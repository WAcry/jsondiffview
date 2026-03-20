import sys

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
