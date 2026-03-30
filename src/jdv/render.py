from __future__ import annotations

import sys

from .model import ColorMode, LayoutPlan, LayoutSpan


_MARKER_COLORS = {
    "+": "\x1b[32m",
    "-": "\x1b[31m",
    "~": "\x1b[33m",
    ">": "\x1b[36m",
}

_SPAN_COLORS = {
    "marker": "\x1b[33m",
    "modified_label": "\x1b[33m",
    "removed": "\x1b[31m",
    "added": "\x1b[32m",
    "note": "\x1b[36m",
}


def render_review_view(plan: LayoutPlan, color_mode: ColorMode) -> str:
    color_enabled = color_mode == ColorMode.ALWAYS or (
        color_mode == ColorMode.AUTO and sys.stdout.isatty()
    )

    rendered_lines: list[str] = []
    for line in plan.lines:
        if line.spans:
            rendered_lines.append(_render_span_line(line.indent, line.marker, line.spans, line.trailing_comma, color_enabled))
            continue

        prefix = f"{line.marker} " if line.marker else ""
        text = f"{'  ' * line.indent}{prefix}{line.text}"
        if color_enabled:
            text = _apply_marker_color(text, line.marker)
        if line.trailing_comma:
            text += ","
        rendered_lines.append(text)
    return "\n".join(rendered_lines)


def _render_span_line(
    indent: int,
    marker: str,
    spans: list[LayoutSpan],
    trailing_comma: bool,
    color_enabled: bool,
) -> str:
    pieces = ["  " * indent]
    if marker:
        pieces.append(_color_text(f"{marker} ", _MARKER_COLORS.get(marker), color_enabled))
    for span in spans:
        pieces.append(_render_span(span, color_enabled))
    if trailing_comma:
        pieces.append(",")
    return "".join(pieces)


def _render_span(span: LayoutSpan, color_enabled: bool) -> str:
    return _color_text(span.text, _SPAN_COLORS.get(span.role), color_enabled)


def _apply_marker_color(text: str, marker: str) -> str:
    return _color_text(text, _MARKER_COLORS.get(marker), True)


def _color_text(text: str, color: str | None, color_enabled: bool) -> str:
    if not color_enabled or color is None:
        return text
    return f"{color}{text}\x1b[0m"
