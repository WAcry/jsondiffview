import sys

from json_diff_cli.diff_engine import diff_values
from json_diff_cli.renderers.changed import render_changed


def diff_node_for(left, right):
    return diff_values("", left, right)


def test_changed_renderer_emits_leaf_blocks_only():
    rendered = render_changed(
        diff_node_for(
            {"demographics": {"population": 1}},
            {"demographics": {"population": 2, "timezone": [-4, -3]}},
        ),
        color="never",
    )

    blocks = rendered.split("\n\n")

    assert len(blocks) == 2
    assert blocks[0].splitlines()[0] == "demographics.population (replace)"
    assert blocks[1].splitlines()[0] == "demographics.timezone (add)"


def test_changed_renderer_does_not_emit_parent_container_snippets():
    rendered = render_changed(
        diff_node_for({"a": {"b": 1}}, {"a": {"b": 2}}),
        color="never",
    )

    assert rendered.splitlines()[0] == "a.b (replace)"
    assert "{\n" not in rendered


def test_changed_renderer_uses_fragment_aware_old_and_new_string_previews():
    rendered = render_changed(
        diff_node_for({"word": "english"}, {"word": "inglés"}),
        color="never",
    )

    assert 'old: "english"' not in rendered
    assert 'new: "inglés"' not in rendered
    assert 'old: "' in rendered
    assert 'new: "' in rendered
    assert "[-" in rendered
    assert "[+" in rendered


def test_changed_renderer_honors_color_for_string_previews():
    rendered = render_changed(
        diff_node_for({"word": "old"}, {"word": "new"}),
        color="always",
    )

    assert "\x1b[" in rendered


def test_changed_renderer_sorts_added_object_preview_when_requested():
    rendered = render_changed(
        diff_node_for({}, {"obj": {"b": 1, "a": 2}}),
        color="never",
        sort_keys=True,
    )

    assert 'new: {"a": 2, "b": 1}' in rendered


def test_changed_renderer_sorts_removed_object_preview_when_requested():
    rendered = render_changed(
        diff_node_for({"obj": {"b": 1, "a": 2}}, {}),
        color="never",
        sort_keys=True,
    )

    assert 'old: {"a": 2, "b": 1}' in rendered


def test_changed_renderer_colors_added_object_preview_when_requested():
    rendered = render_changed(
        diff_node_for({}, {"obj": {"a": 1}}),
        color="always",
    )

    assert "\x1b[" in rendered


def test_changed_renderer_removed_block_emits_only_old_preview():
    rendered = render_changed(
        diff_node_for({"obj": {"a": 1}}, {}),
        color="never",
    )

    assert rendered.splitlines()[0] == "obj (remove)"
    assert 'old: {"a": 1}' in rendered
    assert "new:" not in rendered


def test_changed_renderer_replaced_container_emits_old_and_new_previews():
    rendered = render_changed(
        diff_node_for({"obj": {"a": 1}}, {"obj": [1, 2]}),
        color="never",
    )

    assert rendered.splitlines()[0] == "obj (replace)"
    assert 'old: {"a": 1}' in rendered
    assert "new: [1, 2]" in rendered


def test_changed_renderer_omits_root_path_in_top_level_header():
    rendered = render_changed(diff_node_for("old", "new"), color="never")

    assert rendered.splitlines()[0] == "(replace)"


def test_changed_renderer_auto_non_tty_uses_plain_string_preview(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    rendered = render_changed(
        diff_node_for({"word": "english"}, {"word": "inglés"}),
        color="auto",
    )

    assert "\x1b[" not in rendered
    assert "[-" not in rendered
    assert "[+" not in rendered
    assert 'old: "english"' in rendered
    assert 'new: "inglés"' in rendered
