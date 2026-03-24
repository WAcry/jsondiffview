from __future__ import annotations

import pytest

from jdv.io import InputUsageError, JsonParseError, read_json_source


def test_read_json_source_rejects_duplicate_keys(tmp_path) -> None:
    path = tmp_path / "dup.json"
    path.write_text('{"a": 1, "a": 2}', encoding="utf-8")

    with pytest.raises(JsonParseError, match="duplicate object key"):
        read_json_source(str(path), None, "old")


def test_read_json_source_rejects_non_finite_constant(tmp_path) -> None:
    path = tmp_path / "nan.json"
    path.write_text('{"a": NaN}', encoding="utf-8")

    with pytest.raises(JsonParseError, match="non-finite number"):
        read_json_source(str(path), None, "old")


def test_read_json_source_rejects_overflow_float(tmp_path) -> None:
    path = tmp_path / "overflow.json"
    path.write_text('{"a": 1e999}', encoding="utf-8")

    with pytest.raises(JsonParseError, match="non-finite number"):
        read_json_source(str(path), None, "new")


def test_read_json_source_supports_stdin() -> None:
    assert read_json_source("-", '{"a": 1}', "new") == {"a": 1}


def test_dash_input_requires_stdin_text() -> None:
    with pytest.raises(InputUsageError, match="expected stdin input"):
        read_json_source("-", None, "old")
