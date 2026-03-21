from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib
from typing import Sequence

__all__ = ["__version__", "main"]


def _load_version() -> str:
    try:
        return version("jsondiffview")
    except PackageNotFoundError:
        pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        with pyproject_path.open("rb") as handle:
            project = tomllib.load(handle)["project"]
        return str(project["version"])


def main(argv: Sequence[str] | None = None) -> int:
    from jsondiffview_cli import main as cli_main

    return cli_main(argv)


__version__ = _load_version()


if __name__ == "__main__":
    raise SystemExit(main())
