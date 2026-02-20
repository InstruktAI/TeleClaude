# Python Development Standards — Consolidation

## Pattern

Three separate memories address Python development practices but are scattered:

1. **Module docstrings must be substantive** (Feb 8) — Every module needs proper docstrings explaining purpose, inputs, outputs, integration
2. **Use uv and pyproject.toml for ALL deps** (Feb 10) — Never use pip directly; manage all dependencies through pyproject.toml
3. Implied in governance: substantive documentation is a baseline expectation

## Contradiction/Gap

While `software-development/policy/python/core` exists, it may not adequately cover:

- **Module docstring requirements** — What constitutes "substantive"?
- **Dependency management workflow** — How should AIs add new dependencies?
- **Pyproject.toml structure** — Which optional groups to use for different contexts?

The frustration keeps resurfacing because these are workflow/expectation issues, not code-quality issues. They feel like paper cuts rather than real mistakes.

## Actionable Insight

Create a **Python development workflow checklist** or append to existing policy that covers:

- Module docstring template with clear examples of what NOT to do (one-liners)
- Dependency addition workflow: check existing in pyproject.toml, add to optional group, use `uv sync`
- Pre-commit hooks that enforce substantive docstrings (rather than relying on manual code review)

## Next Steps

- Review `software-development/policy/python/core` scope
- Decide: enhance existing policy or create a separate "python-development-workflow" spec
- Add pre-commit linting for docstring quality (pylint `missing-module-docstring`, similar)
