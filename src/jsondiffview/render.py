"""View projection and annotated JSON-shaped review layout."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import TypeAlias

from .model import (
    ArrayEntry,
    DiffNode,
    DiffStatus,
    JsonNumber,
    JsonPath,
    JsonValue,
    MatchKind,
    StyledSpan,
    StyleRole,
    View,
    json_kind,
)
from .strings import (
    BLOB_HARD_CODE_POINT_LIMIT,
    FragmentKind,
    LineKind,
    LineRow,
    MultilineStringDiff,
    ProjectedLongStringDiff,
    ShortStringDiff,
    StringMode,
    bounded_excerpt,
    build_string_diff,
    classify_string_mode,
    display_width,
    excerpt_cells_for_view,
    project_string_diff,
)

SUBTREE_SUMMARY_THRESHOLD = 8
SUMMARY_PREVIEW_CHILDREN = 2
SUMMARY_PREVIEW_ROW_LIMIT = 12
SUMMARY_PREVIEW_CELL_LIMIT = 1_024


@dataclass(slots=True)
class _Line:
    spans: list[StyledSpan]

    def add_comma(self) -> None:
        role = self.spans[-1].role if self.spans else StyleRole.DEFAULT
        self.spans.append(StyledSpan(",", role))


@dataclass(slots=True)
class _Block:
    lines: list[_Line]
    comma_line: int | None


@dataclass(frozen=True, slots=True)
class _Omission:
    count: int


_ProjectedItem: TypeAlias = int | _Omission


def render_diff(node: DiffNode, view: View) -> tuple[StyledSpan, ...]:
    """Render one semantic tree into styled spans ending in exactly one LF."""

    if node.status is DiffStatus.UNCHANGED:
        return ()
    block = _render_node(node, None, 0, view)
    spans: list[StyledSpan] = []
    for line in block.lines:
        spans.extend(line.spans)
        spans.append(StyledSpan("\n"))
    return tuple(spans)


def _render_node(
    node: DiffNode,
    label: str | None,
    indent: int,
    view: View,
    *,
    context_only: bool = False,
) -> _Block:
    if node.status is DiffStatus.ADDED:
        return _render_marked_raw(
            node.new,
            label,
            indent,
            view,
            "+ ",
            StyleRole.ADDED,
            "added",
        )
    if node.status is DiffStatus.REMOVED:
        return _render_marked_raw(
            node.old,
            label,
            indent,
            view,
            "- ",
            StyleRole.REMOVED,
            "removed",
        )
    if node.status is DiffStatus.UNCHANGED:
        return _render_unchanged_value(
            node.new,
            label,
            indent,
            view,
            context_only=context_only,
        )

    old = node.old
    new = node.new
    if isinstance(old, dict) and isinstance(new, dict):
        return _render_modified_object(node, label, indent, view)
    if isinstance(old, list) and isinstance(new, list):
        return _render_modified_array(node, label, indent, view)
    if isinstance(old, str) and isinstance(new, str):
        return _render_string_change(old, new, label, indent, view)
    if json_kind(old) == json_kind(new) and not isinstance(
        old,
        (dict, list, str),
    ):
        text = f"{_label(label)}{_scalar_text(old)} -> {_scalar_text(new)}"
        return _Block(
            [_uniform_line("~ ", indent, text, StyleRole.MODIFIED)],
            0,
        )
    return _render_replacement(old, new, label, indent, view)


def _render_modified_object(
    node: DiffNode,
    label: str | None,
    indent: int,
    view: View,
) -> _Block:
    opening = _uniform_line(
        "~ ",
        indent,
        f"{_label(label)}{{",
        StyleRole.MODIFIED,
    )
    changed = [
        member.node.status is not DiffStatus.UNCHANGED for member in node.object_members
    ]
    projected = _project_siblings(changed, view)
    child_blocks: list[_Block] = []
    for item in projected:
        if isinstance(item, _Omission):
            child_blocks.append(_omission_block(item.count, indent + 1, "field"))
            continue
        member = node.object_members[item]
        child_blocks.append(
            _render_node(
                member.node,
                _json_string(member.key),
                indent + 1,
                view,
            )
        )
    _apply_commas(child_blocks)
    lines = [opening]
    lines.extend(_flatten(child_blocks))
    lines.append(_uniform_line("  ", indent, "}", StyleRole.DEFAULT))
    return _Block(lines, len(lines) - 1)


def _render_modified_array(
    node: DiffNode,
    label: str | None,
    indent: int,
    view: View,
) -> _Block:
    opening = _uniform_line(
        "~ ",
        indent,
        f"{_label(label)}[",
        StyleRole.MODIFIED,
    )
    changed = [
        entry.node.status is not DiffStatus.UNCHANGED or entry.moved
        for entry in node.array_entries
    ]
    projected = _project_siblings(changed, view)
    child_blocks: list[_Block] = []
    for item in projected:
        if isinstance(item, _Omission):
            child_blocks.append(_omission_block(item.count, indent + 1, "item"))
            continue
        child_blocks.append(
            _render_array_entry(node.array_entries[item], indent + 1, view)
        )
    _apply_commas(child_blocks)
    lines = [opening]
    lines.extend(_flatten(child_blocks))
    lines.append(_uniform_line("  ", indent, "]", StyleRole.DEFAULT))
    return _Block(lines, len(lines) - 1)


def _render_array_entry(entry: ArrayEntry, indent: int, view: View) -> _Block:
    if entry.node.status is DiffStatus.REMOVED:
        label = f"[old {entry.old_index}]"
    else:
        label = f"[{entry.new_index}]"
    block = _render_node(
        entry.node,
        label,
        indent,
        view,
        context_only=entry.moved,
    )
    if not entry.moved:
        return block

    evidence = entry.evidence
    old_path = _path_text(entry.node.old_path or ())
    new_path = _path_text(entry.node.new_path or ())
    if evidence is not None and evidence.kind is MatchKind.IDENTITY:
        reason = (
            f"matched by {_json_string(evidence.key or '')}: "
            f"{_compact_json(evidence.key_value)}"
        )
    else:
        reason = "unique exact match"
    note = _uniform_line(
        "> ",
        indent,
        f"moved from {old_path} to {new_path} ({reason})",
        StyleRole.PROVENANCE,
    )
    comma_line = None if block.comma_line is None else block.comma_line + 1
    return _Block([note, *block.lines], comma_line)


def _render_unchanged_value(
    value: JsonValue,
    label: str | None,
    indent: int,
    view: View,
    *,
    context_only: bool,
) -> _Block:
    if isinstance(value, str) and _requires_bounded_scalar_string(value):
        return _render_bounded_string(
            value,
            label,
            indent,
            view,
            "  ",
            StyleRole.DEFAULT,
        )
    if not isinstance(value, (dict, list)):
        return _Block(
            [_uniform_line("  ", indent, f"{_label(label)}{_scalar_text(value)}")],
            0,
        )
    if not value:
        brackets = "{}" if isinstance(value, dict) else "[]"
        return _Block(
            [_uniform_line("  ", indent, f"{_label(label)}{brackets}")],
            0,
        )

    opening_character, closing_character = (
        ("{", "}")
        if isinstance(
            value,
            dict,
        )
        else ("[", "]")
    )
    lines = [
        _uniform_line(
            "  ",
            indent,
            f"{_label(label)}{opening_character}",
        )
    ]
    item_count = len(value)
    if view is View.SUMMARY:
        projected: list[_ProjectedItem] = [_Omission(item_count)]
    elif view is View.FULL:
        projected = list(range(item_count))
    else:
        projected = [0]
        if item_count > 1:
            projected.append(_Omission(item_count - 1))

    child_blocks: list[_Block] = []
    for item in projected:
        if isinstance(item, _Omission):
            noun = "field" if isinstance(value, dict) else "item"
            child_blocks.append(_omission_block(item.count, indent + 1, noun))
            continue
        if isinstance(value, dict):
            key = list(value)[item]
            child_blocks.append(
                _render_unchanged_value(
                    value[key],
                    _json_string(key),
                    indent + 1,
                    view,
                    context_only=context_only,
                )
            )
        else:
            child_blocks.append(
                _render_unchanged_value(
                    value[item],
                    f"[{item}]",
                    indent + 1,
                    view,
                    context_only=context_only,
                )
            )
    _apply_commas(child_blocks)
    lines.extend(_flatten(child_blocks))
    lines.append(_uniform_line("  ", indent, closing_character))
    return _Block(lines, len(lines) - 1)


def _render_marked_raw(
    value: JsonValue,
    label: str | None,
    indent: int,
    view: View,
    prefix: str,
    role: StyleRole,
    action: str,
) -> _Block:
    if isinstance(value, str) and _requires_bounded_scalar_string(value):
        return _render_bounded_string(value, label, indent, view, prefix, role)
    if (
        view is View.SUMMARY
        and isinstance(value, (dict, list))
        and _descendant_count(value) > SUBTREE_SUMMARY_THRESHOLD
    ):
        preview = _render_summary_preview(
            value,
            label,
            indent,
            prefix,
            role,
            action,
        )
        if preview is not None:
            return preview
        opening, closing = ("{", "}") if isinstance(value, dict) else ("[", "]")
        count = _descendant_count(value)
        text = (
            f"{_label(label)}{opening} … {count} {action} "
            f"{_plural('nested value', count)} omitted {closing}"
        )
        return _Block([_uniform_line(prefix, indent, text, role)], 0)
    if not isinstance(value, (dict, list)):
        return _Block(
            [
                _uniform_line(
                    prefix,
                    indent,
                    f"{_label(label)}{_scalar_text(value)}",
                    role,
                )
            ],
            0,
        )
    if not value:
        brackets = "{}" if isinstance(value, dict) else "[]"
        return _Block(
            [_uniform_line(prefix, indent, f"{_label(label)}{brackets}", role)],
            0,
        )

    opening_character, closing_character = (
        ("{", "}")
        if isinstance(
            value,
            dict,
        )
        else ("[", "]")
    )
    lines = [
        _uniform_line(
            prefix,
            indent,
            f"{_label(label)}{opening_character}",
            role,
        )
    ]
    child_blocks: list[_Block] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_blocks.append(
                _render_marked_raw(
                    child,
                    _json_string(key),
                    indent + 1,
                    view,
                    prefix,
                    role,
                    action,
                )
            )
    else:
        for index, child in enumerate(value):
            child_label = f"[old {index}]" if action == "removed" else f"[{index}]"
            child_blocks.append(
                _render_marked_raw(
                    child,
                    child_label,
                    indent + 1,
                    view,
                    prefix,
                    role,
                    action,
                )
            )
    _apply_commas(child_blocks)
    lines.extend(_flatten(child_blocks))
    lines.append(_uniform_line(prefix, indent, closing_character, role))
    return _Block(lines, len(lines) - 1)


def _render_summary_preview(
    value: dict[str, JsonValue] | list[JsonValue],
    label: str | None,
    indent: int,
    prefix: str,
    role: StyleRole,
    action: str,
) -> _Block | None:
    opening, closing = ("{", "}") if isinstance(value, dict) else ("[", "]")
    lines = [
        _uniform_line(
            prefix,
            indent,
            f"{_label(label)}{opening}",
            role,
        )
    ]
    child_blocks: list[_Block] = []
    if isinstance(value, dict):
        entries = list(value.items())
        for key, child in entries[:SUMMARY_PREVIEW_CHILDREN]:
            child_blocks.append(
                _render_marked_raw(
                    child,
                    _json_string(key),
                    indent + 1,
                    View.SUMMARY,
                    prefix,
                    role,
                    action,
                )
            )
        omitted = sum(
            1 + _descendant_count(child)
            for _key, child in entries[SUMMARY_PREVIEW_CHILDREN:]
        )
    else:
        for index, child in enumerate(value[:SUMMARY_PREVIEW_CHILDREN]):
            child_blocks.append(
                _render_marked_raw(
                    child,
                    f"[old {index}]" if action == "removed" else f"[{index}]",
                    indent + 1,
                    View.SUMMARY,
                    prefix,
                    role,
                    action,
                )
            )
        omitted = sum(
            1 + _descendant_count(child) for child in value[SUMMARY_PREVIEW_CHILDREN:]
        )
    if omitted:
        child_blocks.append(
            _Block(
                [
                    _uniform_line(
                        prefix,
                        indent + 1,
                        (
                            f"… {omitted} {action} "
                            f"{_plural('nested value', omitted)} omitted"
                        ),
                        role,
                    )
                ],
                None,
            )
        )
    _apply_commas(child_blocks)
    lines.extend(_flatten(child_blocks))
    lines.append(_uniform_line(prefix, indent, closing, role))
    if len(lines) > SUMMARY_PREVIEW_ROW_LIMIT:
        return None
    cells = sum(
        display_width("".join(span.text for span in line.spans)) for line in lines
    )
    if cells > SUMMARY_PREVIEW_CELL_LIMIT:
        return None
    return _Block(lines, len(lines) - 1)


def _render_bounded_string(
    value: str,
    label: str | None,
    indent: int,
    view: View,
    prefix: str,
    role: StyleRole,
) -> _Block:
    excerpt = bounded_excerpt(
        value,
        excerpt_cells_for_view(view),
        lambda text: _escape_json_fragment(text, marker_safe=True),
    )
    header = _uniform_line(
        prefix,
        indent,
        f"{_label(label)}<long string: {len(value)} code points>",
        role,
    )
    detail = _excerpt_line(
        prefix,
        indent + 1,
        excerpt.text,
        excerpt.omitted,
        role,
    )
    return _Block([header, detail], 1)


def _render_replacement(
    old: JsonValue,
    new: JsonValue,
    label: str | None,
    indent: int,
    view: View,
) -> _Block:
    header = _uniform_line(
        "~ ",
        indent,
        f"{_label(label)}{json_kind(old)} -> {json_kind(new)}",
        StyleRole.MODIFIED,
    )
    old_block = _render_marked_raw(
        old,
        label,
        indent + 1,
        view,
        "- ",
        StyleRole.REMOVED,
        "removed",
    )
    new_block = _render_marked_raw(
        new,
        label,
        indent + 1,
        view,
        "+ ",
        StyleRole.ADDED,
        "added",
    )
    lines = [header, *old_block.lines, *new_block.lines]
    return _Block(lines, len(lines) - 1)


def _render_string_change(
    old: str,
    new: str,
    label: str | None,
    indent: int,
    view: View,
) -> _Block:
    analysis = build_string_diff(old, new)
    string_diff = project_string_diff(
        analysis,
        view,
        lambda text: _escape_json_fragment(text, marker_safe=True),
    )
    if isinstance(string_diff, ShortStringDiff):
        return _render_short_string(string_diff, old, new, label, indent)
    if isinstance(string_diff, MultilineStringDiff):
        return _render_multiline_string(string_diff, label, indent)
    return _render_long_string(string_diff, label, indent)


def _render_short_string(
    string_diff: ShortStringDiff,
    old: str,
    new: str,
    label: str | None,
    indent: int,
) -> _Block:
    spans = [StyledSpan("~ " + "  " * indent + _label(label) + '"', StyleRole.MODIFIED)]
    old_marker_positions = _literal_marker_positions(old)
    new_marker_positions = _literal_marker_positions(new)
    for fragment in string_diff.fragments:
        if fragment.kind is FragmentKind.ADDED:
            source_offset = fragment.new_start or 0
            marker_positions = new_marker_positions
        else:
            source_offset = fragment.old_start or 0
            marker_positions = old_marker_positions
        escaped = _escape_json_fragment(
            fragment.text,
            marker_positions=marker_positions,
            source_offset=source_offset,
        )
        if fragment.kind is FragmentKind.UNCHANGED:
            spans.append(StyledSpan(escaped))
        elif fragment.kind is FragmentKind.REMOVED:
            spans.append(StyledSpan(f"[-{escaped}-]", StyleRole.REMOVED))
        else:
            spans.append(StyledSpan(f"[+{escaped}+]", StyleRole.ADDED))
    spans.append(StyledSpan('"', StyleRole.MODIFIED))
    return _Block([_Line(spans)], 0)


def _render_multiline_string(
    string_diff: MultilineStringDiff,
    label: str | None,
    indent: int,
) -> _Block:
    header = _uniform_line(
        "~ ",
        indent,
        (
            f"{_label(label)}<multiline string: "
            f"{string_diff.old_line_count} -> {string_diff.new_line_count} "
            "logical lines>"
        ),
        StyleRole.MODIFIED,
    )
    lines = [header]
    comma_line = 0
    for row in string_diff.rows:
        if row.kind is LineKind.OMITTED:
            lines.append(
                _uniform_line(
                    "… ",
                    indent + 1,
                    f"{row.count} unchanged {_plural('line', row.count)} omitted",
                )
            )
            continue
        if row.kind in {LineKind.REMOVED_OMITTED, LineKind.ADDED_OMITTED}:
            action = "removed" if row.kind is LineKind.REMOVED_OMITTED else "added"
            code_points = row.omitted_code_points
            code_point_detail = (
                f" / {code_points} {_plural('code point', code_points)}"
                if code_points
                else ""
            )
            lines.append(
                _uniform_line(
                    "… ",
                    indent + 1,
                    (
                        f"{row.count} {action} {_plural('line', row.count)}"
                        f"{code_point_detail} omitted"
                    ),
                )
            )
            continue
        prefix, role = {
            LineKind.UNCHANGED: ("  ", StyleRole.DEFAULT),
            LineKind.REMOVED: ("- ", StyleRole.REMOVED),
            LineKind.ADDED: ("+ ", StyleRole.ADDED),
        }[row.kind]
        if row.fragments:
            lines.append(
                _multiline_fragment_line(
                    row,
                    prefix,
                    role,
                    indent + 1,
                )
            )
        else:
            lines.append(
                _uniform_line(
                    prefix,
                    indent + 1,
                    _multiline_row_text(
                        row.text,
                        row.omitted_code_points,
                    ),
                    role,
                )
            )
        comma_line = len(lines) - 1
    return _Block(lines, comma_line)


def _multiline_fragment_line(
    row: LineRow,
    prefix: str,
    role: StyleRole,
    indent: int,
) -> _Line:
    spans = [StyledSpan(prefix + "  " * indent + '"', role)]
    marker_positions = _literal_marker_positions(row.text)
    for fragment in row.fragments:
        if row.kind is LineKind.ADDED:
            source_offset = fragment.new_start or 0
        else:
            source_offset = fragment.old_start or 0
        escaped = _escape_json_fragment(
            fragment.text,
            marker_positions=marker_positions,
            source_offset=source_offset,
        )
        if fragment.kind is FragmentKind.UNCHANGED:
            spans.append(StyledSpan(escaped))
        elif fragment.kind is FragmentKind.REMOVED:
            spans.append(StyledSpan(f"[-{escaped}-]", StyleRole.REMOVED))
        else:
            spans.append(StyledSpan(f"[+{escaped}+]", StyleRole.ADDED))
    spans.append(StyledSpan('"', role))
    if row.omitted_code_points:
        count = row.omitted_code_points
        spans.append(
            StyledSpan(
                (
                    f" ({count} {_plural('code point', count)} "
                    "omitted within logical line)"
                ),
                role,
            )
        )
    return _Line(spans)


def _multiline_row_text(text: str, omitted: int) -> str:
    rendered = _json_string(text, marker_safe=True)
    if not omitted:
        return rendered
    return (
        f"{rendered} ({omitted} "
        f"{_plural('code point', omitted)} omitted within logical line)"
    )


def _render_long_string(
    string_diff: ProjectedLongStringDiff,
    label: str | None,
    indent: int,
) -> _Block:
    hunk_count = len(string_diff.hunks)
    header = _uniform_line(
        "~ ",
        indent,
        (
            f"{_label(label)}<long string: {string_diff.old_length} -> "
            f"{string_diff.new_length} code points; {hunk_count} "
            f"{_plural('hunk', hunk_count)}>"
        ),
        StyleRole.MODIFIED,
    )
    lines = [header]
    if string_diff.hunks:
        first = string_diff.hunks[0]
        before_text = _long_omission_text(
            first.old_excerpt.source_start,
            first.new_excerpt.source_start,
            "before",
        )
    else:
        before_text = None
    if before_text is not None:
        lines.append(
            _uniform_line(
                "… ",
                indent + 1,
                before_text,
            )
        )

    comma_line = 0
    for ordinal, hunk in enumerate(string_diff.hunks, start=1):
        if ordinal > 1:
            previous = string_diff.hunks[ordinal - 2]
            gap_text = _long_omission_text(
                hunk.old_excerpt.source_start - previous.old_excerpt.source_end,
                hunk.new_excerpt.source_start - previous.new_excerpt.source_end,
                "between hunks",
            )
            if gap_text is not None:
                lines.append(_uniform_line("… ", indent + 1, gap_text))
        lines.append(
            _uniform_line(
                "~ ",
                indent + 1,
                (
                    f"hunk {ordinal}/{hunk_count} "
                    f"(old {hunk.old_start}:{hunk.old_end}; "
                    f"new {hunk.new_start}:{hunk.new_end})"
                ),
                StyleRole.MODIFIED,
            )
        )
        lines.append(
            _excerpt_line(
                "- ",
                indent + 2,
                hunk.old_excerpt.text,
                hunk.old_excerpt.omitted,
                StyleRole.REMOVED,
            )
        )
        lines.append(
            _excerpt_line(
                "+ ",
                indent + 2,
                hunk.new_excerpt.text,
                hunk.new_excerpt.omitted,
                StyleRole.ADDED,
            )
        )
        comma_line = len(lines) - 1
    if string_diff.hunks:
        last = string_diff.hunks[-1]
        after_text = _long_omission_text(
            string_diff.old_length - last.old_excerpt.source_end,
            string_diff.new_length - last.new_excerpt.source_end,
            "after",
        )
    else:
        after_text = None
    if after_text is not None:
        lines.append(
            _uniform_line(
                "… ",
                indent + 1,
                after_text,
            )
        )
    return _Block(lines, comma_line)


def _long_omission_text(
    old_count: int,
    new_count: int,
    location: str,
) -> str | None:
    if old_count == new_count == 0:
        return None
    if old_count == new_count:
        return (
            f"{old_count} unchanged {_plural('code point', old_count)} "
            f"omitted {location}"
        )
    return f"{old_count} old / {new_count} new unchanged code points omitted {location}"


def _excerpt_line(
    prefix: str,
    indent: int,
    text: str,
    omitted: int,
    role: StyleRole,
) -> _Line:
    suffix = ""
    if omitted:
        suffix = f" ({omitted} {_plural('code point', omitted)} omitted within excerpt)"
    return _uniform_line(
        prefix,
        indent,
        _json_string(text, marker_safe=True) + suffix,
        role,
    )


def _project_siblings(changed: list[bool], view: View) -> list[_ProjectedItem]:
    if view is View.FULL:
        return list(range(len(changed)))

    result: list[_ProjectedItem] = []
    index = 0
    while index < len(changed):
        if changed[index]:
            result.append(index)
            index += 1
            continue
        end = index
        while end < len(changed) and not changed[end]:
            end += 1
        count = end - index
        if view is View.SUMMARY:
            result.append(_Omission(count))
        else:
            has_change_before = index > 0
            has_change_after = end < len(changed)
            if has_change_before and has_change_after:
                result.append(index)
                if count > 2:
                    result.append(_Omission(count - 2))
                if count > 1:
                    result.append(end - 1)
            elif has_change_before:
                result.append(index)
                if count > 1:
                    result.append(_Omission(count - 1))
            elif has_change_after:
                if count > 1:
                    result.append(_Omission(count - 1))
                result.append(end - 1)
            else:
                result.append(index)
                if count > 1:
                    result.append(_Omission(count - 1))
        index = end
    return result


def _omission_block(count: int, indent: int, noun: str) -> _Block:
    return _Block(
        [
            _uniform_line(
                "… ",
                indent,
                f"{count} unchanged {_plural(noun, count)} omitted",
            )
        ],
        None,
    )


def _apply_commas(blocks: list[_Block]) -> None:
    for block in blocks[:-1]:
        comma_line = block.comma_line
        if comma_line is not None:
            block.lines[comma_line].add_comma()


def _flatten(blocks: list[_Block]) -> list[_Line]:
    return [line for block in blocks for line in block.lines]


def _uniform_line(
    prefix: str,
    indent: int,
    text: str,
    role: StyleRole = StyleRole.DEFAULT,
) -> _Line:
    return _Line([StyledSpan(prefix + "  " * indent + text, role)])


def _label(label: str | None) -> str:
    return "" if label is None else f"{label}: "


def _scalar_text(value: JsonValue) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, JsonNumber):
        return value.lexeme
    if isinstance(value, str):
        return _json_string(value)
    return _compact_json(value)


def _compact_json(value: JsonValue) -> str:
    if isinstance(value, str) and _requires_bounded_scalar_string(value):
        excerpt = bounded_excerpt(
            value,
            excerpt_cells_for_view(View.REVIEW),
            lambda text: _escape_json_fragment(text, marker_safe=True),
        )
        return (
            f"<long string: {len(value)} code points; excerpt "
            f"{_json_string(excerpt.text, marker_safe=True)}; "
            f"{excerpt.omitted} {_plural('code point', excerpt.omitted)} "
            "omitted within excerpt>"
        )
    if not isinstance(value, (dict, list)):
        return _scalar_text(value)
    if isinstance(value, list):
        return "[" + ", ".join(_compact_json(item) for item in value) + "]"
    return (
        "{"
        + ", ".join(
            f"{_json_string(key)}: {_compact_json(item)}" for key, item in value.items()
        )
        + "}"
    )


def _json_string(value: str, *, marker_safe: bool = True) -> str:
    return f'"{_escape_json_fragment(value, marker_safe=marker_safe)}"'


def _escape_json_fragment(
    value: str,
    *,
    marker_safe: bool = False,
    marker_positions: set[int] | None = None,
    source_offset: int = 0,
) -> str:
    parts: list[str] = []
    if marker_safe and marker_positions is None:
        marker_positions = _literal_marker_positions(value)
    short_escapes = {
        '"': '\\"',
        "\\": "\\\\",
        "\b": "\\b",
        "\f": "\\f",
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
    }
    for index, character in enumerate(value):
        if marker_positions is not None and source_offset + index in marker_positions:
            parts.append("\\u005b" if character == "[" else "\\u005d")
            continue
        escaped = short_escapes.get(character)
        if escaped is not None:
            parts.append(escaped)
            continue
        code_point = ord(character)
        if (
            unicodedata.category(character) == "Cc"
            or code_point in {0x2028, 0x2029}
            or 0xD800 <= code_point <= 0xDFFF
        ):
            parts.append(f"\\u{code_point:04x}")
        else:
            parts.append(character)
    return "".join(parts)


def _literal_marker_positions(value: str) -> set[int]:
    positions: set[int] = set()
    for index, character in enumerate(value):
        if (
            character == "[" and index + 1 < len(value) and value[index + 1] in "-+"
        ) or (character == "]" and index > 0 and value[index - 1] in "-+"):
            positions.add(index)
    return positions


def _path_text(path: JsonPath) -> str:
    parts = ["$"]
    for part in path:
        if isinstance(part, int):
            parts.append(f"[{part}]")
        elif part.isidentifier():
            parts.append(f".{part}")
        else:
            parts.append(f"[{_json_string(part)}]")
    return "".join(parts)


def _descendant_count(value: JsonValue) -> int:
    if isinstance(value, list):
        return sum(1 + _descendant_count(item) for item in value)
    if isinstance(value, dict):
        return sum(1 + _descendant_count(item) for item in value.values())
    return 0


def _is_long_single_line(value: str) -> bool:
    return classify_string_mode(value, "") is StringMode.BLOB


def _requires_bounded_scalar_string(value: str) -> bool:
    return len(value) >= BLOB_HARD_CODE_POINT_LIMIT or _is_long_single_line(value)


def _plural(noun: str, count: int) -> str:
    return noun if count == 1 else f"{noun}s"
