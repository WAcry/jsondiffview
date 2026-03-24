from __future__ import annotations

import sys

import typer

from .diff import diff_json
from .io import InputUsageError, JdvError, read_json_source
from .layout import build_display_layout
from .model import ColorMode, DiffSettings, ReviewMode
from .render import render_review_view


def main(
    old_json: str = typer.Argument(...),
    new_json: str = typer.Argument(...),
    match_key: list[str] | None = typer.Option(None, "--match-key"),
    color: str = typer.Option("auto", "--color"),
    view: str = typer.Option("compact", "--view"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    try:
        color_mode = _parse_color_mode(color)
        review_mode = _parse_review_mode(view)
        settings = _build_settings(match_key)
        stdin_text = _read_stdin_once(old_json, new_json)

        old_value = read_json_source(
            old_json,
            stdin_text if old_json == "-" else None,
            "old",
        )
        new_value = read_json_source(
            new_json,
            stdin_text if new_json == "-" else None,
            "new",
        )

        root = diff_json(old_value, new_value, settings)
        plan = build_display_layout(root, review_mode, settings)
        if not plan.has_changes:
            if not quiet and sys.stderr.isatty():
                typer.echo("No semantic differences.", err=True)
            raise typer.Exit(0)

        rendered = render_review_view(plan, color_mode)
        if rendered:
            sys.stdout.write(rendered)
            if not rendered.endswith("\n"):
                sys.stdout.write("\n")
    except JdvError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


def entrypoint() -> None:
    typer.run(main)


def _parse_color_mode(value: str) -> ColorMode:
    try:
        return ColorMode(value)
    except ValueError as exc:
        raise InputUsageError(
            f"Invalid --color value {value!r}. Expected one of: auto, always, never."
        ) from exc


def _parse_review_mode(value: str) -> ReviewMode:
    try:
        return ReviewMode(value)
    except ValueError as exc:
        raise InputUsageError(
            f"Invalid --view value {value!r}. Expected one of: compact, focus, full."
        ) from exc


def _build_settings(match_key: list[str] | None) -> DiffSettings:
    if not match_key:
        return DiffSettings()

    normalized: list[str] = []
    for raw_value in match_key:
        value = raw_value.strip()
        if not value:
            raise InputUsageError("--match-key must not be empty")
        normalized.append(value)

    return DiffSettings(match_keys=tuple(normalized))


def _read_stdin_once(old_json: str, new_json: str) -> bytes | None:
    if old_json == "-" and new_json == "-":
        raise InputUsageError("Only one input may be read from stdin at a time")
    if old_json == "-" or new_json == "-":
        return sys.stdin.buffer.read()
    return None
