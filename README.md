# jdv

`jdv` is a review-oriented JSON diff CLI.

This repository is currently in bootstrap mode. The first executable slice provides:

- strict JSON input loading with duplicate-key rejection
- non-finite number rejection, including overflowed literals such as `1e999`
- a minimal root-level replacement view for changed documents
- silent zero-diff behavior on `stdout`, with the optional TTY notice on `stderr`

## Development

Create the environment and run the CLI:

    uv sync
    uv run python -m jdv --help

Run the test suite:

    uv run pytest -q
