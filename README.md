# jdv

`jdv` is a review-oriented JSON diff CLI.

Current behavior:

- strict JSON input loading with duplicate-key rejection
- non-finite number rejection, including overflowed literals such as `1e999`
- three review modes: `compact`, `focus`, and `full`
- identity-aware array matching via `id`, `key`, `name`, `title`, plus exact-value relocation
- move and remove provenance in review output
- silent zero-diff behavior on `stdout`, with the optional TTY notice on `stderr`

`compact` is the default mode and collapses unchanged context.
`focus` shows the full changed material while still collapsing unchanged siblings.
`full` expands the same semantic diff tree without changing move/remove decisions.

## Usage

Default compact review:

    uv run python -m jdv before.json after.json

Focus review with explicit match keys:

    uv run python -m jdv --view focus --match-key sku --match-key variant_id before.json after.json

Full review without ANSI color:

    uv run python -m jdv --view full --color never before.json after.json

## Development

Create the environment and run the CLI:

    uv sync
    uv run python -m jdv --help

Run the test suite:

    uv run pytest -q
