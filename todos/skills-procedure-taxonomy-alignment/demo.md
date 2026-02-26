# Demo Plan (Draft): skills-procedure-taxonomy-alignment

## Medium

CLI + repository diff review.

## What the reviewer should observe

1. A taxonomy source-of-truth doc defines exploratory skill boundaries for this todo.
2. Procedure docs exist for each in-scope exploratory skill.
3. In-scope `SKILL.md` files are wrapper-style and reference procedure docs via `## Required reads`.
4. Skill validation and distribution-related tests pass.

## Suggested demo steps

1. Show taxonomy and procedure docs:

```bash
rg --files docs/global/software-development | rg "concept|procedure"
```

2. Show wrapper references:

```bash
rg -n "^## Required reads|^# " agents/skills/*/SKILL.md
```

3. Run sync and validation:

```bash
telec sync
python -m pytest tests/unit/test_resource_validation.py -k skill
python -m pytest tests/unit/test_distribute_local_codex.py
```

## Acceptance signal

- The commands above complete without errors and the wrapper/procedure mapping is visible in source.
