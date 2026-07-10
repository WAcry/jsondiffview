"""Narrow compatibility bridge for the pinned PyPI publishing action."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
import sys
from collections.abc import Mapping, MutableSequence, Set
from pathlib import Path
from typing import Protocol, cast

ACTION_COMMIT = "cef221092ed1bacb1cc03d23a2d87d1d172e277b"
ACTION_TAG = "v1.14.0"
ACTION_PACKAGING_VERSION = "25.0"
PACKAGING_VERSION = "26.2"
PACKAGING_WHEEL_SHA256 = (
    "5fc45236b9446107ff2415ce77c807cee2862cb6fac22b8a73826d0693b0980e"
)
PACKAGING_TREE_SHA256 = (
    "ee6e82aff69076140093e74c33fdd584f76937492a18d283bffe26a34ac3cb84"
)
PUBLISHER_VERSION = "6.1.0"
MANIFEST_NAME = "publisher-compat.json"


class MetadataTables(Protocol):
    """Private parser tables fixed by the action's fully pinned dependency set."""

    _VALID_METADATA_VERSIONS: MutableSequence[str]
    _EMAIL_TO_RAW_MAPPING: Mapping[str, str]
    _LIST_FIELDS: Set[str]


def patch_metadata_parser(
    metadata_tables: MetadataTables,
    *,
    packaging_version: str,
    publisher_version: str,
) -> None:
    """Teach the pinned uploader about final Core Metadata 2.5."""

    if packaging_version != PACKAGING_VERSION:
        raise RuntimeError(
            f"expected packaging {PACKAGING_VERSION}, found {packaging_version}"
        )
    if publisher_version != PUBLISHER_VERSION:
        raise RuntimeError(
            f"expected publisher {PUBLISHER_VERSION}, found {publisher_version}"
        )
    if metadata_tables._EMAIL_TO_RAW_MAPPING.get("import-name") != "import_names":
        raise RuntimeError("packaging does not recognize Metadata 2.5 Import-Name")
    if "import_names" not in metadata_tables._LIST_FIELDS:
        raise RuntimeError("packaging does not classify Import-Name as repeatable")

    versions = metadata_tables._VALID_METADATA_VERSIONS
    if "2.5" in versions:
        return
    if "2.4" not in versions:
        raise RuntimeError("publisher metadata-version table is unexpected")
    versions.append("2.5")


def packaging_tree_sha256(root: Path) -> str:
    """Hash the exact source tree staged ahead of the action dependencies."""

    if not root.is_dir() or root.is_symlink():
        raise RuntimeError(f"packaging overlay is not a regular directory: {root}")
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"packaging overlay contains a symlink: {path}")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            files.append(path)
    if not files:
        raise RuntimeError("packaging overlay contains no source files")

    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def publisher_manifest() -> dict[str, str]:
    """Return the immutable action and parser provenance contract."""

    return {
        "action_commit": ACTION_COMMIT,
        "action_packaging_version": ACTION_PACKAGING_VERSION,
        "action_tag": ACTION_TAG,
        "overlay_packaging_tree_sha256": PACKAGING_TREE_SHA256,
        "overlay_packaging_version": PACKAGING_VERSION,
        "overlay_packaging_wheel_sha256": PACKAGING_WHEEL_SHA256,
        "twine_version": PUBLISHER_VERSION,
    }


def activate(overlay: Path | None = None) -> None:
    """Patch only the exact dependency versions bundled with the pinned action."""

    overlay = (overlay or Path(__file__).resolve().parent).resolve()
    _validate_overlay(overlay)
    overlay_text = str(overlay)
    sys.path[:] = [entry for entry in sys.path if entry != overlay_text]
    sys.path.insert(0, overlay_text)

    packaging = importlib.import_module("packaging")
    packaging_version = getattr(packaging, "__version__", None)
    if not isinstance(packaging_version, str):
        raise RuntimeError("cannot identify packaging version")
    action_packaging_version = importlib.metadata.version("packaging")
    if action_packaging_version != ACTION_PACKAGING_VERSION:
        raise RuntimeError(
            f"expected action packaging {ACTION_PACKAGING_VERSION}, "
            f"found {action_packaging_version}"
        )

    publisher_package = importlib.import_module("twine.package")
    metadata_tables = cast(MetadataTables, publisher_package.metadata)
    patch_metadata_parser(
        metadata_tables,
        packaging_version=packaging_version,
        publisher_version=importlib.metadata.version("twine"),
    )


def _validate_overlay(overlay: Path) -> None:
    manifest_path = overlay / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("publisher compatibility manifest is invalid") from error
    if manifest != publisher_manifest():
        raise RuntimeError("publisher compatibility manifest differs from the pin")

    digest = packaging_tree_sha256(overlay / "packaging")
    if digest != PACKAGING_TREE_SHA256:
        raise RuntimeError(
            "packaging overlay SHA-256 differs from the locked source tree"
        )


def _activate_sitecustomize() -> None:
    try:
        activate()
    except BaseException as error:
        message = f"publisher compatibility activation failed: {error}\n"
        os.write(2, message.encode("utf-8", errors="backslashreplace"))
        os._exit(1)


if __name__ == "sitecustomize":
    _activate_sitecustomize()
