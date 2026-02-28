# Input: event-domain-infrastructure

Phase 3 of the event-platform. After the system pipeline classifies an event, domain pipelines
take over: each domain runs its own cartridge stack in parallel, scoped to its folder hierarchy
(`~/.teleclaude/company/`, `~/.teleclaude/personal/`, `~/.teleclaude/helpdesk/`).

Core concerns: cartridge DAG loading with topological sort, parallel execution per domain,
personal subscription micro-cartridges per member, autonomy matrix per
`event_type > cartridge > domain > global`, and lifecycle ops (install, remove, promote).
Admin vs member scope enforcement throughout. `telec config` integration for autonomy management.
