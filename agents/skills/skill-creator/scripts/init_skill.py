#!/usr/bin/env python3
"""
Skill Initializer — scaffolds a new skill following the agent-artifact schema.

Usage:
    init_skill.py <skill-name> [--path <path>]

Defaults to agents/skills/ in the current working directory if --path is omitted.

Examples:
    init_skill.py my-new-skill
    init_skill.py my-new-skill --path agents/skills
    init_skill.py my-new-skill --path /absolute/path/to/skills
"""

import sys
from pathlib import Path

SKILL_TEMPLATE = """---
name: {skill_name}
description: TODO — describe what this skill does and when to use it.
---

# {skill_title}

## Required reads

- @~/.teleclaude/docs/TODO-reference-the-doc-snippet-this-skill-wraps.md

## Purpose

TODO — one or two sentences on what this skill achieves.

## Scope

TODO — when and where to apply this skill.

## Inputs

TODO — what the skill needs to start.

## Outputs

TODO — what the skill produces.

## Procedure

Follow the procedure in the required reads above.
"""


def title_case(name: str) -> str:
    return " ".join(word.capitalize() for word in name.split("-"))


def init_skill(skill_name: str, path: str) -> Path | None:
    skill_dir = Path(path).resolve() / skill_name

    if skill_dir.exists():
        print(f"Error: {skill_dir} already exists")
        return None

    try:
        skill_dir.mkdir(parents=True, exist_ok=False)
    except Exception as e:
        print(f"Error creating directory: {e}")
        return None

    content = SKILL_TEMPLATE.format(
        skill_name=skill_name,
        skill_title=title_case(skill_name),
    )
    (skill_dir / "SKILL.md").write_text(content)
    print(f"Created {skill_dir}/SKILL.md")

    print(f"\nSkill '{skill_name}' initialized at {skill_dir}")
    print("\nNext steps:")
    print("1. Replace TODO placeholders in SKILL.md")
    print("2. Point Required reads at the doc snippet this skill wraps")
    print("3. Add scripts/ only if deterministic tooling is needed")
    print("4. Run telec sync to compile and deploy")
    return skill_dir


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: init_skill.py <skill-name> [--path <path>]")
        sys.exit(1)

    skill_name = sys.argv[1]
    path = "agents/skills"

    if "--path" in sys.argv:
        idx = sys.argv.index("--path")
        if idx + 1 < len(sys.argv):
            path = sys.argv[idx + 1]

    result = init_skill(skill_name, path)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
