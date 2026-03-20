import argparse
from typing import Sequence

from . import __version__


def parse_non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="json-diff", usage="json-diff FILE_A FILE_B")
    parser.add_argument("file_a", nargs="?", metavar="FILE_A")
    parser.add_argument("file_b", nargs="?", metavar="FILE_B")
    parser.add_argument("--view", choices=("full", "focused"), default="full")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--array-match", choices=("position", "smart"), default="position")
    parser.add_argument("--match", action="append", default=[])
    parser.add_argument("--match-config")
    parser.add_argument("--context-lines", type=parse_non_negative_int, default=2)
    parser.add_argument("--sort-keys", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--version", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(f"json-diff-cli {__version__}")
        return 0
    if args.file_a is None or args.file_b is None:
        parser.print_usage()
        return 2
    return 0
