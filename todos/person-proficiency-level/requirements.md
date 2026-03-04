# Requirements: person-proficiency-level

## Goal

Add a `proficiency` field to `PersonEntry` so agents know the human's proficiency level
at session start and derive all behavioral calibration from it.

## Scope

### In scope

1. **Schema**: Add `proficiency: Literal["novice", "intermediate", "advanced", "expert"]`
   to `PersonEntry` with default `"intermediate"`.
2. **Session injection**: Extend `_print_memory_injection()` in `receiver.py` to look up
   the person by `human_email` from global config and prepend a proficiency line
   (`Human in the loop: {name} ({proficiency})`) to the memory context injected at
   `AGENT_SESSION_START`.
3. **CLI**: Add `--proficiency` flag to `telec config people add` and `telec config people edit`.
4. **API DTO**: Add `proficiency` field to `PersonDTO`.
5. **TUI wizard**: Display the proficiency level alongside name and role in the config
   wizard's people tab. Add `proficiency` to the `PersonInfo` dataclass used for JSON output.
6. **Tests**: Unit tests for schema validation, CLI flag handling, injection output.

### Out of scope

- Behavioral directive tables mapping proficiency to specific agent behaviors (the agent
  infers behavior from the word itself — it's a language model).
- Per-session proficiency override (proficiency is a static person attribute).
- Migration tooling for existing configs (default covers existing entries).

## Success Criteria

- [ ] `PersonEntry(name="X", email="x@y.com", proficiency="expert")` validates; invalid
      values like `proficiency="guru"` raise `ValidationError`.
- [ ] At `AGENT_SESSION_START`, when the session has a `human_email` matching a configured
      person with `proficiency: expert`, the injected context begins with
      `Human in the loop: X (expert)`.
- [ ] When no person matches or no `human_email` is set, injection behaves exactly as
      before (no proficiency line, no error).
- [ ] `telec config people add --name X --email x@y.com --proficiency expert` creates a
      person with `proficiency: expert`.
- [ ] `telec config people edit X --proficiency novice` updates the proficiency field.
- [ ] `telec config people list --json` includes `"proficiency"` in output.
- [ ] `PersonDTO` serializes the proficiency field in API responses.
- [ ] The TUI config wizard people tab shows the proficiency level per person.

## Constraints

- The injection must not break when `PersonEntry` objects from existing configs lack the
  `proficiency` field (Pydantic default handles this).
- The injection happens in the hook receiver's sync path — no async calls, no new DB
  queries beyond what already exists.
- The person lookup uses the already-imported `config.people` list — no new module
  dependencies in receiver.py.

## Risks

- Negligible. All changes are additive with safe defaults. The `PersonEntry` default
  of `"intermediate"` means existing configs validate without modification.
