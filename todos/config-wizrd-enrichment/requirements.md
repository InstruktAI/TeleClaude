# Requirements: config-wizrd-enrichment

## Goal

Enrich the configuration wizard so every env var step includes human-friendly guidance:
step-by-step instructions, clickable links, format examples, and validation hints.
Zero friction — users are told exactly what to do at each step.

## Scope

### In scope:
- Complete GuidanceRegistry with entries for ALL env vars in `_ADAPTER_ENV_VARS`
- Surface guidance inline in the ConfigView TUI when a var is selected (set or unset)
- Add `_ENV_TO_FIELD` mapping dict for env-var-name → field-path lookup
- OSC 8 terminal hyperlinks for URLs with plain-text fallback
- Integrate with guided mode: auto-expand first unset var's guidance when step lands

### Out of scope:
- Guidance for non-env-var config (people, notifications) — separate todo
- Browser-open from the TUI
- Changes to the env var registry itself (`_ADAPTER_ENV_VARS`)
- Changes to config schema or validation logic

## Success Criteria

- [ ] Every env var in `_ADAPTER_ENV_VARS` has a corresponding GuidanceRegistry entry
- [ ] Selecting any env var in the TUI expands guidance inline (steps, URL, format, hint)
- [ ] URLs render as OSC 8 hyperlinks in supported terminals, plain text otherwise
- [ ] Guided mode auto-expands guidance for the first unset var when landing on an adapter step
- [ ] Guidance collapses when cursor moves away from the var
- [ ] All guidance URLs are verified correct and current
- [ ] Existing tests pass; new tests cover guidance lookup and rendering

## Constraints

- Must work within the existing Textual/Rich rendering pipeline
- No external dependencies added
- GuidanceRegistry remains keyed by field path (extensibility); lookup by env var name via mapping dict
- Must not break existing config wizard UX (tab navigation, editing, validation)

## Risks

- OSC 8 support varies across terminals — fallback must be reliable
- Guidance text length could push content off-screen on small terminals — consider truncation
