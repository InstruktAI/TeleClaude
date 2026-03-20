# state-machine-adoption — Input

Complete the v1->v2 state model migration across all remaining consumers.
Split from the parent `state-machine-versioning` because the full scope
exceeds a single builder session.

This child depends on `state-machine-core` which delivers the engine,
migration, CLI/API surface, and initial prepare/readiness adoption.

This child delivers: work.py dispatch migration, mark-* consolidation into
transition wrappers, ghost artifact protection removal, Pydantic/DTO model
updates, display layer updates (TUI, roadmap, output formatting), resource
validation updates, agent artifact/help text migration, and NFR-1 codebase
enforcement.

The integration module (`teleclaude/core/integration/`) is explicitly excluded
— it already has its own working state machine and does not use the
bag-of-fields model.

See parent `todos/state-machine-versioning/input.md` for the full problem
statement and motivation.
