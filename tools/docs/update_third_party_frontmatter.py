#!/usr/bin/env python3
"""Ensure third-party docs have stable frontmatter."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import frontmatter

THIRD_PARTY_TYPE = "third-party"
SKIPPED_FILENAMES = frozenset({"index.md"})


@dataclass(frozen=True)
class UpdateResult:
    """Result for one inspected third-party markdown file."""

    path: Path
    changed: bool


def _description_from_body(body: str, fallback: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback.replace("-", " ").replace("_", " ").title()


def _snippet_id_for_path(third_party_root: Path, path: Path) -> str:
    rel = path.relative_to(third_party_root).with_suffix("").as_posix()
    return f"{THIRD_PARTY_TYPE}/{rel}"


def _ordered_metadata(
    original: Mapping[str, object],
    *,
    snippet_id: str,
    scope: str,
    description: str,
) -> Mapping[str, object]:
    required = {
        "id": snippet_id,
        "type": THIRD_PARTY_TYPE,
        "scope": scope,
        "description": description,
    }
    extras = {key: value for key, value in original.items() if key not in required}
    return {**required, **extras}


def _render(content: str, metadata: Mapping[str, object]) -> str:
    post = frontmatter.Post(content, **metadata)
    return frontmatter.dumps(post).rstrip() + "\n"


def update_file(third_party_root: Path, path: Path, *, scope: str, dry_run: bool = False) -> UpdateResult:
    """Update one third-party markdown file in place unless ``dry_run`` is set."""
    raw = path.read_text(encoding="utf-8")
    post = frontmatter.loads(raw)
    metadata = dict(post.metadata or {})
    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        description = _description_from_body(post.content, path.stem)

    updated = _render(
        post.content,
        _ordered_metadata(
            metadata,
            snippet_id=_snippet_id_for_path(third_party_root, path),
            scope=scope,
            description=description.strip(),
        ),
    )
    changed = updated != raw
    if changed and not dry_run:
        path.write_text(updated, encoding="utf-8")
    return UpdateResult(path=path, changed=changed)


def update_tree(third_party_root: Path, *, scope: str, dry_run: bool = False) -> list[UpdateResult]:
    """Update all third-party markdown files below ``third_party_root``."""
    if not third_party_root.exists():
        raise FileNotFoundError(f"third-party docs root does not exist: {third_party_root}")
    if not third_party_root.is_dir():
        raise NotADirectoryError(f"third-party docs root is not a directory: {third_party_root}")

    results: list[UpdateResult] = []
    for path in sorted(third_party_root.rglob("*.md")):
        if path.name in SKIPPED_FILENAMES:
            continue
        results.append(update_file(third_party_root, path, scope=scope, dry_run=dry_run))
    return results


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "third_party_root",
        nargs="?",
        default="docs/third-party",
        type=Path,
        help="Path to the third-party docs root.",
    )
    parser.add_argument(
        "--scope",
        choices=("project", "global"),
        default="project",
        help="Frontmatter scope value to write.",
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    results = update_tree(args.third_party_root, scope=args.scope, dry_run=args.dry_run or args.check)
    changed = [result.path for result in results if result.changed]
    for path in changed:
        print(path)
    if args.check and changed:
        return 1
    print(f"Updated {len(changed)} of {len(results)} third-party docs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
