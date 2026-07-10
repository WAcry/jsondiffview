"""Click command boundary, byte I/O, streams, and process statuses."""

from __future__ import annotations

import errno
import os
import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO, Protocol, cast

import click

from . import __version__
from .color import serialize_ansi, serialize_plain
from .diff import DEFAULT_MATCH_KEYS, build_diff
from .model import (
    ColorMode,
    InputError,
    JsonDiffError,
    OutputError,
    View,
    bounded_diagnostic_text,
    bounded_text_repr,
)
from .parser import decode_json_bytes, strict_equal
from .render import render_diff


class _TerminalStream(Protocol):
    def isatty(self) -> bool:
        """Return whether the stream is attached to a terminal."""


class _BrokenOutput(Exception):
    """The downstream stdout consumer closed the pipe."""


def _help_option_callback(
    context: click.Context,
    _parameter: click.Parameter,
    value: bool,
) -> None:
    if not value or context.resilient_parsing:
        return
    _write_control_stdout(context.get_help().rstrip("\n") + "\n")
    context.exit()


def _version_option_callback(
    context: click.Context,
    _parameter: click.Parameter,
    value: bool,
) -> None:
    if not value or context.resilient_parsing:
        return
    _write_control_stdout(f"jdv {__version__}\n")
    context.exit()


@click.command(
    name="jdv",
    add_help_option=False,
)
@click.argument("old_json", metavar="OLD_JSON")
@click.argument("new_json", metavar="NEW_JSON")
@click.option(
    "-v",
    "--view",
    type=click.Choice([view.value for view in View], case_sensitive=True),
    default=View.REVIEW.value,
    show_default=True,
    help="Detail level.",
)
@click.option(
    "-k",
    "--match-key",
    metavar="FIELD",
    multiple=True,
    help=(
        "Array-object identity key; repeat in priority order. "
        "Any occurrence replaces defaults: id, key, name, title."
    ),
)
@click.option(
    "-c",
    "--color",
    type=click.Choice([mode.value for mode in ColorMode], case_sensitive=True),
    default=ColorMode.AUTO.value,
    show_default=True,
    help="Review color policy.",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Suppress the equality notice only.",
)
@click.option(
    "--version",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_version_option_callback,
    help="Show the version and exit.",
)
@click.option(
    "-h",
    "--help",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_help_option_callback,
    help="Show this message and exit.",
)
@click.pass_context
def command(
    context: click.Context,
    old_json: str,
    new_json: str,
    view: str,
    match_key: tuple[str, ...],
    color: str,
    quiet: bool,
) -> None:
    """Compare strict OLD_JSON (before) with NEW_JSON (after)."""

    if old_json == new_json == "-":
        raise click.UsageError("OLD_JSON and NEW_JSON cannot both use stdin.")
    duplicate = _first_duplicate(match_key)
    if duplicate is not None:
        raise click.UsageError(
            f"duplicate --match-key value {bounded_text_repr(duplicate)}."
        )
    match_keys = match_key or DEFAULT_MATCH_KEYS

    old_bytes = _read_input(old_json)
    new_bytes = _read_input(new_json)
    old = decode_json_bytes(old_bytes, _source_name(old_json))
    new = decode_json_bytes(new_bytes, _source_name(new_json))

    if strict_equal(old, new):
        if not quiet:
            _write_stderr(
                "No semantic differences.\n",
                failure_message="unable to write the equality notice.",
            )
        return

    tree = build_diff(old, new, match_keys)
    spans = render_diff(tree, View(view))
    use_color = color_enabled(ColorMode(color), sys.stdout, os.environ)
    review = serialize_ansi(spans) if use_color else serialize_plain(spans)
    try:
        _write_review(review)
    except _BrokenOutput:
        _pacify_stdout()
        context.exit(2)
    context.exit(1)


def main(args: Sequence[str] | None = None) -> int:
    """Run the command with stable expected-error translation."""

    try:
        result = command.main(
            args=None if args is None else list(args),
            prog_name="jdv",
            standalone_mode=False,
            windows_expand_args=False,
        )
    except click.ClickException as error:
        _write_diagnostic(error.format_message())
        return 2
    except click.Abort:
        _write_diagnostic("operation aborted.")
        return 2
    except _BrokenOutput:
        _pacify_stdout()
        return 2
    except JsonDiffError as error:
        _write_diagnostic(str(error))
        return 2
    return int(result or 0)


def color_enabled(
    mode: ColorMode,
    stdout: _TerminalStream,
    environment: Mapping[str, str],
) -> bool:
    """Resolve the explicit color policy without implicit framework behavior."""

    if mode is ColorMode.ALWAYS:
        return True
    if mode is ColorMode.NEVER:
        return False
    try:
        is_terminal = stdout.isatty()
    except ValueError as error:
        raise _BrokenOutput from error
    except OSError as error:
        raise OutputError("unable to inspect review output.") from error
    return is_terminal and not bool(environment.get("NO_COLOR"))


def _first_duplicate(values: tuple[str, ...]) -> str | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None


def _source_name(path: str) -> str:
    return "stdin" if path == "-" else bounded_text_repr(path)


def _read_input(path: str) -> bytes:
    if path == "-":
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        try:
            data = stream.read()
        except (OSError, ValueError) as error:
            raise InputError("stdin: unable to read input.") from error
        if not isinstance(data, str):
            return cast(bytes, data)
        try:
            return data.encode("utf-8")
        except UnicodeEncodeError as error:
            raise InputError("stdin: input is not valid UTF-8 text.") from error

    source = _source_name(path)
    try:
        return Path(path).read_bytes()
    except FileNotFoundError as error:
        raise InputError(f"{source}: input file was not found.") from error
    except IsADirectoryError as error:
        raise InputError(
            f"{source}: expected an input file, found a directory."
        ) from error
    except PermissionError as error:
        raise InputError(f"{source}: permission denied while reading input.") from error
    except OSError as error:
        raise InputError(f"{source}: unable to read input file.") from error


def _write_review(text: str) -> None:
    stream = sys.stdout
    try:
        if not stream.isatty() and hasattr(stream, "buffer"):
            binary = cast(BinaryIO, stream.buffer)
            data = text.encode("utf-8")
            if binary.write(data) != len(data):
                raise OSError(errno.EIO, "short stdout write")
            binary.flush()
        else:
            click.echo(text, file=stream, nl=False, color=True)
            stream.flush()
    except (OSError, ValueError) as error:
        if isinstance(error, ValueError) or _is_broken_pipe(error):
            raise _BrokenOutput from error
        raise OutputError("unable to write review output.") from error


def _write_control_stdout(text: str) -> None:
    stream = sys.stdout
    try:
        if hasattr(stream, "buffer"):
            binary = cast(BinaryIO, stream.buffer)
            data = text.encode("utf-8")
            if binary.write(data) != len(data):
                raise OSError(errno.EIO, "short stdout write")
            binary.flush()
        else:
            if stream.write(text) != len(text):
                raise OSError(errno.EIO, "short stdout write")
            stream.flush()
    except (OSError, ValueError) as error:
        if isinstance(error, ValueError) or _is_broken_pipe(error):
            raise _BrokenOutput from error
        raise OutputError("unable to write command output.") from error


def _is_broken_pipe(error: OSError) -> bool:
    winerror = getattr(error, "winerror", None)
    # CPython can lose the native pipe code and expose EINVAL for this case.
    windows_pipe_without_winerror = (
        os.name == "nt" and error.errno == errno.EINVAL and winerror is None
    )
    return (
        isinstance(error, BrokenPipeError)
        or error.errno == errno.EPIPE
        or winerror in {109, 232}
        or windows_pipe_without_winerror
    )


def _pacify_stdout() -> None:
    stream = sys.stdout
    with suppress(OSError, ValueError):
        stream.close()
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def _write_diagnostic(message: str) -> None:
    _write_stderr(f"jdv: error: {bounded_diagnostic_text(message)}\n")


def _write_stderr(text: str, *, failure_message: str | None = None) -> None:
    stream = sys.stderr
    try:
        if hasattr(stream, "buffer") and not stream.isatty():
            binary = cast(BinaryIO, stream.buffer)
            data = text.encode("utf-8")
            if binary.write(data) != len(data):
                raise OSError(errno.EIO, "short stderr write")
            binary.flush()
        else:
            click.echo(text, file=stream, nl=False, color=False)
            stream.flush()
    except (OSError, ValueError) as error:
        if failure_message is not None:
            raise OutputError(failure_message) from error
