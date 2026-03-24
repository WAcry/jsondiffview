from __future__ import annotations

from typing import Iterable

from .model import (
    DiffNode,
    DiffSettings,
    DiffStatus,
    LayoutLine,
    LayoutLineKind,
    LayoutPlan,
    MoveBasis,
    ReviewMode,
)
from .paths import format_display_path, json_string_fragment, render_json_scalar


def build_display_layout(
    root: DiffNode,
    review_mode: ReviewMode,
    settings: DiffSettings,
) -> LayoutPlan:
    if root.status is DiffStatus.UNCHANGED and root.move_detail is None:
        return LayoutPlan(review_mode=review_mode, has_changes=False, lines=[])

    lines = _emit_node(root, review_mode, settings, indent=0, field_key=None, root=True)
    return LayoutPlan(review_mode=review_mode, has_changes=True, lines=lines)


def _emit_node(
    node: DiffNode,
    review_mode: ReviewMode,
    settings: DiffSettings,
    indent: int,
    field_key: str | None,
    root: bool = False,
) -> list[LayoutLine]:
    old_value = node.old_value
    new_value = node.new_value

    if node.status is DiffStatus.ADDED:
        return _emit_added_removed_block(node, review_mode, settings, indent, field_key, marker="+")
    if node.status is DiffStatus.REMOVED:
        return _emit_added_removed_block(node, review_mode, settings, indent, field_key, marker="-")

    if isinstance(old_value, dict) and isinstance(new_value, dict):
        return _emit_object(node, review_mode, settings, indent, field_key, root=root)
    if isinstance(old_value, list) and isinstance(new_value, list):
        return _emit_array(node, review_mode, settings, indent, field_key, root=root)

    if node.status is DiffStatus.UNCHANGED:
        return [_value_line(indent, "", _render_labelled_scalar(field_key, new_value, root=root))]

    return _emit_modified_leaf(node, indent, field_key, root=root)


def _emit_object(
    node: DiffNode,
    review_mode: ReviewMode,
    settings: DiffSettings,
    indent: int,
    field_key: str | None,
    root: bool,
) -> list[LayoutLine]:
    _ = root
    lines = [_line(indent, LayoutLineKind.OPEN, "", _label_prefix(field_key) + "{")]
    child_blocks = _build_object_child_blocks(node.children, review_mode, settings, indent + 1)
    _apply_trailing_commas(child_blocks)
    lines.extend(_flatten_blocks(child_blocks))
    lines.append(_line(indent, LayoutLineKind.CLOSE, "", "}"))
    return lines


def _emit_array(
    node: DiffNode,
    review_mode: ReviewMode,
    settings: DiffSettings,
    indent: int,
    field_key: str | None,
    root: bool,
) -> list[LayoutLine]:
    _ = root
    lines = [_line(indent, LayoutLineKind.OPEN, "", _label_prefix(field_key) + "[")]
    child_blocks = _build_array_child_blocks(node.children, review_mode, settings, indent + 1)
    _apply_trailing_commas(child_blocks)
    lines.extend(_flatten_blocks(child_blocks))
    lines.append(_line(indent, LayoutLineKind.CLOSE, "", "]"))
    return lines


def _emit_added_removed_block(
    node: DiffNode,
    review_mode: ReviewMode,
    settings: DiffSettings,
    indent: int,
    field_key: str | None,
    marker: str,
) -> list[LayoutLine]:
    value = node.new_value if marker == "+" else node.old_value
    if isinstance(value, dict):
        return _emit_added_removed_object(node, review_mode, settings, indent, field_key, marker)
    if isinstance(value, list):
        return _emit_added_removed_array(node, review_mode, settings, indent, field_key, marker)
    return [_value_line(indent, marker, _render_labelled_scalar(field_key, value))]


def _emit_added_removed_object(
    node: DiffNode,
    review_mode: ReviewMode,
    settings: DiffSettings,
    indent: int,
    field_key: str | None,
    marker: str,
) -> list[LayoutLine]:
    lines = [_line(indent, LayoutLineKind.OPEN, marker, _label_prefix(field_key) + "{")]
    children = sorted(node.children, key=lambda child: child.new_index if marker == "+" else child.old_index)
    preview_limit = settings.compact_preview_keys
    preview_children = children
    remaining = 0
    if review_mode is ReviewMode.COMPACT and len(children) > preview_limit:
        preview_children = children[:preview_limit]
        remaining = len(children) - preview_limit

    child_blocks = [
        _emit_added_removed_block(child, review_mode, settings, indent + 1, _field_key(child), marker)
        for child in preview_children
    ]
    if remaining:
        noun = "added" if marker == "+" else "removed"
        child_blocks.append([_summary_line(indent + 1, marker, f"… {remaining} more {noun} keys")])
    _apply_trailing_commas(child_blocks)
    lines.extend(_flatten_blocks(child_blocks))
    lines.append(_line(indent, LayoutLineKind.CLOSE, marker, "}"))
    return lines


def _emit_added_removed_array(
    node: DiffNode,
    review_mode: ReviewMode,
    settings: DiffSettings,
    indent: int,
    field_key: str | None,
    marker: str,
) -> list[LayoutLine]:
    lines = [_line(indent, LayoutLineKind.OPEN, marker, _label_prefix(field_key) + "[")]
    children = sorted(node.children, key=lambda child: child.new_index if marker == "+" else child.old_index)
    preview_limit = settings.compact_preview_items
    preview_children = children
    remaining = 0
    if review_mode is ReviewMode.COMPACT and len(children) > preview_limit:
        preview_children = children[:preview_limit]
        remaining = len(children) - preview_limit

    child_blocks = [
        _emit_added_removed_block(child, review_mode, settings, indent + 1, None, marker)
        for child in preview_children
    ]
    if remaining:
        noun = "added" if marker == "+" else "removed"
        child_blocks.append([_summary_line(indent + 1, marker, f"… {remaining} more {noun} items")])
    _apply_trailing_commas(child_blocks)
    lines.extend(_flatten_blocks(child_blocks))
    lines.append(_line(indent, LayoutLineKind.CLOSE, marker, "]"))
    return lines


def _emit_modified_leaf(
    node: DiffNode,
    indent: int,
    field_key: str | None,
    root: bool,
) -> list[LayoutLine]:
    label_prefix = _label_prefix(field_key, root=root)
    if node.string_detail is not None and node.string_detail.mode == "inline":
        return [_value_line(indent, "~", f"{label_prefix}{_render_inline_string_detail(node.string_detail)}")]

    if _is_scalar(node.old_value) and _is_scalar(node.new_value):
        return [
            _value_line(
                indent,
                "~",
                f"{label_prefix}{render_json_scalar(node.old_value)} -> {render_json_scalar(node.new_value)}",
            )
        ]

    lines = [_line(indent, LayoutLineKind.MODIFIED_HEADER, "~", _label_prefix(field_key, root=root).rstrip())]
    lines.extend(_render_replace_block("-", node.old_value, indent + 1))
    lines.extend(_render_replace_block("+", node.new_value, indent + 1))
    return lines


def _build_object_child_blocks(
    children: list[DiffNode],
    review_mode: ReviewMode,
    settings: DiffSettings,
    indent: int,
) -> list[list[LayoutLine]]:
    live_children = sorted(
        [child for child in children if child.new_index is not None],
        key=lambda child: child.new_index,
    )
    removed_children = sorted(
        [child for child in children if child.new_index is None],
        key=lambda child: child.old_index,
    )
    sequence = _insert_removed_children(live_children, removed_children)
    return _build_sequence_blocks(sequence, review_mode, settings, indent, is_array=False)


def _build_array_child_blocks(
    children: list[DiffNode],
    review_mode: ReviewMode,
    settings: DiffSettings,
    indent: int,
) -> list[list[LayoutLine]]:
    live_children = sorted(
        [child for child in children if child.new_index is not None],
        key=lambda child: child.new_index,
    )
    removed_children = sorted(
        [child for child in children if child.new_index is None],
        key=lambda child: child.old_index,
    )
    sequence = _insert_removed_children(live_children, removed_children)
    return _build_sequence_blocks(sequence, review_mode, settings, indent, is_array=True)


def _insert_removed_children(live_children: list[DiffNode], removed_children: list[DiffNode]) -> list[DiffNode]:
    anchors: dict[int, list[DiffNode]] = {}
    for removed in removed_children:
        anchor = len(live_children)
        for index, live in enumerate(live_children):
            if live.old_index is not None and live.old_index > removed.old_index:
                anchor = index
                break
        anchors.setdefault(anchor, []).append(removed)

    ordered: list[DiffNode] = []
    for index in range(len(live_children) + 1):
        ordered.extend(anchors.get(index, []))
        if index < len(live_children):
            ordered.append(live_children[index])
    return ordered


def _build_sequence_blocks(
    sequence: list[DiffNode],
    review_mode: ReviewMode,
    settings: DiffSettings,
    indent: int,
    is_array: bool,
) -> list[list[LayoutLine]]:
    blocks: list[list[LayoutLine]] = []
    index = 0
    while index < len(sequence):
        child = sequence[index]
        if review_mode is not ReviewMode.FULL and _is_collapsible_unchanged(child):
            start = index
            count = 0
            while index < len(sequence) and _is_collapsible_unchanged(sequence[index]):
                count += 1
                index += 1
            if count == 1:
                blocks.append(_build_child_block(sequence[start], review_mode, settings, indent, is_array))
                continue
            noun = "items" if is_array else "keys"
            blocks.append([_summary_line(indent, "", f"… {count} unchanged {noun}")])
            continue

        blocks.append(_build_child_block(child, review_mode, settings, indent, is_array))
        index += 1
    return blocks


def _build_child_block(
    child: DiffNode,
    review_mode: ReviewMode,
    settings: DiffSettings,
    indent: int,
    is_array: bool,
) -> list[LayoutLine]:
    block: list[LayoutLine] = []
    if is_array and child.status is DiffStatus.REMOVED:
        block.append(_note_line(indent, f"removed {format_display_path(child.old_path)}"))
    if is_array and child.move_detail is not None:
        block.append(_note_line(indent, _move_note_text(child)))

    block.extend(
        _emit_node(
            node=child,
            review_mode=review_mode,
            settings=settings,
            indent=indent,
            field_key=None if is_array else _field_key(child),
        )
    )
    return block


def _apply_trailing_commas(blocks: list[list[LayoutLine]]) -> None:
    for block in blocks[:-1]:
        last_line = block[-1]
        block[-1] = LayoutLine(
            indent=last_line.indent,
            kind=last_line.kind,
            marker=last_line.marker,
            text=last_line.text,
            trailing_comma=True,
            string_detail=last_line.string_detail,
        )


def _flatten_blocks(blocks: Iterable[list[LayoutLine]]) -> list[LayoutLine]:
    lines: list[LayoutLine] = []
    for block in blocks:
        lines.extend(block)
    return lines


def _render_replace_block(marker: str, value: object, indent: int, field_key: str | None = None) -> list[LayoutLine]:
    if _is_scalar(value):
        return [_value_line(indent, marker, f"{_label_prefix(field_key)}{render_json_scalar(value)}")]

    if isinstance(value, dict):
        lines = [_line(indent, LayoutLineKind.OPEN, marker, _label_prefix(field_key) + "{")]
        child_blocks = [
            _render_replace_block(marker, item, indent + 1, field_key=key)
            for key, item in value.items()
        ]
        _apply_trailing_commas(child_blocks)
        lines.extend(_flatten_blocks(child_blocks))
        lines.append(_line(indent, LayoutLineKind.CLOSE, marker, "}"))
        return lines

    if isinstance(value, list):
        lines = [_line(indent, LayoutLineKind.OPEN, marker, _label_prefix(field_key) + "[")]
        child_blocks = [_render_replace_block(marker, item, indent + 1) for item in value]
        _apply_trailing_commas(child_blocks)
        lines.extend(_flatten_blocks(child_blocks))
        lines.append(_line(indent, LayoutLineKind.CLOSE, marker, "]"))
        return lines

    raise TypeError(f"Unsupported replacement value: {type(value)!r}")


def _move_note_text(node: DiffNode) -> str:
    assert node.move_detail is not None
    detail = node.move_detail
    if detail.basis is MoveBasis.IDENTITY_KEY and detail.identity_label is not None:
        basis_text = f"{detail.identity_label.field_name}={detail.identity_label.value_text}"
    else:
        basis_text = "exact value"
    return (
        f"moved {format_display_path(detail.old_path)} -> "
        f"{format_display_path(detail.new_path)} ({basis_text})"
    )


def _render_inline_string_detail(detail) -> str:
    parts: list[str] = []
    for chunk in detail.chunks:
        escaped = json_string_fragment(chunk.text)
        if chunk.role == "same":
            parts.append(escaped)
        elif chunk.role == "removed":
            parts.append(f"[-{escaped}-]")
        else:
            parts.append(f"[+{escaped}+]")
    return f"\"{''.join(parts)}\""


def _render_labelled_scalar(field_key: str | None, value: object, root: bool = False) -> str:
    return f"{_label_prefix(field_key, root=root)}{render_json_scalar(value)}"


def _label_prefix(field_key: str | None, root: bool = False) -> str:
    if root:
        return "$: "
    if field_key is None:
        return ""
    return f"{render_json_scalar(field_key)}: "


def _field_key(node: DiffNode) -> str:
    path = node.new_path if node.new_index is not None else node.old_path
    key = path[-1]
    assert isinstance(key, str)
    return key


def _is_collapsible_unchanged(node: DiffNode) -> bool:
    return node.status is DiffStatus.UNCHANGED and node.move_detail is None


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _line(indent: int, kind: LayoutLineKind, marker: str, text: str) -> LayoutLine:
    return LayoutLine(indent=indent, kind=kind, marker=marker, text=text)


def _value_line(indent: int, marker: str, text: str) -> LayoutLine:
    return _line(indent, LayoutLineKind.VALUE, marker, text)


def _summary_line(indent: int, marker: str, text: str) -> LayoutLine:
    return _line(indent, LayoutLineKind.SUMMARY, marker, text)


def _note_line(indent: int, text: str) -> LayoutLine:
    return _line(indent, LayoutLineKind.NOTE, ">", text)
