#!/usr/bin/env python3
"""Script to manage 3rd-party documentation research results."""

import argparse
import os
from datetime import datetime


from teleclaude.constants import MAIN_MODULE
def update_index(title: str, filename: str, source: str, purpose: str, output_dir: str = "docs/3rd") -> None:
    """Update index.md with the new or updated entry."""
    index_path = os.path.join(output_dir, "index.md")
    today = datetime.now().strftime("%Y-%m-%d")

    if not os.path.exists(index_path):
        content = ["# Third‑Party Documentation Index\n"]
    else:
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.readlines()

    # Find if entry already exists
    entry_start = -1
    for i, line in enumerate(content):
        if line.strip() == f"## {title}":
            entry_start = i
            break

    entry_lines = [
        f"## {title}\n",
        f"- Purpose: {purpose}\n",
        f"- File: `{filename}`\n",
        f"- Source: {source}\n",
        f"- Last Updated: {today}\n",
        "\n",
    ]

    if entry_start != -1:
        # Update existing entry
        # Find the end of the entry (next ## or EOF)
        entry_end = len(content)
        for i in range(entry_start + 1, len(content)):
            if content[i].startswith("## "):
                entry_end = i
                break
        
        content[entry_start:entry_end] = entry_lines
    else:
        # Append new entry
        if content and not content[-1].endswith("\n"):
            content[-1] += "\n"
        content.extend(entry_lines)

    with open(index_path, "w", encoding="utf-8") as f:
        f.writelines(content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage 3rd-party research docs.")
    parser.add_argument("--title", required=True, help="Title of the documentation")
    parser.add_argument("--filename", required=True, help="Target filename in output directory")
    parser.add_argument("--source", required=True, help="Source URL or description")
    parser.add_argument("--purpose", required=True, help="Brief description of what this doc is for")
    parser.add_argument("--content", required=True, help="Concise markdown content")
    parser.add_argument("--output-dir", default="docs/3rd", help="Output directory (default: docs/3rd)")

    args = parser.parse_args()

    # Ensure filename ends with .md
    if not args.filename.endswith(".md"):
        args.filename += ".md"

    # Write the doc file
    output_dir = args.output_dir
    doc_path = os.path.join(output_dir, args.filename)
    os.makedirs(output_dir, exist_ok=True)

    header = f"# {args.title}\n\n"
    header += f"Source: {args.source}\n"
    header += f"Last Updated: {datetime.now().strftime('%Y-%m-%d')}\n\n"

    with open(doc_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write(args.content)

    # Update index
    update_index(args.title, args.filename, args.source, args.purpose, output_dir)
    index_path = os.path.join(output_dir, "index.md")
    print(f"Successfully updated {doc_path} and {index_path}")


if __name__ == MAIN_MODULE:
    main()