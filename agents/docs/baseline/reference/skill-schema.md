# Skill Schema — Reference

Required reads

@~/.teleclaude/docs/baseline/reference/agent-artifacts.md

## What it is

A skill is a reusable knowledge module stored at `skills/<skill-name>/SKILL.md`.
Skills are loaded into context by runtimes when relevant.

## Canonical fields

Frontmatter (YAML):

- `name` (string, required)
  - Skill name, used for display and lookup.
- `description` (string, required)
  - When and why the skill should be applied.
- `version` (string, optional)
  - Semantic version for change tracking.

Body:

- Core instructions for applying the skill.

Optional directories

- `references/` — authoritative specs or longer references.
- `examples/` — runnable or concrete usage examples.
- `scripts/` — helper scripts used by the skill.
- `assets/` — templates or other static files.

## Field intent and authoring rules

- `description` must state **trigger conditions** and **expected outcome**.
  - Good: "Use to draft API specs with strict schema fields."
  - Bad: "Helpful for docs."
- Keep SKILL.md **short and operational**; move detail into `references/`.
- Use imperative language in the body.

## Discovery behavior

- Runtimes scan `skills/` for `SKILL.md` files.
- Frontmatter determines when the skill is eligible for use.

## Known caveats

- Avoid multi-purpose skills; split if the skill has multiple modes.
- Keep examples current; outdated examples reduce trust.
