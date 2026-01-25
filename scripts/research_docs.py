#!/usr/bin/env python3
"""Script to manage 3rd-party documentation research results."""

import argparse
import os
from datetime import datetime

from teleclaude.constants import MAIN_MODULE


def update_index(_: str, __: str, ___: str, ____: str, output_dir: str = "docs/third-party") -> None:
    """No-op: index.md files are disallowed outside baseline."""
    print(f"Skipping index.md generation for {output_dir}. Index files are only allowed in baseline.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage 3rd-party research docs.")
    parser.add_argument("--title", required=True, help="Title of the documentation")
    parser.add_argument("--filename", required=True, help="Target filename in output directory")
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="Source URL or Context7 snippet ID (repeatable)",
    )
    parser.add_argument("--purpose", required=True, help="Brief description of what this doc is for")
    parser.add_argument("--content", required=True, help="Concise markdown content")
    parser.add_argument(
        "--output-dir",
        default="docs/third-party",
        help="Output directory (default: docs/third-party)",
    )

    args = parser.parse_args()

    # Ensure filename ends with .md
    if not args.filename.endswith(".md"):
        args.filename += ".md"

    # Write the doc file
    output_dir = args.output_dir
    if output_dir != "docs/third-party":
        raise SystemExit("ERROR: research_docs.py only writes to docs/third-party")
    doc_path = os.path.join(output_dir, args.filename)
    os.makedirs(output_dir, exist_ok=True)

    header = f"# {args.title}\n\n"
    header += f"Last Updated: {datetime.now().strftime('%Y-%m-%d')}\n\n"
    content = args.content.rstrip() + "\n\n" if args.content.strip() else ""
    sources = "\n".join(f"- {source}" for source in args.source)
    sources_block = f"## Sources\n\n{sources}\n"

    with open(doc_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write(content)
        f.write(sources_block)

    # Index files are not generated outside baseline.
    update_index(args.title, args.filename, args.source, args.purpose, output_dir)
    print(f"Successfully updated {doc_path}")


if __name__ == MAIN_MODULE:
    main()
