# Input: event-alpha-container

Phase 5 of the event processing platform. Full vision is in `todos/event-platform/input.md`.

This sub-todo delivers sandboxed execution for experimental cartridges: a long-running Docker
sidecar that runs alpha cartridges in isolation (read-only, no-network, capped resources)
after the approved pipeline has completed. Communication over a Unix socket. Zero overhead
when no alpha cartridges exist. Promotion path: alpha cartridge passes validation → moved
from the alpha mount into the codebase → runs in-process as an approved cartridge.

See `todos/event-platform/implementation-plan.md` → Phase 5 for the high-level scope.
