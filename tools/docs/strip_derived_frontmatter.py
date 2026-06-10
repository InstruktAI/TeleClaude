#!/usr/bin/env -S uv run --quiet
"""Strip path-derived snippet classifier fields from docs frontmatter."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import frontmatter

DERIVED_KEYS = frozenset({"id", "type", "scope", "domain"})
DOC_ROOTS = ("docs/global", "docs/project", "docs/third-party")
SKIPPED_FILENAMES = frozenset({"index.md", "index.yaml"})


@dataclass(frozen=True)
class StripResult:
    """One file inspected by the derived-frontmatter stripper."""

    path: Path
    changed: bool


def _has_frontmatter(raw: str) -> bool:
    return raw.lstrip().startswith("---")


def strip_file(path: Path, *, dry_run: bool = False) -> StripResult:
    """Remove derived classifier keys from one Markdown file."""
    raw = path.read_text(encoding="utf-8")
    if not _has_frontmatter(raw):
        return StripResult(path=path, changed=False)
    post = frontmatter.loads(raw)
    metadata = dict(post.metadata or {})
    stripped = {key: value for key, value in metadata.items() if key not in DERIVED_KEYS}
    if stripped == metadata:
        return StripResult(path=path, changed=False)
    rendered = frontmatter.dumps(frontmatter.Post(post.content, **stripped)).rstrip() + "\n"
    if not dry_run:
        path.write_text(rendered, encoding="utf-8")
    return StripResult(path=path, changed=True)


def strip_tree(project_root: Path, *, dry_run: bool = False) -> list[StripResult]:
    """Strip derived fields below all documentation roots."""
    results: list[StripResult] = []
    for rel_root in DOC_ROOTS:
        root = project_root / rel_root
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            if path.name in SKIPPED_FILENAMES:
                continue
            results.append(strip_file(path, dry_run=dry_run))
    return results


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root containing docs/.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if any file would change.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print files that would change without writing them.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    project_root = args.project_root.resolve()
    results = strip_tree(project_root, dry_run=args.dry_run or args.check)
    changed = [result.path for result in results if result.changed]
    for path in changed:
        print(path)
    if args.check and changed:
        return 1
    print(f"Stripped {len(changed)} of {len(results)} docs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
