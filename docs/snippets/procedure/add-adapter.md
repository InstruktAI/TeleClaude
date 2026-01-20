---
id: teleclaude/procedure/add-adapter
type: procedure
scope: project
description: Steps to add a new adapter implementation and wire it into the daemon.
requires:
  - ../concept/adapter-types.md
---

Steps
1) Create a new adapter class inheriting BaseAdapter (and UiAdapter or RemoteExecutionProtocol as needed).
2) Implement start/stop and the required messaging or transport methods.
3) Add configuration keys to config.sample.yml.
4) Register the adapter in AdapterClient.start() based on config.
5) Add tests to validate routing and adapter behavior.

Outputs
- Adapter is discoverable, starts successfully, and routes through AdapterClient.
