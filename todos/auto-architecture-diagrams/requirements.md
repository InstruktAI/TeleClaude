# Requirements: auto-architecture-diagrams

## Goal

Generate architecture diagrams directly from code so the human operator can visually navigate the system at any time without maintaining separate documentation. A single `make diagrams` target produces 6 Mermaid files that reflect the current codebase truth.

## Scope

### In scope:

- Python extraction scripts using `ast` module to parse enums, dataclasses, imports, and SQLModel classes
- Mermaid output format (.mmd files) renderable by GitHub, IDE plugins, and CLI tools
- `make diagrams` target that regenerates all diagrams from source
- Six diagram types:
  1. **Work item lifecycle** — roadmap states (pending/ready/in-progress/done) + build/review phase transitions from `core/next_machine/core.py`
  2. **Event flow** — hook events per runtime (Claude/Gemini/Codex) → internal events → handlers → side effects from `core/events.py`, `core/agent_coordinator.py`
  3. **Data model** — ERD from SQLModel classes in `core/db_models.py`
  4. **Module layers** — import graph across `core/`, `hooks/`, `mcp/`, `cli/`, `api/`, `adapters/` from actual import statements
  5. **Command dispatch** — next-prepare → next-work orchestration cycle from `agents/commands/*.md` frontmatter
  6. **Runtime matrix** — per-agent feature support (hooks, blocking, transcript format) from `core/events.py` HOOK_EVENT_MAP and adapter files

### Out of scope:

- Interactive/web-based diagram viewers
- Diagram diffing or change detection
- CI integration (can be added later)
- Non-Mermaid output formats
- Documenting intent/rationale (that stays in prose docs)

## Success Criteria

- [ ] `make diagrams` produces 6 .mmd files in `docs/diagrams/` from code parsing alone
- [ ] Each diagram is viewable in GitHub markdown preview and VS Code Mermaid plugin
- [ ] Diagrams reflect actual code state — verified by spot-checking against known structures
- [ ] No manual maintenance required — diagrams are regenerated, never hand-edited
- [ ] Extraction scripts have no dependencies beyond Python stdlib (`ast`, `pathlib`, `re`, `json`)

## Constraints

- Zero external dependencies for extraction (stdlib only)
- Output must be valid Mermaid syntax
- Scripts must run in < 5 seconds total
- `docs/diagrams/` is gitignored (generated artifacts, regenerated on demand)

## Risks

- Next machine state transitions are implicit in control flow, not declarative — extraction may need heuristic branch parsing or a hand-maintained mapping that the script validates against code
- Module dependency graph may be noisy at fine granularity — need to decide on the right abstraction level (package vs module vs class)
