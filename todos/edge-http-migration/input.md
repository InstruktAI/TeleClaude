# edge-http-migration — Input

Three daemon-internal callers bypass the API edge and call `CommandService.create_session` / `run_slash_command` directly: `integration_bridge.py` (spawns integrator), `events/cartridges/prepare.py` (spawns prepare workers), `hooks/whatsapp_handler.py` (creates WhatsApp sessions). This violates the layer-ownership architecture — `origin_metadata` is never assembled by the edge, identity resolution is skipped.

The fix: all three must call the existing public API endpoints (`POST /sessions/run`, `POST /sessions`) via HTTP instead. The daemon authenticates with its session token. The edge assembles `origin_metadata`. After migration, `run_slash_command` as an in-process method on `CommandService` becomes dead code and is removed.

Parent requirements coverage: R1, R2, R3, R5, R6 from `edge-session-creation`.
