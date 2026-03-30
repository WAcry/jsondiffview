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


class StringMode(Enum):
    INLINE_TOKEN = "inline_token"
    MULTILINE_BLOCK = "multiline_block"
    BLOB_SUMMARY = "blob_summary"


class StringTokenKind(Enum):
    IDENT = "ident"
    NUMBER = "number"
    SPACE = "space"
    PUNCT = "punct"
    OTHER = "other"


@dataclass(frozen=True)
class DiffSettings:
    match_keys: tuple[str, ...] = ("id", "key", "name", "title")
    compact_preview_keys: int = 2
    compact_preview_items: int = 2
    compact_summary_min_lines: int = 8
    string_blob_min_chars: int = 512
    string_blob_dense_line_chars: int = 160
    string_blob_opaque_token_chars: int = 96
    string_multiline_context_compact: int = 1
    string_multiline_context_focus: int = 2
    string_multiline_pair_min_ratio: float = 0.35
    string_blob_excerpt_columns_compact: int = 32
    string_blob_excerpt_columns_focus: int = 64
    string_blob_excerpt_columns_full: int = 120
    string_blob_hunk_limit_compact: int = 3
    string_blob_hunk_limit_focus: int = 6
    string_blob_hunk_limit_full: int | None = None
    string_blob_merge_gap_columns: int = 8
    string_microdiff_min_shared_affix: int = 3
    string_microdiff_max_token_graphemes: int = 64


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


@dataclass(frozen=True)
class StringToken:
    kind: StringTokenKind
    text: str


@dataclass(frozen=True)
class StringSpan:
    role: Literal["plain", "removed", "added"]
    text: str


@dataclass(frozen=True)
class StringLine:
    kind: Literal["context", "removed", "added", "summary"]
    spans: list[StringSpan] = field(default_factory=list)
    text: str = ""
    old_line_no: int | None = None
    new_line_no: int | None = None


@dataclass(frozen=True)
class StringMultilineHunk:
    prefix_context: list[StringLine] = field(default_factory=list)
    body: list[StringLine] = field(default_factory=list)
    suffix_context: list[StringLine] = field(default_factory=list)


@dataclass(frozen=True)
class StringBlobHunk:
    old_spans: list[StringSpan] = field(default_factory=list)
    new_spans: list[StringSpan] = field(default_factory=list)
    omitted_before_chars: int = 0
    omitted_after_chars: int = 0


@dataclass(frozen=True)
class StringSummary:
    old_len: int
    new_len: int
    hunk_count: int


@dataclass
class StringDetail:
    mode: StringMode
    old_text: str
    new_text: str
    inline_spans: list[StringSpan] = field(default_factory=list)
    multiline_hunks: list[StringMultilineHunk] = field(default_factory=list)
    blob_hunks: list[StringBlobHunk] = field(default_factory=list)
    summary: StringSummary | None = None
    old_line_count: int = 1
    new_line_count: int = 1
    trailing_newline_changed: bool = False


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
class LayoutSpan:
    role: Literal["plain", "marker", "modified_label", "removed", "added", "note"]
    text: str


@dataclass(frozen=True)
class LayoutLine:
    indent: int
    kind: LayoutLineKind
    marker: Literal["", "+", "-", "~", ">"]
    text: str
    trailing_comma: bool = False
    spans: list[LayoutSpan] = field(default_factory=list)


@dataclass(frozen=True)
class LayoutPlan:
    review_mode: ReviewMode
    has_changes: bool
    lines: list[LayoutLine]
