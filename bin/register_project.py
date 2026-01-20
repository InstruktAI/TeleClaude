#!/usr/bin/env python3
"""Register a project snippet index with TeleClaude."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from instrukt_ai_logging import configure_logging, get_logger

from teleclaude.config import config
from teleclaude.constants import MAIN_MODULE
from teleclaude.project_registry import register_project_index

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Register project docs/index.yaml with TeleClaude.")
    parser.add_argument(
        "--project-root",
        default=os.getcwd(),
        help="Project root (default: cwd)",
    )
    parser.add_argument(
        "--index",
        default=None,
        help="Index path (default: <project-root>/docs/index.yaml)",
    )
    args = parser.parse_args()

    configure_logging("teleclaude")

    project_root = Path(args.project_root).expanduser().resolve()
    index_path = Path(args.index).expanduser().resolve() if args.index else project_root / "docs" / "index.yaml"

    if not index_path.exists():
        raise SystemExit(f"Index not found: {index_path}")

    db_path = Path(config.database.path).expanduser().resolve()
    register_project_index(db_path, project_root, index_path)
    logger.info("Project registered", project=str(project_root), index=str(index_path))
    print(str(index_path))


if __name__ == MAIN_MODULE:
    main()
