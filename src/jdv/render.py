from __future__ import annotations

import sys

from .model import ColorMode, LayoutPlan


def render_review_view(plan: LayoutPlan, color_mode: ColorMode) -> str:
    color_enabled = color_mode == ColorMode.ALWAYS or (
        color_mode == ColorMode.AUTO and sys.stdout.isatty()
    )

    rendered_lines: list[str] = []
    for line in plan.lines:
        prefix = f"{line.marker} " if line.marker else ""
        suffix = "," if line.trailing_comma else ""
        text = f"{'  ' * line.indent}{prefix}{line.text}{suffix}"
        if color_enabled:
            text = _apply_color(text, line.marker)
        rendered_lines.append(text)
    return "\n".join(rendered_lines)


def _apply_color(text: str, marker: str) -> str:
    palette = {
        "+": "\x1b[32m",
        "-": "\x1b[31m",
        "~": "\x1b[33m",
        ">": "\x1b[36m",
    }
    color = palette.get(marker)
    if color is None:
        return text
    return f"{color}{text}\x1b[0m"
