# jsondiffview

`jsondiffview` is a terminal-first JSON diff CLI for comparing two JSON files with strict parsing and deterministic output.
It is designed for people who want readable diffs without sacrificing correctness around invalid JSON, invalid YAML rules, duplicate keys, or array matching edge cases.

## Features

- Strict JSON input validation, including duplicate-key rejection and non-standard number rejection.
- Two output modes: `full` for full-structure context and `changed` for a concise change report.
- Deterministic array matching with `position` and `smart` modes.
- Optional YAML match rules for object-array identity matching.
- Plain-text and color-aware output modes for local terminals and CI logs.

## Installation

Install the released CLI with one of the following commands:

```bash
uv tool install jsondiffview
pipx install jsondiffview
pip install jsondiffview
```

After installation, inspect the CLI surface first:

```bash
jsondiffview --help
jsondiffview --version
```

You can also run the module entrypoint directly:

```bash
python -m jsondiffview --help
```

## Quick Start

Create two JSON files:

```json
{"countries":[{"id":1,"capital":"Buenos Aires"}]}
```

```json
{"countries":[{"id":1,"capital":"Rawson"}]}
```

Render a concise change report:

```bash
jsondiffview before.json after.json --view changed --array-match smart --match id
```

Expected shape:

```text
countries[id=1].capital (replace)
  old: "Buenos Aires"
  new: "Rawson"
```

Render the entire structure instead:

```bash
jsondiffview before.json after.json --view full --array-match smart --match id
```

## Output Views

`--view full` renders the full JSON structure with inline change markers.
Use it when you want surrounding context, not just the changed paths.

`--view changed` renders one block per semantic change.
Use it when you want a stable report that is easy to scan in code review, logs, or terminal output.

## Array Matching

`--array-match position` compares arrays by index.
This is the default and is appropriate when order is part of the meaning.

`--array-match smart` applies deterministic matching instead of raw position.
Primitive arrays match by value and occurrence.
Object arrays match by explicit identity keys from `--match` or `--match-config`.

Simple global match keys can be provided directly on the command line:

```bash
jsondiffview before.json after.json --array-match smart --match id --match name
```

For richer rules, use YAML:

```yaml
global_matches:
  - id
path_matches:
  countries:
    - id
  countries.*.cities:
    - identity.id
```

Then run:

```bash
jsondiffview before.json after.json --array-match smart --match-config rules.yaml
```

## Color Behavior

`--color auto` uses ANSI colors when stdout is an interactive terminal and falls back to plain text in non-interactive environments.
This is the default and is suitable for everyday terminal use.

`--color never` disables ANSI color and uses explicit textual markers such as `[-old-]` and `[+new+]`.
Use it when you need logs that stay readable in tools that strip color.

## Development

From the repository root:

```bash
uv run pytest
uv build --no-sources
uvx twine check dist/*
```

The release repository is expected to live at `https://github.com/WAcry/jsondiffview`.
