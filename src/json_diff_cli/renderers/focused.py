from __future__ import annotations

from ..types import DiffKind, DiffNode
from .common import ordered_child_keys
from .full import render_full


def render_focused(
    node: DiffNode,
    *,
    color: str,
    context_lines: int,
    sort_keys: bool = False,
) -> str:
    blocks = _collect_focused_blocks(node, sort_keys=sort_keys)
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
    sort_keys: bool,
) -> list[DiffNode]:
    if node.kind in (DiffKind.ADDED, DiffKind.REMOVED, DiffKind.REPLACED):
        return [node]

    if node.kind is DiffKind.UNCHANGED:
        return []

    blocks: list[DiffNode] = []
    if isinstance(node.children, dict):
        for key in ordered_child_keys(node.children, sort_keys=sort_keys):
            blocks.extend(_collect_focused_blocks(node.children[key], sort_keys=sort_keys))
        return blocks

    for child in node.children:
        blocks.extend(_collect_focused_blocks(child, sort_keys=sort_keys))
    return blocks


def _render_block(
    node: DiffNode,
    *,
    color: str,
    context_lines: int,
    sort_keys: bool,
) -> str:
    rendered_lines = render_full(node, color=color, sort_keys=sort_keys).splitlines()
    rendered_lines = _select_context_lines(
        rendered_lines,
        changed_indexes=_changed_line_indexes(node, rendered_lines),
        context_lines=context_lines,
    )

    if not rendered_lines:
        return node.path
    return f"{node.path}\n" + "\n".join(rendered_lines)


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


def _changed_line_indexes(node: DiffNode, rendered_lines: list[str]) -> list[int]:
    if not rendered_lines:
        return []
    return list(range(len(rendered_lines)))
