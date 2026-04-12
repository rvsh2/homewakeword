"""Command line entrypoint for the HomeWake package."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from homewake.config import HomeWakeConfig


def build_parser() -> argparse.ArgumentParser:
    """Build the minimal CLI parser for architecture verification."""

    parser = argparse.ArgumentParser(
        prog="python -m homewake.cli",
        description="HomeWake runtime shell with frozen architecture contracts.",
    )
    parser.add_argument(
        "--host", default=HomeWakeConfig().server.host, help="Wyoming bind host"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=HomeWakeConfig().server.port,
        help="Wyoming bind port",
    )
    parser.add_argument(
        "--detector-backend",
        default=HomeWakeConfig().detector.backend,
        help="Detector backend identifier",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI arguments without starting runtime behavior yet."""

    build_parser().parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
