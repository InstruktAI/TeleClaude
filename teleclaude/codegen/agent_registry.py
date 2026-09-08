"""Generate frontend agent-registry artifacts from ``teleclaude.agent_registry``.

Emits a generated TypeScript module (canonical agent names in stable order,
per-agent color tiers, and a registry revision digest) and generated
light/dark CSS custom properties for the same tiers. Both derive from the
same canonical per-agent records; neither is ever hand-edited — a change to
an agent's presentation happens once, in ``teleclaude/agent_registry.py``.

The exported ``AgentName`` *type* is not re-declared here: it is already
generated from the Python enum by ``codegen.pydantic_to_typescript`` into
``frontend/lib/api/generated-types.ts``, and this module's TypeScript output
imports it from there rather than creating a second declaration.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from teleclaude.agent_registry import AGENT_REGISTRY, AgentName, PaletteTiers, registry_digest

_TS_HEADER_LINES: tuple[str, ...] = (
    "/**",
    " * Auto-generated from teleclaude.agent_registry.",
    " * Do not edit by hand.",
    " */",
)
_CSS_HEADER_LINES: tuple[str, ...] = (
    "/* -----------------------------------------------------------------------",
    " * Auto-generated from teleclaude.agent_registry.",
    " * Do not edit by hand. Frontend-only tokens (e.g. haze) stay in tokens.css.",
    " * -------------------------------------------------------------------- */",
)
_DEFAULT_TS_OUTPUT_PATH = Path("frontend/lib/api/generated-agent-registry.ts")
_DEFAULT_CSS_OUTPUT_PATH = Path("frontend/lib/theme/generated-agent-tokens.css")
_TIER_ORDER: tuple[str, ...] = ("subtle", "muted", "normal", "highlight")


def _tier_object(tiers: PaletteTiers) -> str:
    fields = ", ".join(f"{tier}: '{getattr(tiers, tier)}'" for tier in _TIER_ORDER)
    return f"{{ {fields} }}"


def generate_typescript() -> str:
    """Return the generated TypeScript module source."""
    agent_names = ", ".join(f"'{name.value}'" for name in AgentName)
    palette_entries = "\n".join(
        f"  {name.value}: {{ dark: {_tier_object(AGENT_REGISTRY[name].palette.dark)},"
        f" light: {_tier_object(AGENT_REGISTRY[name].palette.light)} }},"
        for name in AgentName
    )
    lines = [
        *_TS_HEADER_LINES,
        "",
        "import type { AgentName } from './generated-types';",
        "",
        "export interface AgentColorTiers {",
        "  readonly subtle: string;",
        "  readonly muted: string;",
        "  readonly normal: string;",
        "  readonly highlight: string;",
        "}",
        "",
        "export interface AgentThemeTiers {",
        "  readonly dark: AgentColorTiers;",
        "  readonly light: AgentColorTiers;",
        "}",
        "",
        f"export const AGENT_NAMES: readonly AgentName[] = [{agent_names}];",
        "",
        f"export const AGENT_REGISTRY_REVISION = '{registry_digest()}';",
        "",
        "export const AGENT_PALETTE: Record<AgentName, AgentThemeTiers> = {",
        palette_entries,
        "};",
    ]
    return "\n".join(lines).rstrip() + "\n"


def generate_css() -> str:
    """Return the generated light/dark CSS custom-property block."""

    def block(theme: str) -> list[str]:
        lines: list[str] = []
        for name in AgentName:
            tiers = getattr(AGENT_REGISTRY[name].palette, theme)
            lines.append(f"  /* -- Agents ({name.value}) -- */")
            for tier in _TIER_ORDER:
                lines.append(f"  --tc-agent-{name.value}-{tier}: {getattr(tiers, tier)};")
        return lines

    lines = [
        *_CSS_HEADER_LINES,
        "",
        ":root {",
        *block("light"),
        "}",
        "",
        ".dark {",
        *block("dark"),
        "}",
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_generated_files(
    ts_path: Path = _DEFAULT_TS_OUTPUT_PATH,
    css_path: Path = _DEFAULT_CSS_OUTPUT_PATH,
) -> None:
    """Write both generated artifacts to disk."""
    ts_path.parent.mkdir(parents=True, exist_ok=True)
    ts_path.write_text(generate_typescript(), encoding="utf-8")
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(generate_css(), encoding="utf-8")


def print_canonical_list() -> None:
    """Print each canonical agent key on its own line — the shell-consumable membership export.

    The deterministic completeness check ``bin/install.sh`` and
    ``src/Launcher/build.sh`` compare their own hand-listed agents against:
    an unhandled canonical definition fails loudly instead of silently
    omitting the new agent.
    """
    for name in AgentName:
        print(name.value)


def main(argv: Sequence[str] | None = None) -> int:
    """Write generated agent-registry artifacts, or print the canonical list with `--list`."""
    args = list(argv) if argv is not None else sys.argv[1:]
    if args and args[0] == "--list":
        print_canonical_list()
        return 0
    ts_path = Path(args[0]) if len(args) > 0 else _DEFAULT_TS_OUTPUT_PATH
    css_path = Path(args[1]) if len(args) > 1 else _DEFAULT_CSS_OUTPUT_PATH
    write_generated_files(ts_path, css_path)
    print(f"Agent registry TypeScript written to {ts_path}")
    print(f"Agent registry CSS written to {css_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
