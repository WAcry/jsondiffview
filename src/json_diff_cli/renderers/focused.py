from __future__ import annotations

from ..types import DiffKind, DiffNode
from .full import render_full


def render_focused(node: DiffNode, *, color: str, context_lines: int) -> str:
    blocks = _collect_focused_blocks(node, context_lines=context_lines)
    return "\n\n".join(
        _render_block(block, color=color, context_lines=context_lines)
        for block in blocks
    )


def _collect_focused_blocks(
    node: DiffNode,
    *,
    context_lines: int,
) -> list[DiffNode]:
    if node.kind in (DiffKind.ADDED, DiffKind.REMOVED, DiffKind.REPLACED):
        return [node]

    if node.kind is DiffKind.UNCHANGED:
        return []

    if context_lines > 0 and _has_multiple_direct_changes(node):
        return [node]

    children = node.children.values() if isinstance(node.children, dict) else node.children
    blocks: list[DiffNode] = []
    for child in children:
        blocks.extend(_collect_focused_blocks(child, context_lines=context_lines))
    return blocks


def _has_multiple_direct_changes(node: DiffNode) -> bool:
    if isinstance(node.children, dict):
        changed_children = sum(
            1 for child in node.children.values() if child.kind is not DiffKind.UNCHANGED
        )
    else:
        changed_children = sum(
            1 for child in node.children if child.kind is not DiffKind.UNCHANGED
        )
    return changed_children >= 2


def _render_block(node: DiffNode, *, color: str, context_lines: int) -> str:
    marker_lines = render_full(node, color="never").splitlines()
    rendered_lines = render_full(node, color=color).splitlines()

    if node.kind in (DiffKind.OBJECT, DiffKind.ARRAY):
        rendered_lines = _select_context_lines(
            rendered_lines,
            marker_lines=marker_lines,
            context_lines=context_lines,
        )

    if not rendered_lines:
        return node.path
    return f"{node.path}\n" + "\n".join(rendered_lines)


def _select_context_lines(
    rendered_lines: list[str],
    *,
    marker_lines: list[str],
    context_lines: int,
) -> list[str]:
    changed_indexes = [
        index for index, line in enumerate(marker_lines) if _line_contains_change_marker(line)
    ]
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


def _line_contains_change_marker(line: str) -> bool:
    return "[+" in line or "[-" in line or "+]" in line or "-]" in line
