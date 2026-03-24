from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


class JdvError(Exception):
    """Base class for expected CLI errors."""


class InputUsageError(JdvError):
    """Raised when the CLI invocation is invalid."""


class JsonParseError(JdvError):
    """Raised when JSON input cannot be read or parsed safely."""


def read_json_source(path_or_dash: str, stdin_text: str | None, source_role: str) -> Any:
    source_label = _source_label(path_or_dash, source_role)

    if path_or_dash == "-":
        if stdin_text is None:
            raise InputUsageError(f"{source_label}: expected stdin input for '-'")
        text = stdin_text
    else:
        try:
            text = Path(path_or_dash).read_text(encoding="utf-8")
        except OSError as exc:
            reason = exc.strerror or "unable to read file"
            raise JsonParseError(f"{source_label}: {reason}") from exc

    try:
        value = json.loads(
            text,
            object_pairs_hook=_duplicate_key_hook(source_label),
            parse_constant=_non_finite_constant_hook(source_label),
        )
    except JsonParseError:
        raise
    except json.JSONDecodeError as exc:
        raise JsonParseError(
            f"{source_label}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    ensure_finite_numbers(value, source_label)
    return value


def ensure_finite_numbers(value: Any, source_label: str) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise JsonParseError(f"{source_label}: non-finite number is not valid JSON")
        return

    if isinstance(value, list):
        for item in value:
            ensure_finite_numbers(item, source_label)
        return

    if isinstance(value, dict):
        for item in value.values():
            ensure_finite_numbers(item, source_label)


def _source_label(path_or_dash: str, source_role: str) -> str:
    display = "<stdin>" if path_or_dash == "-" else path_or_dash
    return f"{source_role} input ({display})"


def _duplicate_key_hook(source_label: str):
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise JsonParseError(f"{source_label}: duplicate object key {key!r}")
            result[key] = value
        return result

    return reject_duplicate_keys


def _non_finite_constant_hook(source_label: str):
    def reject_constant(token: str) -> Any:
        raise JsonParseError(f"{source_label}: non-finite number {token!r} is not valid JSON")

    return reject_constant
