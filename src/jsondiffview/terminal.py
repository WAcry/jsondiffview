"""Shared policy for displaying untrusted text without terminal controls."""

from __future__ import annotations


def requires_visible_escape(character: str) -> bool:
    """Keep controls visible without escaping ordinary script or emoji joiners.

    Bidi_Control is the explicit set from Unicode PropList.txt / UAX #9.
    Escaping all format characters would also damage ZWJ emoji and text using
    ZWNJ, so do not substitute a blanket Unicode category-Cf check here.
    """

    code_point = ord(character)
    return (
        code_point < 0x20
        or 0x7F <= code_point <= 0x9F
        or code_point in {0x061C, 0x200E, 0x200F, 0x2028, 0x2029}
        or 0x202A <= code_point <= 0x202E
        or 0x2066 <= code_point <= 0x2069
        or 0xD800 <= code_point <= 0xDFFF
    )
