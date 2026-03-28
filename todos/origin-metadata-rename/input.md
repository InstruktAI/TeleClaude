# origin-metadata-rename — Input

Complete the naming convergence from `channel_metadata` to `origin_metadata` throughout the command pipeline, as documented in the layer-ownership architecture. The per-request payload carrying platform-specific identity signals is `channel_metadata` in adapters, transport, and fanout, but `origin_metadata` in the session model and API layer. The codebase must use a single consistent name.

`channel_metadata` is not dead code — it is the active data path for actor extraction in `CommandMapper._extract_actor`, Telegram adapter message dispatch, Redis transport metadata serialization, and fanout reflection metadata. The rename must preserve all behavioral contracts across these paths.

Depends on: `edge-http-migration` (HTTP callers migrated first).
Parent requirements coverage: R4, R5 (rename-specific behavioral preservation) from `edge-session-creation`.
