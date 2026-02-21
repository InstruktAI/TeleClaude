# Requirements: tui-todo-dependencies

## Goal

Display todo dependency relationships (`after`) and group labels (`group`) in the TUI Preparation view, matching the information already shown by `telec roadmap`.

## Scope

### In scope:

- Thread `after` and `group` fields from `roadmap.yaml` through the full data pipeline to the TUI
- Display dependency arrows (e.g. `<- slug1, slug2`) on todo rows in the Preparation view
- Display group sub-headers when todos belong to named groups

### Out of scope:

- Interactive dependency graph or visualization
- Editing dependencies from the TUI
- Dependency validation or cycle detection (already handled by `load_roadmap()`)

## Success Criteria

- [ ] `curl /todos` API response includes `after` and `group` fields for each todo
- [ ] TUI Preparation view shows dimmed dependency suffix (e.g. `<- slug1, slug2`) after property columns on todo rows that have dependencies
- [ ] TUI Preparation view shows group sub-headers between groups within a project
- [ ] Display matches `telec roadmap` CLI output in terms of information shown
- [ ] Existing tests pass; no regressions in cache, API, or MCP tests

## Constraints

- Do not modify `roadmap.yaml` parsing (`load_roadmap()`) - it already works correctly
- Do not modify `telec roadmap` CLI - it already works correctly
- Follow existing dataclass/DTO patterns for field additions
- TUI changes must be hot-reloadable via SIGUSR2

## Risks

- Cache stores `TodoInfo` objects; adding fields to the dataclass must be backward-compatible with existing cached data (defaulting to empty list / None)
