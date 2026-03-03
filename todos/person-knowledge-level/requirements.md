# Requirements: person-knowledge-level

## Goal

Add a `knowledge` field to `PersonEntry` so agents know the human's knowledge level
at session start and derive all behavioral calibration from it.

## Scope

### In scope

1. **Schema**: Add `knowledge: Literal["novice", "intermediate", "advanced", "expert"]`
   to `PersonEntry` with default `"intermediate"`.
2. **Session injection**: Extend `_print_memory_injection()` in `receiver.py` to look up
   the person by `human_email` from global config and prepend a knowledge line
   (`Human in the loop: {name} ({knowledge})`) to the memory context injected at
   `AGENT_SESSION_START`.
3. **CLI**: Add `--knowledge` flag to `telec config people add` and `telec config people edit`.
4. **API DTO**: Add `knowledge` field to `PersonDTO`.
5. **TUI wizard**: Display the knowledge level alongside name and role in the config
   wizard's people tab. Add `knowledge` to the `PersonInfo` dataclass used for JSON output.
6. **Tests**: Unit tests for schema validation, CLI flag handling, injection output.

### Out of scope

- Behavioral directive tables mapping knowledge to specific agent behaviors (the agent
  infers behavior from the word itself — it's a language model).
- Per-session knowledge override (knowledge is a static person attribute).
- Migration tooling for existing configs (default covers existing entries).

## Success Criteria

- [ ] `PersonEntry(name="X", email="x@y.com", knowledge="expert")` validates; invalid
      values like `knowledge="guru"` raise `ValidationError`.
- [ ] At `AGENT_SESSION_START`, when the session has a `human_email` matching a configured
      person with `knowledge: expert`, the injected context begins with
      `Human in the loop: X (expert)`.
- [ ] When no person matches or no `human_email` is set, injection behaves exactly as
      before (no knowledge line, no error).
- [ ] `telec config people add --name X --email x@y.com --knowledge expert` creates a
      person with `knowledge: expert`.
- [ ] `telec config people edit X --knowledge novice` updates the knowledge field.
- [ ] `telec config people list --json` includes `"knowledge"` in output.
- [ ] `PersonDTO` serializes the knowledge field in API responses.
- [ ] The TUI config wizard people tab shows the knowledge level per person.

## Constraints

- The injection must not break when `PersonEntry` objects from existing configs lack the
  `knowledge` field (Pydantic default handles this).
- The injection happens in the hook receiver's sync path — no async calls, no new DB
  queries beyond what already exists.
- The person lookup uses the already-imported `config.people` list — no new module
  dependencies in receiver.py.

## Risks

- Negligible. All changes are additive with safe defaults. The `PersonEntry` default
  of `"intermediate"` means existing configs validate without modification.
