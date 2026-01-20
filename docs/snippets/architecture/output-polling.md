---
id: architecture/output-polling
description: Output polling pipeline that captures tmux output and streams updates to UI adapters.
type: architecture
scope: project
requires:
  - tmux-management.md
  - adapter-client.md
---

# Output Polling

## Purpose
- Continuously capture tmux output and deliver updates to UI adapters.

## Inputs/Outputs
- Inputs: tmux session name, output file path, poll interval, directory check interval.
- Outputs: OutputChanged, ProcessExited, and DirectoryChanged events; UI output updates.

## Invariants
- Only one poller per session is active at a time (guarded in-memory).
- Output updates are emitted only when content changes, but at least once before exit.
- Directory changes update session project/subdir and can trigger title updates.

## Primary Flows
- Poller reads pane output, detects changes, and writes latest output to file.
- Coordinator consumes events and calls adapter_client.send_output_update.
- Process exit results in final output update and session cleanup as needed.

## Failure Modes
- Disappearing tmux sessions emit exit events; coordinator handles cleanup.
- Output file write failures are logged but do not stop polling.
