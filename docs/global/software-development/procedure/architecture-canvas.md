---
description: Mechanics for the exceptional case where a picture must be manipulated on a live agent-readable canvas — server lifecycle, semantic scene discipline, and promotion of agreed design.
activation_trigger: Use when the escalation test in general/procedure/visualizing-for-humans has passed — the arrangement itself carries meaning that the relations do not, and a person will actually manipulate the shapes — or when the human explicitly asks for Excalidraw, a canvas, or a whiteboard. A request to draw, diagram, or visualize does not by itself activate this procedure.
---

# Architecture Canvas — Procedure

## Required reads

@~/.teleclaude/docs/general/procedure/visualizing-for-humans.md
@~/.teleclaude/docs/general/spec/scratchpad-workspaces.md
@~/.teleclaude/docs/general/procedure/invoke-mcp-server-tools.md
@~/.teleclaude/docs/general/procedure/doc-snippet-authoring.md

## Goal

Give a human and one or more agents a shared, semantically inspectable canvas
for the architecture work that needs one — where the arrangement carries meaning
no layout engine can infer and a person will move the shapes — while keeping
temporary exploration separate from durable design. Preserve the editable canvas
source when it remains useful, but make the documentation snippet—not a drawing
or screenshot—the authoritative architecture contract. Everything a human simply
needs to see is cheaper and clearer as Mermaid source; see
`general/procedure/visualizing-for-humans`.

## Preconditions

- The escalation test in `general/procedure/visualizing-for-humans` has passed.
  A canvas server is never started because a request mentioned drawing,
  diagramming, collaboration, or a scratchpad; it is started because the
  arrangement carries meaning the relations do not and someone will manipulate
  it. When only reading is needed, that procedure's Mermaid default applies and
  this one does not run.
- The configured `excalidraw` MCP server is available through TeleClaude's lazy
  MCP runtime. The pinned upstream package supplies the loopback canvas server
  and its lifecycle CLI; no separately installed skill is required.
- The relevant current architecture and affected domain specifications have
  been read through `telec docs`.
- The collaboration route is known: local browser by default, or an explicitly
  secured network route when another device such as an iPad participates.
- The project provides a version-control-ignored `scratchpad/` root.

## Steps

1. Create `scratchpad/YYYYMMDD-HHMMSS-<topic>/`. Use `notes.md` for unresolved
   questions and decisions, `canvas.excalidraw` for the editable scene, and
   `canvas.svg` only when a temporary rendered view is useful.
2. Run `npx -y mcp-excalidraw-server@1.1.0 start`. Retain the returned canvas
   URL and `spawned` value for this activity: `spawned: true` grants cleanup
   ownership; `spawned: false` means the process was inherited. Reuse an
   inherited canvas only when its current scene belongs to this activity.
3. Run `telec mcp list-tools excalidraw` to initialize or reuse the daemon-owned
   MCP lease. Open the canvas URL retained from Step 2 for the human: use
   `open <url>` on macOS or `xdg-open <url>` on Linux. On a headless host,
   present the URL only through an explicitly secured private route; never bind
   the unauthenticated canvas directly to an untrusted network.
4. Import the workspace's latest `canvas.excalidraw` when resuming. Before
   changing an existing scene, inspect its semantic description and query its
   elements so labels, relationships, identifiers, and grouping remain intact.
5. Collaborate on the same live canvas. Use stable element identifiers, make
   bounded edits, and snapshot before material edit batches. Agents interpret
   the scene through the semantic API; screenshots supplement that reading only
   for layout, legibility, overlap, and visual-quality checks.
6. Export the editable scene to the scratch workspace at meaningful
   checkpoints and before any server shutdown. Keep open questions in
   `notes.md`; do not encode unresolved prose only as shapes on the canvas.
7. When the human and agent agree on the architecture, classify each result:
   current durable architecture enters a live design snippet; undelivered
   architecture enters the existing pending-documentation lifecycle; tactics,
   alternatives, and discarded exploration remain ephemeral. Agreement never
   bypasses delivery state.
8. For a composite architecture topic, promote durable material into:

   ```text
   docs/project/design/architecture/<topic>/
     overview.md
     <facet>.md
     canvas.excalidraw
     canvas.svg
   ```

   `overview.md` is the canonical design snippet. Add a facet only when it
   carries an independently useful design contract. Preserve
   `canvas.excalidraw` when future humans or agents benefit from editing or
   semantically inspecting it. Preserve `canvas.svg` only when a durable
   document or surface consumes it. Distill the canvas into the Markdown
   contract rather than copying scratch notes or treating the image as truth.

9. After a final export, run `npx -y mcp-excalidraw-server@1.1.0 stop` only when
   Step 2 returned `spawned: true` and no participant is continuing the
   collaboration. The daemon owns and reaps its MCP stdio lease independently;
   this cleanup command owns only the canvas process. Remove transient renders
   and browser captures. Retain or remove the scratch workspace according to
   the scratchpad contract; its existence never signals completion.

### Examples

These patterns cover the common collaboration flow. They are representative,
not exhaustive or allowlisting; use other Excalidraw MCP operations when the
architecture activity requires them.

Start the pinned canvas, initialize the MCP lease, and open the human view:

```sh
npx -y mcp-excalidraw-server@1.1.0 start
telec mcp list-tools excalidraw
open http://127.0.0.1:3000
xdg-open http://127.0.0.1:3000
```

Read the design guidance and current semantic scene before editing:

```sh
telec mcp call excalidraw read_diagram_guide --json '{}'
telec mcp call excalidraw describe_scene --json '{}'
telec mcp call excalidraw query_elements --json '{}'
telec mcp call excalidraw get_element --json '{"id":"<element-id>"}'
```

Create a bounded shape, update it, or delete it by stable identifier:

```sh
telec mcp call excalidraw batch_create_elements --json '{"elements":[{"id":"component-a","type":"rectangle","x":120,"y":120,"width":240,"height":100,"text":"Component A"}]}'
telec mcp call excalidraw update_element --json '{"id":"component-a","x":180,"y":160}'
telec mcp call excalidraw delete_element --json '{"id":"component-a"}'
```

Create connected architecture from Mermaid or arrange existing elements:

```sh
telec mcp call excalidraw create_from_mermaid --json '{"mermaidDiagram":"flowchart LR; A[Input] --> B[Boundary]"}'
telec mcp call excalidraw align_elements --json '{"elementIds":["component-a","component-b"],"alignment":"middle"}'
telec mcp call excalidraw distribute_elements --json '{"elementIds":["component-a","component-b"],"direction":"horizontal"}'
```

Checkpoint and restore before a material edit batch:

```sh
telec mcp call excalidraw snapshot_scene --json '{"name":"before-boundary-rework"}'
telec mcp call excalidraw restore_snapshot --json '{"name":"before-boundary-rework"}'
```

Import, inspect visually, and export the activity workspace:

```sh
telec mcp call excalidraw import_scene --json '{"filePath":"<absolute-path>/canvas.excalidraw","mode":"replace"}'
telec mcp call excalidraw set_viewport --json '{"scrollToContent":true}'
telec mcp call excalidraw get_canvas_screenshot --json '{"background":true}'
telec mcp call excalidraw export_scene --json '{"filePath":"<absolute-path>/canvas.excalidraw"}'
telec mcp call excalidraw export_to_image --json '{"format":"svg","filePath":"<absolute-path>/canvas.svg","background":true}'
```

Stop only a canvas process owned by this activity:

```sh
npx -y mcp-excalidraw-server@1.1.0 stop
```

## Outputs

- A semantically inspectable collaborative canvas checkpointed under the
  activity's scratch workspace.
- Agreed durable architecture distilled into the appropriate live or pending
  project design snippets.
- Optional co-located editable and rendered canvas companions when they have
  durable value.
- A canvas server left running only when another active participant still owns
  or needs it.

## Discipline

`create_from_mermaid` renders into the browser view only: converted content does
not enter the semantic element store and does not appear in an export, so it can
be neither inspected by identifier nor persisted through this surface. It is a
preview device, never a way to build a scene — a diagram that needs a layout
engine belongs in Mermaid source under
`general/procedure/visualizing-for-humans`, not on this canvas.

Do not let the ease of drawing turn the canvas into a parallel documentation
system. Semantic scene access is primary because agents must reason about the
same model the human edits; screenshots alone are insufficient evidence of
structure. Promote only settled design, preserve pending-state semantics, and
keep transient exploration in the scratchpad. Server cleanup follows ownership:
starting a process permits stopping it only after confirming nobody else is
using it.

## Recovery

- **The server is already running.** Inspect its scene before deciding whether
  it belongs to this activity. Export foreign work before clearing anything;
  prefer a separate server instance when ownership is ambiguous.
- **The server exits or the browser disconnects.** Restart through the upstream
  lifecycle CLI, reopen its URL, and import the latest scratch export. Do not
  reconstruct the scene from screenshots.
- **Semantic tools are unavailable but the UI renders.** Stop substantive
  agent edits and repair the MCP connection. Screenshot-only collaboration does
  not satisfy this procedure.
- **Remote-device access is unavailable.** Continue locally or establish an
  authenticated private route. Do not expose an unauthenticated canvas service
  publicly.
- **Durable promotion fails validation.** Leave the exported source in the
  scratch workspace, correct the documentation shape, and rerun `telec sync`.
