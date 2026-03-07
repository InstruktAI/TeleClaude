# Breakdown: proficiency-to-expertise

## Assessment

**Splitting required.** The work spans 15+ files across 5 distinct subsystems (schema,
hooks, CLI, TUI, and doc artifacts). Each subsystem has its own test suite and can be
delivered independently once the schema foundation exists.

Delivering as a single todo would exhaust session context — the touchpoint matrix alone
covers schema validation, API DTOs, config serialization, hook injection, CLI flags,
TUI editing patterns, guided wizard steps, and behavioral template refactoring.

The natural dependency seam is clear: everything depends on the Pydantic schema model.
Once that lands, injection, CLI, and TUI can proceed in parallel.

## Sub-todos

| Slug | Scope | Depends on |
|------|-------|------------|
| `proficiency-to-expertise-schema` | Pydantic expertise model, API DTO, config handler serialization, migration/backward compat, schema tests | — |
| `proficiency-to-expertise-injection` | Hook receiver rendering, behavioral templates, injection tests, AGENTS.md refactoring | schema |
| `proficiency-to-expertise-cli` | CLI add/edit/list expertise flags, PersonInfo dataclass, CLI tests | schema |
| `proficiency-to-expertise-tui` | TUI wizard, display, editing, guidance for expertise fields | schema |

## Dependency graph

```
proficiency-to-expertise-schema
  ├── proficiency-to-expertise-injection
  ├── proficiency-to-expertise-cli
  └── proficiency-to-expertise-tui
```

After schema lands, injection/CLI/TUI can run in parallel — no inter-dependencies
between them.

## DOR Gate Assessment (parent)

| Gate | Status | Evidence |
|------|--------|----------|
| 1. Intent & success | Pass | Clear problem statement with concrete schema, injection, and UI changes |
| 2. Scope & size | Fail → split | 15+ files, 5 subsystems — too large for one session |
| 3. Verification | Pass (per child) | Tests identified per subsystem |
| 4. Approach known | Pass | Input.md has exact file paths, line numbers, and implementation approach |
| 5. Research complete | Auto-pass | No new third-party dependencies |
| 6. Dependencies | Pass | No external blockers; ruamel serialization bug is not tracked and may be resolved |
| 7. Integration safety | Pass | Schema first, then parallel consumers — each child is independently mergeable |
| 8. Tooling impact | Pass | Config wizard updates explicitly scoped to TUI child |

**Score: 8 / 10** — Status: **pass** (after splitting)

The parent todo is now a tracking container. Work proceeds through the four children.
