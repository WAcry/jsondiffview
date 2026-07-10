"""Plain and fixed-role ANSI serialization."""

from __future__ import annotations

from collections.abc import Iterable

from .model import StyledSpan, StyleRole

_ANSI_BY_ROLE = {
    StyleRole.MODIFIED: "\x1b[33m",
    StyleRole.REMOVED: "\x1b[31m",
    StyleRole.ADDED: "\x1b[32m",
    StyleRole.PROVENANCE: "\x1b[36m",
}
_RESET = "\x1b[0m"


def serialize_plain(spans: Iterable[StyledSpan]) -> str:
    """Concatenate authoritative plain review text."""

    return "".join(span.text for span in spans)


def serialize_ansi(spans: Iterable[StyledSpan]) -> str:
    """Wrap each semantic span with a fixed local ANSI style and reset."""

    parts: list[str] = []
    for span in spans:
        code = _ANSI_BY_ROLE.get(span.role)
        if code is None or not span.text:
            parts.append(span.text)
        else:
            parts.extend((code, span.text, _RESET))
    return "".join(parts)
