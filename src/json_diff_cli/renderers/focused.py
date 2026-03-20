from __future__ import annotations

from dataclasses import dataclass

from ..types import DiffKind, DiffNode
from .common import ordered_child_keys, resolve_color_mode
from .full import (
    _append_suffix_to_blocks,
    _attach_array_item,
    _attach_object_field,
    _materialize_block_breaks,
    _render_node_lines,
    render_full,
)


@dataclass(frozen=True)
class _FocusedBlock:
    node: DiffNode
    context_node: DiffNode


def render_focused(
    node: DiffNode,
    *,
    color: str,
    context_lines: int,
    sort_keys: bool = False,
) -> str:
    blocks = _collect_focused_blocks(node, parent=None, sort_keys=sort_keys)
    return "\n\n".join(
        _render_block(
            block,
            color=color,
            context_lines=context_lines,
            sort_keys=sort_keys,
        )
        for block in blocks
    )


def _collect_focused_blocks(
    node: DiffNode,
    *,
    parent: DiffNode | None,
    sort_keys: bool,
) -> list[_FocusedBlock]:
    if node.kind in (DiffKind.ADDED, DiffKind.REMOVED, DiffKind.REPLACED):
        return [_FocusedBlock(node=node, context_node=parent or node)]

    if node.kind is DiffKind.UNCHANGED:
        return []

    blocks: list[_FocusedBlock] = []
    if isinstance(node.children, dict):
        for key in ordered_child_keys(node.children, sort_keys=sort_keys):
            blocks.extend(
                _collect_focused_blocks(
                    node.children[key],
                    parent=node,
                    sort_keys=sort_keys,
                )
            )
        return blocks

    for child in node.children:
        blocks.extend(_collect_focused_blocks(child, parent=node, sort_keys=sort_keys))
    return blocks


def _render_block(
    block: _FocusedBlock,
    *,
    color: str,
    context_lines: int,
    sort_keys: bool,
) -> str:
    rendered_lines, changed_indexes = _render_block_lines(
        block,
        color=color,
        context_lines=context_lines,
        sort_keys=sort_keys,
    )
    rendered_lines = _select_context_lines(
        rendered_lines,
        changed_indexes=changed_indexes,
        context_lines=context_lines,
    )

    if not rendered_lines:
        return block.node.path
    return f"{block.node.path}\n" + "\n".join(rendered_lines)


def _render_block_lines(
    block: _FocusedBlock,
    *,
    color: str,
    context_lines: int,
    sort_keys: bool,
) -> tuple[list[str], list[int]]:
    if context_lines <= 0 or block.context_node is block.node:
        rendered_lines = render_full(
            block.node,
            color=color,
            sort_keys=sort_keys,
        ).splitlines()
        return rendered_lines, _changed_line_indexes(rendered_lines)

    return _render_context_lines(
        block.context_node,
        target_node=block.node,
        color=color,
        sort_keys=sort_keys,
    )


def _render_context_lines(
    context_node: DiffNode,
    *,
    target_node: DiffNode,
    color: str,
    sort_keys: bool,
) -> tuple[list[str], list[int]]:
    color_mode = resolve_color_mode(color)

    if context_node.kind is DiffKind.OBJECT and isinstance(context_node.children, dict):
        keys = ordered_child_keys(context_node.children, sort_keys=sort_keys)
        lines = ["{"]
        changed_indexes: list[int] = []

        for index, key in enumerate(keys):
            child = context_node.children[key]
            child_lines = _render_node_lines(
                child,
                indent=1,
                color=color,
                sort_keys=sort_keys,
            )
            child_lines = _attach_object_field(key, child_lines, indent=1)
            if index < len(keys) - 1:
                child_lines = _append_suffix_to_blocks(child_lines, ",")
            materialized = _materialize_block_breaks(child_lines, color_mode=color_mode)
            start = len(lines)
            lines.extend(materialized)
            if child is target_node:
                changed_indexes.extend(range(start, len(lines)))

        lines.append("}")
        return lines, changed_indexes

    if context_node.kind is DiffKind.ARRAY and isinstance(context_node.children, tuple):
        lines = ["["]
        changed_indexes: list[int] = []

        for index, child in enumerate(context_node.children):
            child_lines = _render_node_lines(
                child,
                indent=1,
                color=color,
                sort_keys=sort_keys,
            )
            child_lines = _attach_array_item(child_lines, indent=1)
            if index < len(context_node.children) - 1:
                child_lines = _append_suffix_to_blocks(child_lines, ",")
            materialized = _materialize_block_breaks(child_lines, color_mode=color_mode)
            start = len(lines)
            lines.extend(materialized)
            if child is target_node:
                changed_indexes.extend(range(start, len(lines)))

        lines.append("]")
        return lines, changed_indexes

    rendered_lines = render_full(context_node, color=color, sort_keys=sort_keys).splitlines()
    return rendered_lines, _changed_line_indexes(rendered_lines)


def _select_context_lines(
    rendered_lines: list[str],
    *,
    changed_indexes: list[int],
    context_lines: int,
) -> list[str]:
    if not changed_indexes:
        return rendered_lines

    windows = _merge_windows(
        [
            (
                max(0, index - context_lines),
                min(len(rendered_lines) - 1, index + context_lines),
            )
            for index in changed_indexes
        ]
    )

    selected: list[str] = []
    for start, end in windows:
        selected.extend(rendered_lines[start : end + 1])
    if windows[0][0] > 0:
        selected.insert(0, rendered_lines[0])
    if windows[-1][1] < len(rendered_lines) - 1:
        selected.append(rendered_lines[-1])
    return selected


def _merge_windows(windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not windows:
        return []

    ordered_windows = sorted(windows)
    merged = [ordered_windows[0]]

    for start, end in ordered_windows[1:]:
        previous_start, previous_end = merged[-1]
        if start <= previous_end + 1:
            merged[-1] = (previous_start, max(previous_end, end))
            continue
        merged.append((start, end))

    return merged


def _changed_line_indexes(rendered_lines: list[str]) -> list[int]:
    if not rendered_lines:
        return []
    return list(range(len(rendered_lines)))
