from __future__ import annotations

import json
import sys
from collections.abc import Mapping

from ..text_diff import StringFragment
from ..types import JsonValue


INDENT = "  "
ANSI_RESET = "\x1b[0m"
ANSI_RED = "\x1b[31m"
ANSI_GREEN = "\x1b[32m"


def indent_text(level: int) -> str:
    return INDENT * level


def json_text(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False)


def json_preview(value: JsonValue, *, sort_keys: bool = False) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=sort_keys)


def ordered_object_keys(mapping: Mapping[str, JsonValue], *, sort_keys: bool) -> list[str]:
    keys = list(mapping)
    if sort_keys:
        keys.sort()
    return keys


def ordered_child_keys(children: Mapping[str, object], *, sort_keys: bool) -> list[str]:
    keys = list(children)
    if sort_keys:
        keys.sort()
    return keys


def append_suffix(lines: list[str], suffix: str) -> list[str]:
    if not lines:
        return lines
    updated = list(lines)
    updated[-1] = f"{updated[-1]}{suffix}"
    return updated


def strip_indent(line: str, level: int) -> str:
    prefix = indent_text(level)
    if line.startswith(prefix):
        return line[len(prefix) :]
    for marker in ("[+", "[-", ANSI_GREEN, ANSI_RED):
        if not line.startswith(marker):
            continue
        remainder = line[len(marker) :]
        if remainder.startswith(prefix):
            return f"{marker}{remainder[len(prefix) :]}"
    return line


def format_replaced_scalar(left: JsonValue, right: JsonValue, *, color: str) -> str:
    color_mode = resolve_color_mode(color)
    left_text = json_text(left)
    right_text = json_text(right)
    if color_mode == "ansi":
        return f"{ANSI_RED}{left_text}{ANSI_RESET} -> {ANSI_GREEN}{right_text}{ANSI_RESET}"
    if color_mode == "plain":
        return f"{left_text} -> {right_text}"
    return f"[-{left_text}-][+{right_text}+]"


def format_replaced_string(
    fragments: tuple[StringFragment, ...],
    *,
    left: str,
    right: str,
    color: str,
) -> str:
    color_mode = resolve_color_mode(color)
    if color_mode != "markers":
        return format_replaced_scalar(left, right, color=color)

    rendered_parts: list[str] = []
    for fragment in fragments:
        text = _json_string_inner(fragment.text)
        if fragment.role == "equal":
            rendered_parts.append(text)
            continue
        if fragment.role == "remove":
            rendered_parts.append(f"[-{text}-]")
            continue
        rendered_parts.append(f"[+{text}+]")

    return f"\"{''.join(rendered_parts)}\""


def format_changed_value(
    value: JsonValue,
    *,
    role: str,
    color: str,
    sort_keys: bool = False,
) -> str:
    text = json_preview(value, sort_keys=sort_keys)
    color_mode = resolve_color_mode(color)
    if color_mode == "markers":
        if role == "add":
            return f"[+{text}+]"
        if role == "remove":
            return f"[-{text}-]"
    if color_mode != "ansi":
        return text
    if role == "add":
        return f"{ANSI_GREEN}{text}{ANSI_RESET}"
    if role == "remove":
        return f"{ANSI_RED}{text}{ANSI_RESET}"
    return text


def format_changed_string_preview(
    fragments: tuple[StringFragment, ...],
    *,
    mode: str,
    color: str,
) -> str:
    color_mode = resolve_color_mode(color)
    rendered_parts: list[str] = []

    for fragment in fragments:
        if fragment.role == "equal":
            rendered_parts.append(_json_string_inner(fragment.text))
            continue
        if fragment.role == "remove":
            if mode == "new":
                continue
            if color_mode == "plain":
                rendered_parts.append(_json_string_inner(fragment.text))
                continue
            rendered_parts.append(
                _format_changed_fragment(_json_string_inner(fragment.text), "remove", color_mode)
            )
            continue
        if mode == "old":
            continue
        if color_mode == "plain":
            rendered_parts.append(_json_string_inner(fragment.text))
            continue
        rendered_parts.append(
            _format_changed_fragment(_json_string_inner(fragment.text), "add", color_mode)
        )

    return f"\"{''.join(rendered_parts)}\""


def wrap_added_lines(lines: list[str], *, color: str) -> list[str]:
    return _wrap_lines(lines, marker="added", color=color)


def wrap_removed_lines(lines: list[str], *, color: str) -> list[str]:
    return _wrap_lines(lines, marker="removed", color=color)


def _wrap_lines(lines: list[str], *, marker: str, color: str) -> list[str]:
    color_mode = resolve_color_mode(color)
    if color_mode == "ansi":
        prefix = ANSI_GREEN if marker == "added" else ANSI_RED
        return [f"{prefix}{line}{ANSI_RESET}" for line in lines]
    if color_mode == "plain":
        token = "+" if marker == "added" else "-"
        if len(lines) == 1:
            return [_insert_prefix_after_indent(lines[0], token)]
        wrapped = list(lines)
        wrapped[0] = _insert_prefix_after_indent(wrapped[0], token)
        wrapped[-1] = _insert_prefix_after_indent(wrapped[-1], token)
        return wrapped

    if len(lines) == 1:
        token = "+" if marker == "added" else "-"
        return [f"[{token}{lines[0]}{token}]"]

    token = "+" if marker == "added" else "-"
    wrapped = list(lines)
    wrapped[0] = f"[{token}{wrapped[0]}"
    wrapped[-1] = f"{wrapped[-1]}{token}]"
    return wrapped


def resolve_color_mode(color: str) -> str:
    if color == "always":
        return "ansi"
    if color == "never":
        return "markers"
    if color == "auto":
        return "ansi" if _stdout_supports_color() else "plain"
    raise ValueError(f"Unsupported color mode: {color}")


def _stdout_supports_color() -> bool:
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _insert_prefix_after_indent(line: str, prefix: str) -> str:
    index = 0
    while index < len(line) and line[index] == " ":
        index += 1
    return f"{line[:index]}{prefix}{line[index:]}"


def _json_string_inner(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)[1:-1]


def _format_changed_fragment(text: str, role: str, color_mode: str) -> str:
    if color_mode == "ansi":
        color = ANSI_GREEN if role == "add" else ANSI_RED
        return f"{color}{text}{ANSI_RESET}"
    return f"[{'+' if role == 'add' else '-'}{text}{'+' if role == 'add' else '-'}]"
