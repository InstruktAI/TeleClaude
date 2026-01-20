---
id: teleclaude/architecture/output-polling
type: architecture
scope: project
description: Output polling pipeline that captures tmux output and streams updates to adapters.
requires:
  - tmux-management.md
  - adapter-client.md
---

Purpose
- Stream tmux output to UI adapters while maintaining process lifecycle signals.

Inputs/Outputs
- Inputs: tmux pane capture snapshots and session metadata.
- Outputs: OutputChanged, ProcessExited, and DirectoryChanged events routed to adapters.

Primary flows
- OutputPoller compares successive captures and emits change events.
- Polling coordinator sends output updates through AdapterClient.
- Process exit triggers a final output update and optional session cleanup.

Invariants
- Output polling stops when the tmux session no longer exists.
- Output updates are edited into a single persistent message per UI session.

Failure modes
- Missing sessions abort polling and log a warning.
