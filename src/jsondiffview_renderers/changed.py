from __future__ import annotations

from dataclasses import dataclass

from jsondiffview_renderers.common import (
    format_changed_string_preview,
    format_changed_value,
    ordered_child_keys,
)
from jsondiffview_types import DiffKind, DiffNode, MISSING


@dataclass(frozen=True)
class _ChangedBlock:
    node: DiffNode
    action: str


def render_changed(
    node: DiffNode,
    *,
    color: str,
    sort_keys: bool = False,
) -> str:
    blocks = _collect_changed_blocks(node, sort_keys=sort_keys)
    return "\n\n".join(
        _render_changed_block(block, color=color, sort_keys=sort_keys)
        for block in blocks
    )


def _collect_changed_blocks(
    node: DiffNode,
    *,
    sort_keys: bool,
) -> list[_ChangedBlock]:
    if node.kind is DiffKind.UNCHANGED:
        return []
    if node.kind is DiffKind.ADDED:
        return [_ChangedBlock(node=node, action="add")]
    if node.kind is DiffKind.REMOVED:
        return [_ChangedBlock(node=node, action="remove")]
    if node.kind is DiffKind.REPLACED:
        return [_ChangedBlock(node=node, action="replace")]

    blocks: list[_ChangedBlock] = []
    if isinstance(node.children, dict):
        for key in ordered_child_keys(node.children, sort_keys=False):
            blocks.extend(
                _collect_changed_blocks(node.children[key], sort_keys=sort_keys)
            )
        return blocks

    for child in node.children:
        blocks.extend(_collect_changed_blocks(child, sort_keys=sort_keys))
    return blocks


def _render_changed_block(
    block: _ChangedBlock,
    *,
    color: str,
    sort_keys: bool,
) -> str:
    node = block.node
    if node.display_path:
        lines = [f"{node.display_path} ({block.action})"]
    else:
        lines = [f"({block.action})"]
    if block.action != "add" and node.left is not MISSING:
        lines.append(
            f"  old: {_render_changed_preview(node, side='old', color=color, sort_keys=sort_keys)}"
        )
    if block.action != "remove" and node.right is not MISSING:
        lines.append(
            f"  new: {_render_changed_preview(node, side='new', color=color, sort_keys=sort_keys)}"
        )
    return "\n".join(lines)


def _render_changed_preview(
    node: DiffNode,
    *,
    side: str,
    color: str,
    sort_keys: bool,
) -> str:
    if (
        node.kind is DiffKind.REPLACED
        and node.text_diff is not None
        and isinstance(node.left, str)
        and isinstance(node.right, str)
    ):
        return format_changed_string_preview(
            node.text_diff.fragments,
            mode=side,
            color=color,
        )

    if side == "old":
        if node.left is MISSING:
            raise ValueError("Old preview requested for node without left value")
        return format_changed_value(
            node.left,
            role="remove",
            color=color,
            sort_keys=sort_keys,
        )

    if node.right is MISSING:
        raise ValueError("New preview requested for node without right value")
    return format_changed_value(
        node.right,
        role="add",
        color=color,
        sort_keys=sort_keys,
    )
