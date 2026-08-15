---
description: Upstream capabilities, lifecycle, persistence, and security characteristics of yctimlin/mcp_excalidraw.
---

# MCP Excalidraw

## Upstream shape

`yctimlin/mcp_excalidraw` is an MIT-licensed Excalidraw toolkit published as
the `mcp-excalidraw-server` npm package. The package on the upstream `main`
branch declares version `2.0.0` and Node.js `>=20.0.0`, while npm currently
publishes versions only through `1.1.0`, whose package metadata requires
Node.js `>=18.0.0`. The GitHub repository does not currently publish GitHub
Releases. Consumers must therefore pin the npm artifact that actually exists
rather than infer publication from the repository manifest.

The project separates two processes:

- A canvas server providing the browser UI, REST API, and WebSocket live sync.
- A stdio MCP server exposing programmatic tools and synchronizing with the
  canvas server through `EXPRESS_SERVER_URL`.

The default canvas URL is `http://127.0.0.1:3000`.

## Interfaces and scene access

The packaged CLI and MCP server drive the same live canvas; the REST API is a
lower-level third interface. The CLI has explicit `start`, `status`, and `stop`
commands and can auto-start the canvas server for canvas-touching commands.
`start` reports whether it spawned the process, allowing callers to retain
cleanup ownership rather than stop an inherited canvas.

The published `1.1.0` MCP surface contains 26 tools covering element CRUD,
grouping and layout, scene description, screenshots, file import/export,
snapshots, Mermaid conversion, viewport control, and design guidance.
`describe_scene` returns structured element identities, labels, positions, and
relationships; `get_canvas_screenshot` returns the rendered view. The upstream
workflow uses semantic description for structural understanding and screenshots
for visual verification.

## Persistence and lifecycle

Canvas-server state is in memory. Restarting the server clears the live scene,
so durable work requires explicit export to an `.excalidraw` file and import
when resuming. Named snapshots support local rollback during an active server
lifecycle but do not replace exported files as durable storage.

Browser-dependent operations include screenshots, rendered image export,
Mermaid conversion, and viewport control. Element CRUD, queries, semantic
description, and scene-file operations can otherwise be driven headlessly.

The portable upstream skill lives at `skills/excalidraw-skill/`. It documents
status/start/stop, scene CRUD, describe-and-screenshot refinement, snapshots,
and file round trips for skill-capable agents.

## Network and security constraints

The canvas server binds to `127.0.0.1` by default. Binding to `0.0.0.0` enables
network access, but the upstream API has no built-in authentication. Any LAN,
tablet, container, or remote-device exposure therefore requires network-level
access control or an authenticated private proxy; the service must not be
published directly to an untrusted network.

## Sources

- https://github.com/yctimlin/mcp_excalidraw
- https://github.com/yctimlin/mcp_excalidraw/blob/main/package.json
- https://github.com/yctimlin/mcp_excalidraw/blob/main/skills/excalidraw-skill/SKILL.md
- https://github.com/yctimlin/mcp_excalidraw/releases
- https://www.npmjs.com/package/mcp-excalidraw-server
