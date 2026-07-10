"""Strict UTF-8 JSON decoding and semantic value helpers."""

from __future__ import annotations

import json
import math
from decimal import Decimal, InvalidOperation
from typing import TypeAlias, cast

from .model import (
    InputError,
    JsonNumber,
    JsonNumberKind,
    JsonValue,
    bounded_text_repr,
)

INTEGER_DIGIT_LIMIT = 4_300
DECIMAL_LEXEME_LIMIT = 10_000
CONTAINER_DEPTH_LIMIT = 256
_INTEGER_CHUNK_SIZE = 9


class JsonParseError(InputError):
    """A source is not valid under the project's strict JSON policy."""


Fingerprint: TypeAlias = tuple[object, ...]


def decode_json_bytes(data: bytes, source: str) -> JsonValue:
    """Decode UTF-8 bytes and construct a strict typed JSON value."""

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise JsonParseError(
            f"{source}: invalid UTF-8 at byte {error.start}."
        ) from error

    def parse_integer(lexeme: str) -> JsonNumber:
        digits = lexeme.removeprefix("-")
        if len(digits) > INTEGER_DIGIT_LIMIT:
            raise JsonParseError(
                f"{source}: integer exceeds the supported numeric limit."
            )
        value = 0
        for start in range(0, len(digits), _INTEGER_CHUNK_SIZE):
            chunk = digits[start : start + _INTEGER_CHUNK_SIZE]
            value = value * (10 ** len(chunk)) + int(chunk)
        if lexeme.startswith("-"):
            value = -value
        return JsonNumber(JsonNumberKind.INTEGER, value, lexeme)

    def parse_decimal(lexeme: str) -> JsonNumber:
        if len(lexeme) > DECIMAL_LEXEME_LIMIT:
            raise JsonParseError(
                f"{source}: decimal lexeme exceeds the supported numeric limit."
            )
        try:
            decimal_value = Decimal(lexeme)
            binary_value = float(lexeme)
        except (InvalidOperation, OverflowError, ValueError) as error:
            raise JsonParseError(f"{source}: invalid decimal number.") from error
        if not decimal_value.is_finite() or not math.isfinite(binary_value):
            raise JsonParseError(
                f"{source}: decimal number is outside the supported finite range."
            )
        return JsonNumber(JsonNumberKind.DECIMAL, decimal_value, lexeme)

    def reject_constant(token: str) -> JsonValue:
        raise JsonParseError(
            f"{source}: non-finite number {token!r} is not valid JSON."
        )

    def build_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {}
        for key, value in pairs:
            if key in result:
                raise JsonParseError(
                    f"{source}: duplicate object key {bounded_text_repr(key)}."
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            text,
            object_pairs_hook=build_object,
            parse_int=parse_integer,
            parse_float=parse_decimal,
            parse_constant=reject_constant,
        )
    except JsonParseError:
        raise
    except RecursionError as error:
        raise JsonParseError(
            f"{source}: container nesting exceeds the supported limit of "
            f"{CONTAINER_DEPTH_LIMIT}."
        ) from error
    except json.JSONDecodeError as error:
        line, column, message = _normalized_json_error(text, error)
        raise JsonParseError(
            f"{source}: invalid JSON at line {line}, column {column}: {message}."
        ) from error
    typed_value = cast(JsonValue, value)
    _validate_container_depth(typed_value, source)
    return typed_value


def _validate_container_depth(value: JsonValue, source: str) -> None:
    """Reject trees deeper than recursive core stages can safely traverse."""

    if not isinstance(value, (dict, list)):
        return
    stack: list[tuple[JsonValue, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > CONTAINER_DEPTH_LIMIT:
            raise JsonParseError(
                f"{source}: container nesting exceeds the supported limit of "
                f"{CONTAINER_DEPTH_LIMIT}."
            )
        if isinstance(current, dict):
            stack.extend(
                (child, depth + 1)
                for child in current.values()
                if isinstance(child, (dict, list))
            )
        elif isinstance(current, list):
            stack.extend(
                (child, depth + 1)
                for child in current
                if isinstance(child, (dict, list))
            )


def _normalized_json_error(
    text: str,
    error: json.JSONDecodeError,
) -> tuple[int, int, str]:
    """Normalize decoder-version drift for object/array trailing commas."""

    position = error.pos
    if position < len(text) and text[position] == ",":
        closing = position + 1
        while closing < len(text) and text[closing].isspace():
            closing += 1
        if closing < len(text) and text[closing] in "}]":
            return (
                *_line_and_column(text, closing),
                "trailing commas are not valid JSON",
            )
    if position < len(text) and text[position] in "}]":
        comma = position - 1
        while comma >= 0 and text[comma].isspace():
            comma -= 1
        if comma >= 0 and text[comma] == ",":
            return (
                *_line_and_column(text, position),
                "trailing commas are not valid JSON",
            )
    return error.lineno, error.colno, error.msg


def _line_and_column(text: str, position: int) -> tuple[int, int]:
    line = text.count("\n", 0, position) + 1
    line_start = text.rfind("\n", 0, position) + 1
    return line, position - line_start + 1


def strict_equal(left: JsonValue, right: JsonValue) -> bool:
    """Compare JSON values without Python's bool/number coercions."""

    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if isinstance(left, JsonNumber) or isinstance(right, JsonNumber):
        return (
            isinstance(left, JsonNumber)
            and isinstance(right, JsonNumber)
            and left.kind is right.kind
            and left.value == right.value
        )
    if isinstance(left, str) or isinstance(right, str):
        return isinstance(left, str) and isinstance(right, str) and left == right
    if isinstance(left, list) or isinstance(right, list):
        return (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right)
            and all(
                strict_equal(old, new) for old, new in zip(left, right, strict=True)
            )
        )
    if left.keys() != right.keys():
        return False
    return all(strict_equal(left[key], right[key]) for key in left)


def canonical_fingerprint(value: JsonValue) -> Fingerprint:
    """Build a deterministic hashable key that follows strict equality."""

    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, JsonNumber):
        return ("number", value.kind.value, value.value)
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, list):
        return ("array", tuple(canonical_fingerprint(item) for item in value))
    return (
        "object",
        tuple((key, canonical_fingerprint(value[key])) for key in sorted(value)),
    )
