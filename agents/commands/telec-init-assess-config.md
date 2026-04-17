---
description: 'Assess project quality tool configuration against blessed templates during telec init'
---

# Telec Init Assess Config

You are now the quality configuration assessor.

## Purpose

Compare the project's quality tool configuration against TeleClaude's blessed
templates and produce a coverage report with actionable recommendations. This
command is invoked by `telec init` alongside the doc snippet analysis.

## Inputs

- The current working directory is the project root.
- `teleclaude.yml` contains `languages` and optionally `frontend_root`.
- Templates live under `templates/quality/{language}/` in the TeleClaude repo.

## Steps

1. Read `teleclaude.yml` to get `languages` and `frontend_root`.
2. For each declared language, read the project's tool configs:
   - **Python**: `pyproject.toml` sections for ruff, pyright, mypy, guardrails.
   - **TypeScript**: `tsconfig.json`, `eslint.config.mjs`, `.prettierrc`, `vitest.config.ts`
     (all relative to `frontend_root`).
3. Read the blessed templates from `templates/quality/{language}/`.
4. Compare semantically — coverage analysis, not file diff:
   - Which rules/sections are present vs missing?
   - Is strict mode enabled (pyright, tsconfig)?
   - Are key safety settings active?
5. Report findings with specific recommendations.
6. If the user approves via session interaction: apply the recommended changes.

## Output Format

```
## Config Assessment: {language}

### Present
- [list of rules/sections that match template]

### Missing or Weaker
- [list of rules/sections absent or weaker than template]

### Recommendations
- [actionable items]
```

## Constraints

- Do not silently modify configuration files.
- Present findings before applying any changes.
- Focus on safety-impacting settings (strict mode, type checking, lint rules).
