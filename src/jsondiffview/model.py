"""Typed values shared by the parser, diff engine, and renderer."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TypeAlias

DIAGNOSTIC_TEXT_LIMIT = 80
DIAGNOSTIC_MESSAGE_LIMIT = 512


class JsonDiffError(Exception):
    """Base class for expected user-facing failures."""


class InputError(JsonDiffError):
    """An input could not be read or decoded."""


class OutputError(JsonDiffError):
    """Review output could not be written."""


class JsonNumberKind(StrEnum):
    """The two intentionally distinct JSON number categories."""

    INTEGER = "integer"
    DECIMAL = "decimal"


@dataclass(frozen=True, slots=True)
class JsonNumber:
    """A strict JSON number with its category and source spelling retained."""

    kind: JsonNumberKind
    value: int | Decimal
    lexeme: str


JsonScalar: TypeAlias = None | bool | str | JsonNumber
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonPathPart: TypeAlias = str | int
JsonPath: TypeAlias = tuple[JsonPathPart, ...]


class DiffStatus(StrEnum):
    """The semantic relationship between one old and new value."""

    UNCHANGED = "unchanged"
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"


class MatchKind(StrEnum):
    """Trusted evidence strong enough to explain an array move."""

    IDENTITY = "identity"
    EXACT = "exact"


class AlignmentBasis(StrEnum):
    """The independent reason two array entries are visually aligned."""

    IDENTITY = "identity"
    UNIQUE_EXACT = "unique_exact"
    DUPLICATE_EXACT_SEQUENCE = "duplicate_exact_sequence"


@dataclass(frozen=True, slots=True)
class MatchEvidence:
    """High-confidence same-item and move evidence for one array match."""

    kind: MatchKind
    key: str | None = None
    key_value: JsonValue | None = None


@dataclass(frozen=True, slots=True)
class ObjectMember:
    """One object member in deterministic presentation order."""

    key: str
    node: DiffNode


@dataclass(frozen=True, slots=True)
class ArrayEntry:
    """One array entry, including pairing and move provenance."""

    node: DiffNode
    old_index: int | None
    new_index: int | None
    alignment_basis: AlignmentBasis | None = None
    evidence: MatchEvidence | None = None
    moved: bool = False


@dataclass(frozen=True, slots=True)
class DiffNode:
    """A renderer-independent semantic diff node."""

    status: DiffStatus
    old: JsonValue | None
    new: JsonValue | None
    old_path: JsonPath | None
    new_path: JsonPath | None
    object_members: tuple[ObjectMember, ...] = ()
    array_entries: tuple[ArrayEntry, ...] = ()


class StyleRole(StrEnum):
    """Semantic terminal color roles."""

    DEFAULT = "default"
    MODIFIED = "modified"
    REMOVED = "removed"
    ADDED = "added"
    PROVENANCE = "provenance"


@dataclass(frozen=True, slots=True)
class StyledSpan:
    """One immutable fragment of review text and its semantic role."""

    text: str
    role: StyleRole = StyleRole.DEFAULT


class View(StrEnum):
    """Supported projection detail levels."""

    SUMMARY = "summary"
    REVIEW = "review"
    FULL = "full"


class ColorMode(StrEnum):
    """Supported review color policies."""

    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


def bounded_text_repr(text: str) -> str:
    """Return a bounded repr suitable for a single-line diagnostic."""

    if len(text) <= DIAGNOSTIC_TEXT_LIMIT:
        return repr(text)
    left = DIAGNOSTIC_TEXT_LIMIT // 2
    right = DIAGNOSTIC_TEXT_LIMIT - left
    excerpt = text[:left] + "…" + text[-right:]
    omitted = len(text) - DIAGNOSTIC_TEXT_LIMIT
    return f"{excerpt!r} ({omitted} code points omitted)"


def bounded_diagnostic_text(text: str) -> str:
    """Bound and escape a user-facing diagnostic message."""

    if len(text) > DIAGNOSTIC_MESSAGE_LIMIT:
        left = DIAGNOSTIC_MESSAGE_LIMIT // 2
        right = DIAGNOSTIC_MESSAGE_LIMIT - left
        omitted = len(text) - DIAGNOSTIC_MESSAGE_LIMIT
        text = text[:left] + f"… {omitted} code points omitted …" + text[-right:]

    parts: list[str] = []
    for character in text:
        code_point = ord(character)
        if (
            code_point < 0x20
            or 0x7F <= code_point <= 0x9F
            or code_point in {0x2028, 0x2029}
            or 0xD800 <= code_point <= 0xDFFF
        ):
            parts.append(f"\\u{code_point:04x}")
        else:
            parts.append(character)
    return "".join(parts)


def json_kind(value: JsonValue) -> str:
    """Return the stable user-facing kind of a strict JSON value."""

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, JsonNumber):
        return value.kind.value
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"
