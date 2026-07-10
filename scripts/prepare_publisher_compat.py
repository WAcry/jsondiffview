"""Stage the locked Metadata 2.5 parser for the pinned publishing action."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import packaging

from scripts.publisher_compat import (
    MANIFEST_NAME,
    PACKAGING_TREE_SHA256,
    PACKAGING_VERSION,
    PACKAGING_WHEEL_SHA256,
    packaging_tree_sha256,
    publisher_manifest,
)


def main(arguments: Sequence[str] | None = None) -> int:
    """Copy the exact locked parser and fail-closed compatibility bridge."""

    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    options = parser.parse_args(arguments)
    try:
        prepare(options.destination)
    except (OSError, RuntimeError) as error:
        print(f"publisher compatibility setup failed: {error}", file=sys.stderr)
        return 1
    print(f"prepared Metadata 2.5 publisher support in {options.destination}")
    return 0


def prepare(destination: Path) -> None:
    """Stage a minimal pure-Python overlay without changing release archives."""

    if packaging.__version__ != PACKAGING_VERSION:
        raise RuntimeError(
            f"expected locked packaging {PACKAGING_VERSION}, "
            f"found {packaging.__version__}"
        )
    if destination.exists():
        raise RuntimeError(f"destination already exists: {destination}")
    if not destination.parent.is_dir():
        raise RuntimeError(f"destination parent does not exist: {destination.parent}")
    if packaging.__file__ is None:
        raise RuntimeError("cannot locate the locked packaging module")

    source = Path(packaging.__file__).resolve().parent
    source_digest = packaging_tree_sha256(source)
    if source_digest != PACKAGING_TREE_SHA256:
        raise RuntimeError("installed packaging source differs from the pinned tree")
    _require_locked_packaging(Path(__file__).resolve().parents[1] / "uv.lock")

    with tempfile.TemporaryDirectory(
        prefix="publisher-compat-",
        dir=destination.parent,
    ) as raw:
        staging = Path(raw) / destination.name
        staging.mkdir()
        shutil.copytree(
            source,
            staging / "packaging",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copy2(
            Path(__file__).with_name("publisher_compat.py"),
            staging / "sitecustomize.py",
        )
        (staging / MANIFEST_NAME).write_text(
            json.dumps(publisher_manifest(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if packaging_tree_sha256(staging / "packaging") != PACKAGING_TREE_SHA256:
            raise RuntimeError("copied packaging overlay differs from its source")
        staging.replace(destination)


def _require_locked_packaging(lock_path: Path) -> None:
    text = lock_path.read_text(encoding="utf-8")
    package = re.search(
        r'(?ms)^\[\[package\]\]\nname = "packaging"\n'
        rf'version = "{re.escape(PACKAGING_VERSION)}"\n'
        r".*?(?=^\[\[package\]\]|\Z)",
        text,
    )
    if package is None:
        raise RuntimeError("uv.lock does not contain the exact packaging version")
    wheel = re.compile(
        r'\{ url = "https://files\.pythonhosted\.org/[^"]*/'
        rf'packaging-{re.escape(PACKAGING_VERSION)}-py3-none-any\.whl", '
        rf'hash = "sha256:{PACKAGING_WHEEL_SHA256}"'
    )
    if wheel.search(package.group(0)) is None:
        raise RuntimeError("uv.lock does not contain the pinned packaging wheel hash")


if __name__ == "__main__":
    raise SystemExit(main())
