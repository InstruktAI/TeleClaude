# A2UI Protocol Overview

## What it is

A2UI (Agent-to-UI) is Google's open-source declarative UI specification that enables AI agents to generate rich, interactive interfaces rendered natively across web, mobile, and desktop. Agents emit JSON describing UI structure; clients render using their own component implementations and styling.

## Core Design

```
Agent (LLM) --> A2UI JSON stream --> Transport (SSE/WS/A2A)
                                          |
Client: Stream Reader --> Message Parser --> Renderer --> Native UI
```

**Key properties:**

- **Declarative** — JSON structure, no executable code (security by design)
- **Framework-agnostic** — Same agent response renders on React, Angular, Flutter, native mobile
- **Catalog-based** — Components are pre-approved; agents can only reference cataloged widgets
- **Progressive rendering** — JSONL streaming, UI builds incrementally as tokens arrive
- **LLM-friendly** — Flat JSON structure designed for easy generation by language models

## Message Types (Server-to-Client)

### 1. Surface Update — defines UI structure

```json
{
  "surfaceUpdate": {
    "surfaceId": "booking_form",
    "components": [
      {
        "id": "name_field",
        "component": {
          "TextField": {
            "label": "Guest Name",
            "value": { "path": "/reservation/name" }
          }
        }
      },
      {
        "id": "submit_btn",
        "component": {
          "Button": {
            "child": "submit_text",
            "action": {
              "name": "submit_form",
              "context": [{ "key": "name", "value": { "path": "/reservation/name" } }]
            }
          }
        }
      }
    ]
  }
}
```

### 2. Data Model Update — populates values

```json
{
  "dataModelUpdate": {
    "surfaceId": "booking_form",
    "path": "/reservation",
    "contents": [
      { "key": "name", "valueString": "John Doe" },
      { "key": "guests", "valueNumber": 2 }
    ]
  }
}
```

### 3. Begin Rendering — signals ready

```json
{ "beginRendering": { "surfaceId": "booking_form", "root": "root" } }
```

### 4. Delete Surface — removes UI

```json
{ "deleteSurface": { "surfaceId": "booking_form" } }
```

## Component Catalog

The catalog is the key architectural concept:

- Components are NOT fixed by the protocol — defined in a separate **Catalog**
- Clients register renderers for each component type
- Agents discover available catalogs through metadata exchange
- Custom components extend the catalog for domain-specific needs (charts, maps, dashboards)
- **Security model**: agents can only reference pre-approved catalog components

## Data Binding

Components reference data through path bindings (`"path": "/reservation/guests"`), enabling:

- Automatic sync between UI and data model
- Live updates by sending new `dataModelUpdate` messages
- No explicit event handling needed in component definitions

## Performance

- **Batching**: Updates buffer within 16ms intervals
- **Diffing**: Only changed properties update
- **Granular updates**: Modify specific data paths, not entire models

## Current Status

v0.8 (Public Preview), v0.9 draft available. Actively developed under Google open-source.

## Sources

- https://a2ui.org/
- https://a2ui.org/concepts/data-flow
- https://a2ui.org/concepts/components/
- https://a2ui.org/guides/custom-components/
- https://github.com/google/A2UI
- https://developers.googleblog.com/introducing-a2ui-an-open-project-for-agent-driven-interfaces/
- /websites/a2ui
