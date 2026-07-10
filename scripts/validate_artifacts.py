"""Validate local jsondiffview wheel and sdist release invariants."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from email.message import Message
from email.parser import BytesParser
from email.policy import default
from pathlib import Path, PurePosixPath

from readme_renderer import markdown

NAME = "jsondiffview"
VERSION = "3.0.0"
WHEEL_NAME = f"{NAME}-{VERSION}-py3-none-any.whl"
SDIST_NAME = f"{NAME}-{VERSION}.tar.gz"
DIST_INFO = f"{NAME}-{VERSION}.dist-info"
SCREENSHOT_PATH = "playground/jdv-review.png"
SCREENSHOT_URL = (
    "https://raw.githubusercontent.com/WAcry/jsondiffview/"
    "main/playground/jdv-review.png"
)
SCREENSHOT_MARKDOWN = (
    "![Terminal screenshot of jdv reviewing nested JSON changes, moves, "
    f"additions, and removals]({SCREENSHOT_URL})"
)
SCREENSHOT_SHA256 = (
    "a9afbbd91e16f750fa6e7bdf2e78b9d940826715451cee79702d9c36d1dbb281"
)
PACKAGE_FILES = {
    f"{NAME}/{module}.py"
    for module in (
        "__init__",
        "__main__",
        "cli",
        "color",
        "diff",
        "matching",
        "model",
        "parser",
        "render",
        "strings",
    )
}
TEST_FILES = {
    "tests/corpus/array_cases.jsonl",
    "tests/corpus/baseline_hashes.jsonl",
    "tests/corpus/string_cases.jsonl",
    "tests/fixtures/review_after.json",
    "tests/fixtures/review_before.json",
    "tests/integration/test_cli.py",
    "tests/integration/test_workflow_policy.py",
    "tests/unit/test_corpus.py",
    "tests/unit/test_diff.py",
    "tests/unit/test_matching.py",
    "tests/unit/test_parser.py",
    "tests/unit/test_render.py",
    "tests/unit/test_strings.py",
    "tests/unit/test_v2_migration_regressions.py",
}
PLAYGROUND_FILES = {
    "playground/README.md",
    "playground/context-after.json",
    "playground/context-before.json",
    "playground/custom-key-after.json",
    "playground/custom-key-before.json",
    "playground/equal.json",
    "playground/invalid-duplicate-key.json",
    SCREENSHOT_PATH,
    "playground/matching-after.json",
    "playground/matching-before.json",
    "playground/review-after.json",
    "playground/review-before.json",
    "playground/strings-after.json",
    "playground/strings-before.json",
}
SDIST_FILES = (
    {
        ".gitignore",
        "LICENSE",
        "MIGRATING.md",
        "README.md",
        "PKG-INFO",
        "benchmarks/benchmark_jsondiffview.py",
        "pyproject.toml",
        "uv.lock",
    }
    | {f"src/{name}" for name in PACKAGE_FILES}
    | TEST_FILES
    | PLAYGROUND_FILES
)
SDIST_DIRECTORIES = {
    "/".join(PurePosixPath(path).parts[:depth])
    for path in SDIST_FILES
    for depth in range(1, len(PurePosixPath(path).parts))
}
WHEEL_FILES = PACKAGE_FILES | {
    f"{DIST_INFO}/METADATA",
    f"{DIST_INFO}/WHEEL",
    f"{DIST_INFO}/entry_points.txt",
    f"{DIST_INFO}/licenses/LICENSE",
    f"{DIST_INFO}/RECORD",
}
PROJECT_URLS = {
    "Homepage, https://github.com/WAcry/jsondiffview",
    "Repository, https://github.com/WAcry/jsondiffview",
    "Issues, https://github.com/WAcry/jsondiffview/issues",
    "Changelog, https://github.com/WAcry/jsondiffview/releases",
}
REQUIRES_DIST = {
    "click<8.5,>=8.4.2",
    "regex==2026.6.28",
    "wcwidth==0.8.2",
}
CLASSIFIERS = {
    "Development Status :: 5 - Production/Stable",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
    "Topic :: Software Development :: Testing",
    "Topic :: Utilities",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "dist",
        nargs="?",
        type=Path,
        default=Path("dist"),
        help="Distribution directory or either expected archive.",
    )
    parser.add_argument(
        "--rebuild-sdist",
        action="store_true",
        help="Build and validate a wheel from the exact sdist.",
    )
    arguments = parser.parse_args()
    wheel, sdist = _resolve_archives(arguments.dist)
    _validate_wheel(wheel)
    _validate_sdist(sdist)
    _validate_lock(wheel.parents[1] / "uv.lock")
    if arguments.rebuild_sdist:
        _rebuild_sdist(sdist)
    print(f"validated {wheel.name} and {sdist.name}")
    return 0


def _resolve_archives(path: Path) -> tuple[Path, Path]:
    directory = path if path.is_dir() else path.parent
    wheel = directory / WHEEL_NAME
    sdist = directory / SDIST_NAME
    actual = {item.name for item in directory.iterdir() if item.is_file()}
    expected = {WHEEL_NAME, SDIST_NAME}
    unexpected_archives = {
        name for name in actual if name.endswith((".whl", ".tar.gz", ".zip"))
    } - expected
    assert not unexpected_archives, f"unexpected archives: {unexpected_archives}"
    assert wheel.is_file(), f"missing {wheel}"
    assert sdist.is_file(), f"missing {sdist}"
    return wheel, sdist


def _validate_wheel(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        assert len(names) == len(set(names)), "wheel has duplicate members"
        assert set(names) == WHEEL_FILES, (
            f"wheel contents differ: missing={WHEEL_FILES - set(names)}, "
            f"extra={set(names) - WHEEL_FILES}"
        )
        for name in names:
            _assert_safe_path(name)
        for info in infos:
            mode = info.external_attr >> 16
            assert not stat.S_ISLNK(mode), (
                f"wheel symlink is not allowed: {info.filename}"
            )

        metadata = _parse_metadata(archive.read(f"{DIST_INFO}/METADATA"))
        _validate_metadata(metadata)
        wheel_metadata = archive.read(f"{DIST_INFO}/WHEEL").decode("utf-8")
        assert "Root-Is-Purelib: true\n" in wheel_metadata
        assert "Tag: py3-none-any\n" in wheel_metadata
        entry_points = archive.read(f"{DIST_INFO}/entry_points.txt").decode("utf-8")
        assert entry_points == ("[console_scripts]\njdv = jsondiffview.cli:main\n")
        _validate_record(archive)


def _validate_record(archive: zipfile.ZipFile) -> None:
    record_name = f"{DIST_INFO}/RECORD"
    rows = list(
        csv.reader(
            io.StringIO(archive.read(record_name).decode("utf-8")),
        )
    )
    assert all(len(row) == 3 for row in rows), "malformed RECORD row"
    by_name = {row[0]: row for row in rows}
    assert len(rows) == len(by_name), "RECORD has duplicate members"
    assert set(by_name) == set(archive.namelist())
    for name in archive.namelist():
        row = by_name[name]
        if name == record_name:
            assert row[1:] == ["", ""]
            continue
        algorithm, encoded = row[1].split("=", 1)
        assert algorithm == "sha256"
        digest = hashlib.sha256(archive.read(name)).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        assert encoded == expected, f"bad RECORD hash for {name}"
        assert row[2] == str(len(archive.read(name)))


def _validate_sdist(sdist: Path) -> None:
    root = f"{NAME}-{VERSION}"
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name.rstrip("/") for member in members]
        assert len(names) == len(set(names)), "sdist has duplicate members"
        for member in members:
            _assert_safe_path(member.name)
            assert member.name == root or member.name.startswith(root + "/")
            assert not (
                member.issym() or member.islnk() or member.isdev() or member.isfifo()
            ), f"unsafe sdist member type: {member.name}"
            assert member.isfile() or member.isdir(), (
                f"unsupported sdist member type: {member.name}"
            )

        relative_files = {
            name.removeprefix(root + "/")
            for name, member in zip(names, members, strict=True)
            if member.isfile()
        }
        relative_directories = {
            name.removeprefix(root + "/")
            for name, member in zip(names, members, strict=True)
            if member.isdir() and name != root
        }
        assert relative_files == SDIST_FILES, (
            f"sdist contents differ: missing={SDIST_FILES - relative_files}, "
            f"extra={relative_files - SDIST_FILES}"
        )
        assert relative_directories <= SDIST_DIRECTORIES, (
            f"unexpected sdist directories: {relative_directories - SDIST_DIRECTORIES}"
        )
        assert not any(
            part in {".cursor", ".github", ".trellis", "__pycache__", "dist"}
            for path in relative_files
            for part in PurePosixPath(path).parts
        )
        screenshot = archive.extractfile(f"{root}/{SCREENSHOT_PATH}")
        assert screenshot is not None
        assert hashlib.sha256(screenshot.read()).hexdigest() == SCREENSHOT_SHA256

        pkg_info = archive.extractfile(f"{root}/PKG-INFO")
        assert pkg_info is not None
        _validate_metadata(_parse_metadata(pkg_info.read()))


def _validate_metadata(metadata: Message) -> None:
    assert metadata["Metadata-Version"] == "2.5"
    assert metadata["Name"] == NAME
    assert metadata["Version"] == VERSION
    assert metadata["Summary"] == (
        "Deterministic, review-oriented strict JSON diffs for humans"
    )
    assert metadata["Author-email"] == ("David Zhang <davidzhang2000@outlook.com>")
    assert metadata["Keywords"] == "cli,diff,json,review,terminal"
    assert metadata["Requires-Python"] == ">=3.11"
    assert metadata["License-Expression"] == "MIT"
    assert metadata.get_all("License-File") == ["LICENSE"]
    assert metadata.get_all("Import-Name") == [NAME]
    assert set(metadata.get_all("Project-URL", [])) == PROJECT_URLS
    assert set(metadata.get_all("Requires-Dist", [])) == REQUIRES_DIST
    assert set(metadata.get_all("Classifier", [])) == CLASSIFIERS
    assert metadata.get_all("Dynamic", []) == []
    assert metadata["Description-Content-Type"] == "text/markdown"
    description = metadata.get_payload()
    assert isinstance(description, str)
    assert description.count(SCREENSHOT_MARKDOWN) == 1
    assert description.count(SCREENSHOT_URL) == 1
    warnings = io.StringIO()
    assert markdown.render(description, stream=warnings) is not None
    assert warnings.getvalue() == ""


def _parse_metadata(data: bytes) -> Message:
    return BytesParser(policy=default).parsebytes(data)


def _validate_lock(lock_path: Path) -> None:
    text = lock_path.read_text(encoding="utf-8")
    package_block = 'name = "jsondiffview"\nversion = "3.0.0"'
    assert package_block in text
    assert 'name = "regex"\nversion = "2026.6.28"' in text
    assert 'name = "wcwidth"\nversion = "0.8.2"' in text
    assert "patiencediff" not in text


def _rebuild_sdist(sdist: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="jsondiffview-rebuild-") as raw:
        output = Path(raw)
        subprocess.run(
            [
                "uv",
                "build",
                "--wheel",
                "--no-sources",
                "--out-dir",
                str(output),
                str(sdist),
            ],
            check=True,
        )
        rebuilt = output / WHEEL_NAME
        assert rebuilt.is_file()
        _validate_wheel(rebuilt)
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("validate_clean_install.py")),
                str(rebuilt),
            ],
            check=True,
        )


def _assert_safe_path(name: str) -> None:
    path = PurePosixPath(name)
    assert not path.is_absolute(), f"absolute archive path: {name}"
    assert "\\" not in name, f"non-POSIX archive path: {name}"
    assert ".." not in path.parts, f"parent traversal in archive: {name}"


if __name__ == "__main__":
    raise SystemExit(main())
