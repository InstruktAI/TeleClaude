---
description: Where an agent finds what the service process was doing when a request stalled or its event loop lagged — one hang dump per watch firing, complete, named in the daemon log, durable once written and bounded on disk.
delivered_by:
  - api-hang-dumps-show-where-requests-wait
---

# Request Stall Diagnostics — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

The service process watches its own request surface. When a request stays in
flight past the watch's in-flight threshold, or the event loop lags past the
watch's lag threshold (the `api.watch_*` keys in
`local/projects/teleclaude/spec/teleclaude-config`), the watch writes a hang
dump. An agent investigating a stall afterwards reads from it where each overdue
request was waiting, using the daemon log and ordinary file reads.

## Canonical fields

### The log record

Each dump is announced by one error record in the daemon log. The record carries
the reason the watch fired and the path of the dump's file, and stays within the
log's message cap: the dump itself never travels in a log message. A dump that
cannot be written is logged as an error with its cause, and the watch keeps
running.

### The dump file

Each dump is a file of its own and holds:

- the reason, the time, the process, and every overdue request with its method,
  path and age;
- the complete stack of every thread in the process, under the thread's name;
- the await chain of every pending event-loop task, from the task's coroutine to
  the object it waits on, with each task that serves an overdue request
  labelled with that request.

A dump file appears under its final name only once it is complete and on disk,
and the log record is written after that. A forced kill or machine reset after
the record therefore keeps the dump.

### Frequency and retention

Dumps are spaced by the watch's cooldown. Only the newest dumps are kept, and
older ones are deleted as new ones are written, so a long stall stays bounded on
disk. A log record can name a dump that has since been deleted.

## Known caveats

- A dump triggered by loop lag shows the loop after it resumed. The watch runs
  on the loop it watches, so it never captures the frame that blocked the loop.
- A dump records code locations, thread names, task names and the types of
  awaited objects. It records no variable values and no request content.
