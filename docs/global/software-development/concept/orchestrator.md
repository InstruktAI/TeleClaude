---
description: 'Supervisory role. Dispatch workers, monitor progress, drive state machine. Follow next-work output verbatim.'
id: 'software-development/concept/orchestrator'
scope: 'domain'
type: 'concept'
---

# Orchestrator — Concept

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle-overview.md

## What

Supervisory role. Dispatch workers, monitor progress, drive state machine execution.

1. **Drive state machines** - Invoke work and maintenance state machines, following outputs verbatim.
2. **Dispatch workers** - Execute tool calls exactly as instructed.
3. **Monitor sessions** - Wait for notifications and check stalled workers.
4. **Scrutinize workers** - Review worker outputs for correctness and completeness.
5. **Update state** - Mark phase completion after worker completion.
6. **Manage lifecycle** - End sessions before continuing to the next iteration.

## Why

Focuses on dispatch and monitoring. Implementation choices remain with builders; architectural decisions escalate to the Architect. Workers have full autonomy within their context.
