from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class DiffStatus(Enum):
    UNCHANGED = "unchanged"
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"


class SameItemBasis(Enum):
    NONE = "none"
    IDENTITY_KEY = "identity_key"
    EXACT_VALUE = "exact_value"


class AlignmentBasis(Enum):
    NONE = "none"
    IDENTITY_PASS = "identity_pass"
    EXACT_SEQUENCE = "exact_sequence"
    EXACT_UNIQUE = "exact_unique"


class MoveBasis(Enum):
    NONE = "none"
    IDENTITY_KEY = "identity_key"
    EXACT_VALUE = "exact_value"


class ColorMode(Enum):
    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


class ReviewMode(Enum):
    COMPACT = "compact"
    FOCUS = "focus"
    FULL = "full"


class LayoutLineKind(Enum):
    OPEN = "open"
    CLOSE = "close"
    VALUE = "value"
    NOTE = "note"
    SUMMARY = "summary"
    MODIFIED_HEADER = "modified_header"


@dataclass(frozen=True)
class DiffSettings:
    match_keys: tuple[str, ...] = ("id", "key", "name", "title")
    inline_string_limit: int = 120
    compact_preview_keys: int = 2
    compact_preview_items: int = 2
    compact_summary_min_lines: int = 8


@dataclass(frozen=True)
class IdentityLabel:
    field_name: str
    value_text: str


@dataclass(frozen=True)
class MoveDetail:
    old_path: tuple[str | int, ...]
    new_path: tuple[str | int, ...]
    basis: MoveBasis
    identity_label: IdentityLabel | None = None


@dataclass
class StringChunk:
    role: Literal["same", "removed", "added"]
    text: str


@dataclass
class StringDetail:
    mode: Literal["inline", "block"]
    old_text: str
    new_text: str
    chunks: list[StringChunk] = field(default_factory=list)


@dataclass
class DiffNode:
    old_path: tuple[str | int, ...]
    new_path: tuple[str | int, ...]
    status: DiffStatus
    old_value: Any | None
    new_value: Any | None
    children: list["DiffNode"] = field(default_factory=list)
    same_item_basis: SameItemBasis = SameItemBasis.NONE
    alignment_basis: AlignmentBasis = AlignmentBasis.NONE
    identity_label: IdentityLabel | None = None
    move_detail: MoveDetail | None = None
    old_index: int | None = None
    new_index: int | None = None
    string_detail: StringDetail | None = None


@dataclass(frozen=True)
class LayoutLine:
    indent: int
    kind: LayoutLineKind
    marker: Literal["", "+", "-", "~", ">"]
    text: str
    trailing_comma: bool = False
    string_detail: StringDetail | None = None


@dataclass(frozen=True)
class LayoutPlan:
    review_mode: ReviewMode
    has_changes: bool
    lines: list[LayoutLine]
