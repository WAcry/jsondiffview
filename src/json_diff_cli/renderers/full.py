from __future__ import annotations

from collections.abc import Mapping

from ..types import DiffKind, DiffNode, JsonValue, MISSING
from .common import (
    append_suffix,
    format_replaced_scalar,
    indent_text,
    json_text,
    ordered_child_keys,
    ordered_object_keys,
    strip_indent,
    wrap_added_lines,
    wrap_removed_lines,
)


def render_full(node: DiffNode, *, color: str, sort_keys: bool = False) -> str:
    return "\n".join(_render_node_lines(node, indent=0, color=color, sort_keys=sort_keys))


def _render_node_lines(
    node: DiffNode,
    *,
    indent: int,
    color: str,
    sort_keys: bool,
) -> list[str]:
    if node.kind is DiffKind.UNCHANGED:
        return _render_plain_value(node.right if node.right is not MISSING else node.left, indent=indent, sort_keys=sort_keys)
    if node.kind is DiffKind.ADDED:
        if node.right is MISSING:
            raise ValueError("Added diff node is missing right value")
        return wrap_added_lines(_render_plain_value(node.right, indent=indent, sort_keys=sort_keys), color=color)
    if node.kind is DiffKind.REMOVED:
        if node.left is MISSING:
            raise ValueError("Removed diff node is missing left value")
        return wrap_removed_lines(_render_plain_value(node.left, indent=indent, sort_keys=sort_keys), color=color)
    if node.kind is DiffKind.REPLACED:
        if node.left is MISSING or node.right is MISSING:
            raise ValueError("Replaced diff node is missing values")
        if _is_scalar(node.left) and _is_scalar(node.right):
            return [f"{indent_text(indent)}{format_replaced_scalar(node.left, node.right, color=color)}"]
        removed_lines = wrap_removed_lines(
            _render_plain_value(node.left, indent=indent, sort_keys=sort_keys),
            color=color,
        )
        added_lines = wrap_added_lines(
            _render_plain_value(node.right, indent=indent, sort_keys=sort_keys),
            color=color,
        )
        return [*removed_lines, *added_lines]
    if node.kind is DiffKind.OBJECT:
        return _render_object_node(node, indent=indent, color=color, sort_keys=sort_keys)
    if node.kind is DiffKind.ARRAY:
        return _render_array_node(node, indent=indent, color=color, sort_keys=sort_keys)
    raise ValueError(f"Unsupported diff node kind: {node.kind}")


def _render_plain_value(value: JsonValue, *, indent: int, sort_keys: bool) -> list[str]:
    if isinstance(value, Mapping):
        return _render_plain_object(value, indent=indent, sort_keys=sort_keys)
    if isinstance(value, list):
        return _render_plain_array(value, indent=indent, sort_keys=sort_keys)
    return [f"{indent_text(indent)}{json_text(value)}"]


def _render_plain_object(
    value: Mapping[str, JsonValue],
    *,
    indent: int,
    sort_keys: bool,
) -> list[str]:
    if not value:
        return [f"{indent_text(indent)}{{}}"]

    keys = ordered_object_keys(value, sort_keys=sort_keys)
    lines = [f"{indent_text(indent)}{{"]
    child_indent = indent + 1

    for index, key in enumerate(keys):
        child_lines = _render_plain_value(value[key], indent=child_indent, sort_keys=sort_keys)
        lines.extend(_attach_object_field(key, child_lines, indent=child_indent))
        if index < len(keys) - 1:
            lines = append_suffix(lines, ",")

    lines.append(f"{indent_text(indent)}}}")
    return lines


def _render_plain_array(
    value: list[JsonValue],
    *,
    indent: int,
    sort_keys: bool,
) -> list[str]:
    if not value:
        return [f"{indent_text(indent)}[]"]

    lines = [f"{indent_text(indent)}["]
    child_indent = indent + 1

    for index, item in enumerate(value):
        child_lines = _render_plain_value(item, indent=child_indent, sort_keys=sort_keys)
        lines.extend(_attach_array_item(child_lines, indent=child_indent))
        if index < len(value) - 1:
            lines = append_suffix(lines, ",")

    lines.append(f"{indent_text(indent)}]")
    return lines


def _render_object_node(
    node: DiffNode,
    *,
    indent: int,
    color: str,
    sort_keys: bool,
) -> list[str]:
    if not isinstance(node.children, dict) or not node.children:
        return [f"{indent_text(indent)}{{}}"]

    keys = ordered_child_keys(node.children, sort_keys=sort_keys)
    lines = [f"{indent_text(indent)}{{"]
    child_indent = indent + 1

    for index, key in enumerate(keys):
        child_lines = _render_node_lines(
            node.children[key],
            indent=child_indent,
            color=color,
            sort_keys=sort_keys,
        )
        lines.extend(_attach_object_field(key, child_lines, indent=child_indent))
        if index < len(keys) - 1:
            lines = append_suffix(lines, ",")

    lines.append(f"{indent_text(indent)}}}")
    return lines


def _render_array_node(
    node: DiffNode,
    *,
    indent: int,
    color: str,
    sort_keys: bool,
) -> list[str]:
    if not node.children:
        return [f"{indent_text(indent)}[]"]

    lines = [f"{indent_text(indent)}["]
    child_indent = indent + 1

    for index, child in enumerate(node.children):
        child_lines = _render_node_lines(
            child,
            indent=child_indent,
            color=color,
            sort_keys=sort_keys,
        )
        lines.extend(_attach_array_item(child_lines, indent=child_indent))
        if index < len(node.children) - 1:
            lines = append_suffix(lines, ",")

    lines.append(f"{indent_text(indent)}]")
    return lines


def _attach_object_field(key: str, value_lines: list[str], *, indent: int) -> list[str]:
    key_text = json_text(key)
    prefix = f"{indent_text(indent)}{key_text}: "
    attached = list(value_lines)
    attached[0] = f"{prefix}{strip_indent(attached[0], indent)}"
    return attached


def _attach_array_item(value_lines: list[str], *, indent: int) -> list[str]:
    attached = list(value_lines)
    attached[0] = f"{indent_text(indent)}{strip_indent(attached[0], indent)}"
    return attached


def _is_scalar(value: JsonValue) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))
