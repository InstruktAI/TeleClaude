"""Resolve or discard the machine's kept project declaration answers."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.capabilities import (
    DeclarationUnreadable,
    read_declaration_view,
)
from teleclaude.config.declaration_views import (
    discard_declaration_views,
    entry_path_for_root,
    entry_text,
    publish_entry,
    read_epoch,
)
from teleclaude.config.schema import ConfigKind

logger = get_logger(__name__)
_TRIGGER_CHOICES = ("maintenance", "install")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve the runtime declaration view.")
    commands = parser.add_subparsers(dest="command", required=True)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("root", type=Path)
    resolve.add_argument("entry_path", type=Path)
    discard = commands.add_parser("discard")
    discard.add_argument("--trigger", required=True, choices=_TRIGGER_CHOICES)
    return parser


def main() -> int:
    """Serve one shell resolution or installation-owned discard request."""
    arguments = _build_parser().parse_args()
    if arguments.command == "discard":
        discard_declaration_views(arguments.trigger)
        logger.info("declaration_views_discarded", trigger=arguments.trigger)
        return 0

    root: Path = arguments.root.expanduser().resolve()
    entry_path: Path = arguments.entry_path.expanduser().resolve()
    if entry_path != entry_path_for_root(root):
        print("declaration view entry path does not match its root", file=sys.stderr)
        return 1
    epoch = read_epoch()
    try:
        view = read_declaration_view(root)
    except DeclarationUnreadable as error:
        generation = uuid4().hex
        print(f"{generation}\n!{error.reason}\n")
        logger.info(
            "declaration_view_resolved",
            document_key=_document_key(root / "teleclaude.yml"),
            kind=None,
            code=None,
            docs=None,
            agents=None,
            environment_read=False,
            outcome="refused",
            kept=False,
            reason=error.reason,
        )
        return 0
    except Exception as error:
        print(f"declaration view resolution failed: {error}", file=sys.stderr)
        return 1

    generation = uuid4().hex
    text = entry_text(view, generation)
    print(text, end="")
    try:
        kept = publish_entry(entry_path, view, view.dependencies, epoch, generation=generation)
    except Exception as error:
        print(f"declaration view publication failed: {error}", file=sys.stderr)
        kept = False
    logger.info(
        "declaration_view_resolved",
        document_key=_document_key(root / "teleclaude.yml"),
        kind=view.kind.value if isinstance(view.kind, ConfigKind) else None,
        code=view.capabilities.code if view.capabilities.is_target else None,
        docs=view.capabilities.docs if view.capabilities.is_target else None,
        agents=view.capabilities.agents if view.capabilities.is_target else None,
        environment_read=view.environment_read,
        outcome="resolved",
        kept=kept,
        reason=None,
    )
    return 0


def _document_key(path: Path) -> str:
    """Hash a resolved declaration path for privacy-safe operational records."""
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
