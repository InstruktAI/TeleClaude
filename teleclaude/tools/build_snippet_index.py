#!/usr/bin/env python3
"""Build docs/index.yaml from docs/snippets frontmatter."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from instrukt_ai_logging import configure_logging, get_logger

from teleclaude.constants import MAIN_MODULE
from teleclaude.context_index import write_index_yaml

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build docs/index.yaml for project snippets.")
    parser.add_argument(
        "--project-root",
        default=os.getcwd(),
        help="Project root (default: cwd)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path (default: <project-root>/docs/index.yaml)",
    )
    args = parser.parse_args()

    configure_logging("teleclaude")

    project_root = Path(args.project_root).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve() if args.output else None

    written = write_index_yaml(project_root, output_path=output_path)
    logger.info("Snippet index written", path=str(written))
    print(str(written))


if __name__ == MAIN_MODULE:
    main()
