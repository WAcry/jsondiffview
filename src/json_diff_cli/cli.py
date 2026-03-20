import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .diff_engine import diff_values
from .errors import UserInputError
from .loader import load_json_file, load_match_config
from .match_rules import build_match_rule_set
from .renderers import render_focused, render_full


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
        parser.print_usage(sys.stderr)
        return 2

    try:
        left = load_json_file(Path(args.file_a))
        right = load_json_file(Path(args.file_b))
        match_config = (
            load_match_config(Path(args.match_config))
            if args.match_config is not None
            else None
        )
        match_rules = build_match_rule_set(args.match, match_config)
        diff = diff_values(
            "",
            left,
            right,
            array_mode=args.array_match,
            match_rules=match_rules,
        )
        if args.quiet:
            return 1 if diff.has_changes else 0

        rendered = _render_output(
            diff,
            view=args.view,
            color=args.color,
            context_lines=args.context_lines,
            sort_keys=args.sort_keys,
        )
        if rendered:
            print(rendered)
        return 1 if diff.has_changes else 0
    except UserInputError as exc:
        _write_stderr(str(exc))
        return 2
    except Exception as exc:
        message = "internal error"
        details = str(exc).strip()
        if details:
            message = f"{message}: {details}"
        _write_stderr(message)
        return 3


def _render_output(
    diff,
    *,
    view: str,
    color: str,
    context_lines: int,
    sort_keys: bool,
) -> str:
    if view == "focused":
        return render_focused(
            diff,
            color=color,
            context_lines=context_lines,
            sort_keys=sort_keys,
        )
    return render_full(diff, color=color, sort_keys=sort_keys)


def _write_stderr(message: str) -> None:
    sys.stderr.write(f"{message}\n")
