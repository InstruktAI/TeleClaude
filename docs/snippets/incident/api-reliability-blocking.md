---
id: teleclaude/incident/api-reliability-blocking
type: incident
scope: project
description: Reliability analysis identifying async blocking risks in the REST server path.
requires: []
---

Incident summary
- The REST server can become intermittently unresponsive due to blocking operations inside async paths.

Key findings
- Blocking subprocess.run in next_machine workflow preparation.
- Blocking psutil.cpu_percent calls inside async handlers.
- Synchronous file I/O in async orchestration code.
- Missing SQLite busy_timeout in async DB connections.

Impact
- Event loop stalls under load, causing temporary API unavailability.

Status
- Documented as a reliability risk; mitigation requires async-friendly I/O wrappers.
