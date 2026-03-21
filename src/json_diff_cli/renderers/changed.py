from __future__ import annotations

from dataclasses import dataclass

from ..types import DiffKind, DiffNode, MISSING
from .common import json_text, ordered_child_keys


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
    del color

    blocks = _collect_changed_blocks(node, sort_keys=sort_keys)
    return "\n\n".join(_render_changed_block(block) for block in blocks)


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
        for key in ordered_child_keys(node.children, sort_keys=sort_keys):
            blocks.extend(
                _collect_changed_blocks(node.children[key], sort_keys=sort_keys)
            )
        return blocks

    for child in node.children:
        blocks.extend(_collect_changed_blocks(child, sort_keys=sort_keys))
    return blocks


def _render_changed_block(block: _ChangedBlock) -> str:
    node = block.node
    lines = [f"{node.path} ({block.action})"]
    if block.action != "add" and node.left is not MISSING:
        lines.append(f"  old: {json_text(node.left)}")
    if block.action != "remove" and node.right is not MISSING:
        lines.append(f"  new: {json_text(node.right)}")
    return "\n".join(lines)
