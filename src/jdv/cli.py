from __future__ import annotations

import sys

import typer
from typer.models import OptionInfo

from . import __version__
from .diff import diff_json
from .io import InputUsageError, JdvError, read_json_source
from .layout import build_display_layout
from .model import ColorMode, DiffSettings, ReviewMode
from .render import render_review_view


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"jdv {__version__}")
        raise typer.Exit()


def main(
    old_json: str = typer.Argument(
        ...,
        metavar="OLD_JSON",
        help="Path to the old JSON document. Use '-' to read this side from stdin.",
    ),
    new_json: str = typer.Argument(
        ...,
        metavar="NEW_JSON",
        help="Path to the new JSON document. Use '-' to read this side from stdin.",
    ),
    match_key: list[str] | None = typer.Option(
        None,
        "--match-key",
        "-k",
        metavar="FIELD",
        help=(
            "Array object identity key. Repeat to replace the default keys: "
            "id, key, name, title."
        ),
    ),
    color: ColorMode = typer.Option(
        ColorMode.AUTO,
        "--color",
        "-c",
        case_sensitive=False,
        help="Color mode for rendered diff output.",
    ),
    view: ReviewMode = typer.Option(
        ReviewMode.COMPACT,
        "--view",
        "-v",
        case_sensitive=False,
        help="compact shows a compressed diff, focus shows the full changed content, full shows the full JSON context.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress the TTY-only 'No semantic differences.' notice for zero-diff results.",
    ),
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the installed version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Compare two JSON documents and render a review-oriented diff.

    Examples:

      jdv before.json after.json
      jdv --view focus --match-key sku --match-key variant_id before.json after.json
      cat after.json | jdv --view full --color never before.json -

    Notes:

      - Only one side may use '-' to read from stdin.
      - Zero-diff results exit 0 and print nothing to stdout.
      - Default array identity keys: id, key, name, title.
    """
    try:
        match_key = _normalize_option_default(match_key, None)
        color = _normalize_option_default(color, ColorMode.AUTO)
        view = _normalize_option_default(view, ReviewMode.COMPACT)
        quiet = _normalize_option_default(quiet, False)

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


def _parse_color_mode(value: ColorMode | str) -> ColorMode:
    if isinstance(value, ColorMode):
        return value
    try:
        return ColorMode(value)
    except ValueError as exc:
        raise InputUsageError(
            f"Invalid --color value {value!r}. Expected one of: auto, always, never."
        ) from exc


def _parse_review_mode(value: ReviewMode | str) -> ReviewMode:
    if isinstance(value, ReviewMode):
        return value
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


def _normalize_option_default(value, default):
    if isinstance(value, OptionInfo):
        return default
    return value
