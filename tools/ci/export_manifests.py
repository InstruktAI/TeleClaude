"""Replace manifest-generation steps in release.yaml."""

from __future__ import annotations

import argparse

from teleclaude.cli.telec.surface import export_surface_markdown
from teleclaude.config.schema_export import export_config_markdown
from teleclaude.events.schema_export import export_events_markdown
from tools.ci.gha import repo_root

CLI_MANIFEST = "cli-surface.md"
CONFIG_MANIFEST = "config.md"
DESCRIPTION = "Generate release manifests."
EVENTS_MANIFEST = "events.md"
MANIFEST_DIRECTORY = "manifests"
NEWLINE = "\n"


def write_manifest(name: str, content: str) -> None:
    """Write one generated manifest using the shell print newline contract."""
    destination = repo_root() / MANIFEST_DIRECTORY / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content + NEWLINE, encoding="utf-8")


def export_manifests() -> None:
    """Generate all manifests used by release analysis and tagging."""
    write_manifest(CLI_MANIFEST, export_surface_markdown())
    write_manifest(EVENTS_MANIFEST, export_events_markdown())
    write_manifest(CONFIG_MANIFEST, export_config_markdown())


def main(argv: list[str] | None = None) -> int:
    """Generate the current release manifest set."""
    argparse.ArgumentParser(description=DESCRIPTION).parse_args(argv)
    export_manifests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
