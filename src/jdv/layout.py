from __future__ import annotations

from typing import Iterable
from wcwidth import wcswidth

from .model import (
    DiffNode,
    DiffSettings,
    DiffStatus,
    LayoutLine,
    LayoutLineKind,
    LayoutPlan,
    LayoutSpan,
    MoveBasis,
    ReviewMode,
    StringDetail,
    StringLine,
    StringMode,
    StringSpan,
)
from .paths import format_display_path, json_string_fragment, render_json_scalar
from .string_diff import split_graphemes


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

    return _emit_modified_leaf(node, review_mode, settings, indent, field_key, root=root)


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
    child_blocks: list[list[LayoutLine]]
    remaining = 0
    if (
        review_mode is ReviewMode.COMPACT
        and len(children) > preview_limit
        and _estimate_compact_pure_change_container_full_lines(children, settings, is_array=False) >= settings.compact_summary_min_lines
    ):
        child_blocks = [
            _emit_added_removed_block(child, review_mode, settings, indent + 1, _field_key(child), marker)
            for child in children[:preview_limit]
        ]
        remaining = len(children) - preview_limit
    else:
        child_blocks = [
            _emit_added_removed_block(child, review_mode, settings, indent + 1, _field_key(child), marker)
            for child in children
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
    child_blocks: list[list[LayoutLine]]
    remaining = 0
    if (
        review_mode is ReviewMode.COMPACT
        and len(children) > preview_limit
        and _estimate_compact_pure_change_container_full_lines(children, settings, is_array=True) >= settings.compact_summary_min_lines
    ):
        child_blocks = [
            _emit_added_removed_block(child, review_mode, settings, indent + 1, None, marker)
            for child in children[:preview_limit]
        ]
        remaining = len(children) - preview_limit
    else:
        child_blocks = [
            _emit_added_removed_block(child, review_mode, settings, indent + 1, None, marker)
            for child in children
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
    review_mode: ReviewMode,
    settings: DiffSettings,
    indent: int,
    field_key: str | None,
    root: bool,
) -> list[LayoutLine]:
    if node.string_detail is not None:
        return _emit_string_detail(node.string_detail, indent, field_key, root, review_mode, settings)

    label_prefix = _label_prefix(field_key, root=root)

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

        if review_mode is ReviewMode.COMPACT and child.status in (DiffStatus.ADDED, DiffStatus.REMOVED):
            start = index
            status = child.status
            group: list[DiffNode] = []
            while index < len(sequence) and sequence[index].status is status and sequence[index].move_detail is None:
                group.append(sequence[index])
                index += 1

            preview_limit = settings.compact_preview_items if is_array else settings.compact_preview_keys
            estimated_lines = _estimate_compact_pure_change_group_lines(group, settings, is_array)
            if len(group) > preview_limit and estimated_lines >= settings.compact_summary_min_lines:
                marker = "+" if status is DiffStatus.ADDED else "-"
                noun = "added" if status is DiffStatus.ADDED else "removed"
                target = "items" if is_array else "keys"
                blocks.extend(
                    _build_child_block(group_child, review_mode, settings, indent, is_array)
                    for group_child in group[:preview_limit]
                )
                blocks.append([_summary_line(indent, marker, f"… {len(group) - preview_limit} more {noun} {target}")])
            else:
                blocks.extend(
                    _build_child_block(group_child, review_mode, settings, indent, is_array)
                    for group_child in group
                )
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
            spans=last_line.spans,
        )


def _flatten_blocks(blocks: Iterable[list[LayoutLine]]) -> list[LayoutLine]:
    lines: list[LayoutLine] = []
    for block in blocks:
        lines.extend(block)
    return lines


def _count_block_lines(blocks: Iterable[list[LayoutLine]]) -> int:
    return sum(len(block) for block in blocks)


def _estimate_compact_pure_change_container_lines(
    children: Iterable[DiffNode],
    settings: DiffSettings,
    is_array: bool,
) -> int:
    child_lines = [
        _estimate_compact_pure_change_node_lines(child, settings)
        for child in children
    ]
    preview_limit = settings.compact_preview_items if is_array else settings.compact_preview_keys
    total_lines = sum(child_lines) + 2
    if len(child_lines) > preview_limit and total_lines >= settings.compact_summary_min_lines:
        return sum(child_lines[:preview_limit]) + 1 + 2
    return total_lines


def _estimate_compact_pure_change_container_full_lines(
    children: Iterable[DiffNode],
    settings: DiffSettings,
    is_array: bool,
) -> int:
    _ = is_array
    return sum(_estimate_compact_pure_change_node_lines(child, settings) for child in children) + 2


def _estimate_compact_pure_change_group_lines(
    children: Iterable[DiffNode],
    settings: DiffSettings,
    is_array: bool,
) -> int:
    return sum(
        _estimate_compact_child_block_lines(child, settings, is_array)
        for child in children
    )


def _estimate_compact_child_block_lines(
    node: DiffNode,
    settings: DiffSettings,
    is_array: bool,
) -> int:
    note_lines = 1 if is_array and node.status is DiffStatus.REMOVED else 0
    return note_lines + _estimate_compact_pure_change_node_lines(node, settings)


def _estimate_compact_pure_change_node_lines(node: DiffNode, settings: DiffSettings) -> int:
    value = node.new_value if node.status is DiffStatus.ADDED else node.old_value
    if _is_scalar(value):
        return 1
    if isinstance(value, dict):
        return _estimate_compact_pure_change_container_lines(node.children, settings, is_array=False)
    if isinstance(value, list):
        return _estimate_compact_pure_change_container_lines(node.children, settings, is_array=True)
    raise TypeError(f"Unsupported pure-change value: {type(value)!r}")


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


def _emit_string_detail(
    detail: StringDetail,
    indent: int,
    field_key: str | None,
    root: bool,
    review_mode: ReviewMode,
    settings: DiffSettings,
) -> list[LayoutLine]:
    label_prefix = _label_prefix(field_key, root=root)
    label_span = LayoutSpan(role="modified_label", text=label_prefix)

    if detail.mode is StringMode.INLINE_TOKEN:
        return [
            _span_line(
                indent,
                LayoutLineKind.VALUE,
                "~",
                [label_span, *_quote_string_spans(detail.inline_spans)],
            )
        ]

    if detail.mode is StringMode.MULTILINE_BLOCK:
        lines = [
            _span_line(
                indent,
                LayoutLineKind.MODIFIED_HEADER,
                "~",
                [label_span, LayoutSpan(role="plain", text=_multiline_header_text(detail))],
            )
        ]
        context_budget = _multiline_context_budget(review_mode, settings)
        for hunk_index, hunk in enumerate(detail.multiline_hunks):
            lines.extend(_render_multiline_gap(hunk.prefix_context, indent + 1, context_budget, from_end=True))
            lines.extend(_render_multiline_body(hunk.body, indent + 1))
            if hunk_index == len(detail.multiline_hunks) - 1:
                lines.extend(_render_multiline_gap(hunk.suffix_context, indent + 1, context_budget, from_end=False))
        return lines

    assert detail.summary is not None
    lines = [
        _span_line(
            indent,
            LayoutLineKind.MODIFIED_HEADER,
            "~",
            [
                label_span,
                LayoutSpan(
                    role="plain",
                    text=(
                        f"string changed ({detail.summary.old_len} -> "
                        f"{detail.summary.new_len} chars, {detail.summary.hunk_count} hunks)"
                    ),
                ),
            ],
        )
    ]
    excerpt_columns = _blob_excerpt_columns(review_mode, settings)
    hunk_limit = _blob_hunk_limit(review_mode, settings)
    display_hunks = detail.blob_hunks if hunk_limit is None else detail.blob_hunks[:hunk_limit]
    for index, hunk in enumerate(display_hunks):
        if hunk.omitted_before_chars > 0:
            label = "prefix" if index == 0 else "text"
            lines.append(
                _summary_line(
                    indent + 1,
                    "",
                    f"… {hunk.omitted_before_chars} chars of unchanged {label} omitted …",
                )
            )
        lines.append(
            _span_line(
                indent + 1,
                LayoutLineKind.VALUE,
                "-",
                _quote_string_spans(_trim_blob_spans(hunk.old_spans, excerpt_columns)),
            )
        )
        lines.append(
            _span_line(
                indent + 1,
                LayoutLineKind.VALUE,
                "+",
                _quote_string_spans(_trim_blob_spans(hunk.new_spans, excerpt_columns)),
            )
        )

    if hunk_limit is not None and len(detail.blob_hunks) > len(display_hunks):
        lines.append(
            _summary_line(
                indent + 1,
                "",
                f"… {len(detail.blob_hunks) - len(display_hunks)} more hunks omitted …",
            )
        )
    elif display_hunks and display_hunks[-1].omitted_after_chars > 0:
        lines.append(
            _summary_line(
                indent + 1,
                "",
                f"… {display_hunks[-1].omitted_after_chars} chars of unchanged suffix omitted …",
            )
        )
    return lines


def _multiline_header_text(detail: StringDetail) -> str:
    if detail.old_line_count == detail.new_line_count:
        header = f"<<{detail.old_line_count} lines"
    else:
        header = f"<<{detail.old_line_count} -> {detail.new_line_count} lines"
    if detail.trailing_newline_changed:
        header += ", trailing newline changed"
    return header + ">>"


def _multiline_context_budget(review_mode: ReviewMode, settings: DiffSettings) -> int | None:
    if review_mode is ReviewMode.COMPACT:
        return settings.string_multiline_context_compact
    if review_mode is ReviewMode.FOCUS:
        return settings.string_multiline_context_focus
    return None


def _render_multiline_gap(
    lines: list[StringLine],
    indent: int,
    context_budget: int | None,
    *,
    from_end: bool,
) -> list[LayoutLine]:
    if not lines:
        return []
    if context_budget is None or len(lines) <= max(context_budget, context_budget * 2):
        selected = lines
        omitted = 0
    elif from_end:
        selected = lines[-context_budget:]
        omitted = len(lines) - context_budget
    else:
        selected = lines[:context_budget]
        omitted = len(lines) - context_budget

    rendered: list[LayoutLine] = []
    if omitted:
        rendered.append(_summary_line(indent, "", f"… {omitted} unchanged lines omitted …"))
    rendered.extend(_render_multiline_body(selected, indent))
    return rendered


def _render_multiline_body(lines: list[StringLine], indent: int) -> list[LayoutLine]:
    rendered: list[LayoutLine] = []
    for line in lines:
        if line.kind == "summary":
            rendered.append(_summary_line(indent, "", line.text))
            continue
        marker = ""
        if line.kind == "removed":
            marker = "-"
        elif line.kind == "added":
            marker = "+"
        rendered.append(_span_line(indent, LayoutLineKind.VALUE, marker, _quote_string_spans(line.spans)))
    return rendered


def _blob_excerpt_columns(review_mode: ReviewMode, settings: DiffSettings) -> int | None:
    if review_mode is ReviewMode.COMPACT:
        return settings.string_blob_excerpt_columns_compact
    if review_mode is ReviewMode.FOCUS:
        return settings.string_blob_excerpt_columns_focus
    return settings.string_blob_excerpt_columns_full


def _blob_hunk_limit(review_mode: ReviewMode, settings: DiffSettings) -> int | None:
    if review_mode is ReviewMode.COMPACT:
        return settings.string_blob_hunk_limit_compact
    if review_mode is ReviewMode.FOCUS:
        return settings.string_blob_hunk_limit_focus
    return settings.string_blob_hunk_limit_full


def _trim_blob_spans(spans: list[StringSpan], budget: int | None) -> list[StringSpan]:
    if budget is None:
        return spans
    if _string_span_width(spans) <= budget:
        return spans

    changed_indexes = [index for index, span in enumerate(spans) if span.role != "plain"]
    if not changed_indexes:
        text = "".join(span.text for span in spans)
        return [StringSpan(role="plain", text=_take_left_columns(text, budget))]

    first_changed = changed_indexes[0]
    last_changed = changed_indexes[-1]
    middle = spans[first_changed:last_changed + 1]
    middle_width = _string_span_width(middle)
    if middle_width >= budget:
        return _merge_string_spans(_take_center_excerpt(middle, budget))

    remaining = max(budget - middle_width, 0)
    left_budget = remaining // 2
    right_budget = remaining - left_budget

    trimmed: list[StringSpan] = []
    left_text = _take_right_columns(
        "".join(span.text for span in spans[:first_changed] if span.role == "plain"),
        left_budget,
    )
    if left_text:
        trimmed.append(StringSpan(role="plain", text=left_text))
    trimmed.extend(middle)
    right_text = _take_left_columns(
        "".join(span.text for span in spans[last_changed + 1:] if span.role == "plain"),
        right_budget,
    )
    if right_text:
        trimmed.append(StringSpan(role="plain", text=right_text))
    return _merge_string_spans(trimmed)


def _quote_string_spans(spans: list[StringSpan]) -> list[LayoutSpan]:
    rendered = [LayoutSpan(role="plain", text="\"")]
    for span in spans:
        escaped = json_string_fragment(span.text)
        if span.role == "plain":
            rendered.append(LayoutSpan(role="plain", text=escaped))
        elif span.role == "removed":
            rendered.append(LayoutSpan(role="removed", text=f"[-{escaped}-]"))
        else:
            rendered.append(LayoutSpan(role="added", text=f"[+{escaped}+]"))
    rendered.append(LayoutSpan(role="plain", text="\""))
    return rendered


def _string_span_width(spans: list[StringSpan]) -> int:
    return sum(_display_width(span.text) for span in spans)


def _merge_string_spans(spans: list[StringSpan]) -> list[StringSpan]:
    merged: list[StringSpan] = []
    for span in spans:
        if not span.text:
            continue
        if merged and merged[-1].role == span.role:
            previous = merged[-1]
            merged[-1] = StringSpan(role=span.role, text=previous.text + span.text)
            continue
        merged.append(span)
    return merged


def _display_width(text: str) -> int:
    width = wcswidth(text)
    return width if width >= 0 else len(split_graphemes(text))


def _take_left_columns(text: str, max_columns: int | None) -> str:
    if max_columns is None:
        return text
    if max_columns <= 0 or not text:
        return ""

    graphemes = split_graphemes(text)
    result = ""
    used = 0
    for grapheme in graphemes:
        char_width = _display_width(grapheme)
        if result and used + char_width > max_columns:
            break
        result += grapheme
        used += char_width
        if used >= max_columns:
            break
    return result


def _take_right_columns(text: str, max_columns: int | None) -> str:
    if max_columns is None:
        return text
    if max_columns <= 0 or not text:
        return ""

    graphemes = split_graphemes(text)
    reversed_result = ""
    used = 0
    for grapheme in reversed(graphemes):
        char_width = _display_width(grapheme)
        if reversed_result and used + char_width > max_columns:
            break
        reversed_result += grapheme
        used += char_width
        if used >= max_columns:
            break
    return "".join(reversed(reversed_result))


def _take_center_excerpt(spans: list[StringSpan], budget: int) -> list[StringSpan]:
    if budget <= 0:
        return []
    if _string_span_width(spans) <= budget:
        return spans
    if budget == 1:
        return [StringSpan(role="plain", text="…")]

    inner_budget = budget - 1
    left_budget = inner_budget // 2
    right_budget = inner_budget - left_budget
    return [
        *_take_span_prefix(spans, left_budget),
        StringSpan(role="plain", text="…"),
        *_take_span_suffix(spans, right_budget),
    ]


def _take_span_prefix(spans: list[StringSpan], budget: int) -> list[StringSpan]:
    if budget <= 0:
        return []
    remaining = budget
    excerpt: list[StringSpan] = []
    for span in spans:
        if remaining <= 0:
            break
        text = _take_left_columns(span.text, remaining)
        if text:
            excerpt.append(StringSpan(role=span.role, text=text))
            remaining -= _display_width(text)
    return excerpt


def _take_span_suffix(spans: list[StringSpan], budget: int) -> list[StringSpan]:
    if budget <= 0:
        return []
    remaining = budget
    excerpt: list[StringSpan] = []
    for span in reversed(spans):
        if remaining <= 0:
            break
        text = _take_right_columns(span.text, remaining)
        if text:
            excerpt.append(StringSpan(role=span.role, text=text))
            remaining -= _display_width(text)
    excerpt.reverse()
    return excerpt


def _line(
    indent: int,
    kind: LayoutLineKind,
    marker: str,
    text: str,
    spans: list[LayoutSpan] | None = None,
) -> LayoutLine:
    return LayoutLine(indent=indent, kind=kind, marker=marker, text=text, spans=spans or [])


def _span_line(indent: int, kind: LayoutLineKind, marker: str, spans: list[LayoutSpan]) -> LayoutLine:
    return _line(indent, kind, marker, "", spans=spans)


def _value_line(indent: int, marker: str, text: str) -> LayoutLine:
    return _line(indent, LayoutLineKind.VALUE, marker, text)


def _summary_line(indent: int, marker: str, text: str) -> LayoutLine:
    return _line(indent, LayoutLineKind.SUMMARY, marker, text)


def _note_line(indent: int, text: str) -> LayoutLine:
    return _line(indent, LayoutLineKind.NOTE, ">", text)
