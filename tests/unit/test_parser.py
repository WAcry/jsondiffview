from __future__ import annotations

from decimal import Decimal

import pytest

from jsondiffview.model import (
    DIAGNOSTIC_MESSAGE_LIMIT,
    JsonNumber,
    JsonNumberKind,
    JsonValue,
    bounded_diagnostic_text,
)
from jsondiffview.parser import (
    CONTAINER_DEPTH_LIMIT,
    DECIMAL_LEXEME_LIMIT,
    INTEGER_DIGIT_LIMIT,
    JsonParseError,
    canonical_fingerprint,
    decode_json_bytes,
    strict_equal,
)


def parse(text: str) -> JsonValue:
    return decode_json_bytes(text.encode(), "fixture.json")


def test_utf8_bom_is_accepted() -> None:
    assert strict_equal(
        decode_json_bytes(b'\xef\xbb\xbf{"name":"caf\xc3\xa9"}', "bom.json"),
        parse('{"name":"caf\u00e9"}'),
    )


def test_invalid_utf8_reports_the_byte_offset() -> None:
    with pytest.raises(JsonParseError, match=r"invalid UTF-8 at byte 1"):
        decode_json_bytes(b'"\xff"', "bad.json")


def test_duplicate_keys_are_rejected_at_nested_objects() -> None:
    with pytest.raises(
        JsonParseError,
        match=r"duplicate object key 'id'",
    ):
        parse('{"nested":{"id":1,"id":2}}')


def test_long_duplicate_key_diagnostic_is_bounded() -> None:
    key = "k" * 1_000
    with pytest.raises(JsonParseError) as caught:
        parse(f'{{"{key}":1,"{key}":2}}')

    message = str(caught.value)
    assert len(message) < 300
    assert key not in message
    assert "920 code points omitted" in message


def test_diagnostic_text_is_bounded_and_control_safe() -> None:
    message = "a" * (DIAGNOSTIC_MESSAGE_LIMIT + 1) + "\u009b"
    result = bounded_diagnostic_text(message)

    assert "\u009b" not in result
    assert "\\u009b" in result
    assert "code points omitted" in result
    assert len(result) < 600


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_constants_are_rejected(constant: str) -> None:
    with pytest.raises(JsonParseError, match="non-finite number"):
        parse(constant)


@pytest.mark.parametrize("literal", ["1e999", "-1E999"])
def test_binary64_overflow_is_rejected(literal: str) -> None:
    with pytest.raises(JsonParseError, match="supported finite range"):
        parse(literal)


@pytest.mark.parametrize(
    ("digit_count", "accepted"),
    [
        (INTEGER_DIGIT_LIMIT - 1, True),
        (INTEGER_DIGIT_LIMIT, True),
        (INTEGER_DIGIT_LIMIT + 1, False),
    ],
)
def test_integer_digit_limit_boundaries(
    digit_count: int,
    accepted: bool,
) -> None:
    literal = "9" * digit_count
    if accepted:
        value = parse(literal)
        assert isinstance(value, JsonNumber)
        assert value.lexeme == literal
    else:
        with pytest.raises(JsonParseError, match="supported numeric limit"):
            parse(literal)


def test_malformed_json_reports_source_line_and_column() -> None:
    with pytest.raises(
        JsonParseError,
        match=(
            r"fixture\.json: invalid JSON at line 2, column 1: "
            r"trailing commas are not valid JSON"
        ),
    ):
        parse('{"ok": true,\n}')


def test_array_trailing_comma_uses_stable_location_and_wording() -> None:
    with pytest.raises(
        JsonParseError,
        match=(
            r"fixture\.json: invalid JSON at line 2, column 1: "
            r"trailing commas are not valid JSON"
        ),
    ):
        parse("[true,\n]")


def test_number_categories_and_lexemes_are_preserved() -> None:
    value = parse("[1,1.00,1e0]")
    assert isinstance(value, list)
    assert value == [
        JsonNumber(JsonNumberKind.INTEGER, 1, "1"),
        JsonNumber(JsonNumberKind.DECIMAL, Decimal("1.00"), "1.00"),
        JsonNumber(JsonNumberKind.DECIMAL, Decimal("1"), "1e0"),
    ]


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("1", "1", True),
        ("1.0", "1.00", True),
        ("1", "1.0", False),
        ("true", "1", False),
        ('"1"', "1", False),
        ('{"a":1,"b":2}', '{"b":2,"a":1}', True),
        ("[1,2]", "[2,1]", False),
    ],
)
def test_strict_equality(left: str, right: str, expected: bool) -> None:
    assert strict_equal(parse(left), parse(right)) is expected


def test_fingerprints_follow_strict_equality() -> None:
    assert canonical_fingerprint(parse('{"a":1.0,"b":[true,null]}')) == (
        canonical_fingerprint(parse('{"b":[true,null],"a":1.00}'))
    )
    assert canonical_fingerprint(parse("1")) != canonical_fingerprint(parse("1.0"))
    assert canonical_fingerprint(parse("true")) != canonical_fingerprint(parse("1"))


@pytest.mark.parametrize(
    ("length", "accepted"),
    [
        (DECIMAL_LEXEME_LIMIT - 1, True),
        (DECIMAL_LEXEME_LIMIT, True),
        (DECIMAL_LEXEME_LIMIT + 1, False),
    ],
)
def test_decimal_lexeme_limit_boundaries(length: int, accepted: bool) -> None:
    literal = "0." + "1" * (length - 2)
    if accepted:
        value = parse(literal)
        assert isinstance(value, JsonNumber)
        assert value.lexeme == literal
    else:
        with pytest.raises(JsonParseError, match="decimal lexeme exceeds"):
            parse(literal)


@pytest.mark.parametrize(
    ("depth", "accepted"),
    [
        (CONTAINER_DEPTH_LIMIT - 1, True),
        (CONTAINER_DEPTH_LIMIT, True),
        (CONTAINER_DEPTH_LIMIT + 1, False),
    ],
)
def test_container_depth_limit_boundaries(depth: int, accepted: bool) -> None:
    document = "[" * depth + "0" + "]" * depth
    if accepted:
        assert isinstance(parse(document), list)
    else:
        with pytest.raises(JsonParseError, match=r"nesting exceeds.*256"):
            parse(document)


def test_decoder_recursion_failure_uses_the_depth_diagnostic() -> None:
    document = "[" * 2_000 + "0" + "]" * 2_000
    with pytest.raises(JsonParseError, match=r"fixture\.json: container nesting"):
        parse(document)
