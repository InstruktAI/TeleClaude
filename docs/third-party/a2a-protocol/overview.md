# A2A Protocol Overview

## What it is

The Agent2Agent (A2A) protocol is an open standard by Google (Apache 2.0, governed by the Linux Foundation) that enables communication and collaboration between independent AI agents. Unlike tool-calling protocols, A2A treats agents as opaque peers that discover each other, negotiate interactions, and coordinate work without exposing internal state.

## Core Concepts

| Concept                | Description                                                                                         |
| ---------------------- | --------------------------------------------------------------------------------------------------- |
| **A2A Client**         | Agent that initiates requests to a remote agent                                                     |
| **A2A Server**         | Agent exposing an A2A-compliant endpoint                                                            |
| **Agent Card**         | JSON metadata at `/.well-known/agent-card.json` describing identity, capabilities, skills, and auth |
| **Message**            | Communication unit containing one or more Parts (text, file, data)                                  |
| **Task**               | Stateful unit of work with lifecycle states (submitted, working, completed, etc.)                   |
| **Artifact**           | Output of a task, composed of Parts                                                                 |
| **Context**            | Optional identifier grouping related tasks into a conversation                                      |
| **Streaming**          | Real-time incremental updates via SSE                                                               |
| **Push Notifications** | Async webhook callbacks for long-running tasks                                                      |

## Architecture

A2A operates at the application layer on top of HTTP, SSE, and JSON-RPC (with optional gRPC support since v0.3). Communication flows:

```
Client Agent  --(A2A/JSON-RPC)--> Remote Agent
     |                                |
     |--- internally uses MCP ---|    |--- internally uses MCP ---|
     |   (tools, databases, APIs)|    |   (tools, databases, APIs)|
```

**Design principles:**

- **Agents as peers** — agents collaborate as equals, not as tool providers
- **Opaque execution** — agents don't need to share internal state, memory, or tools
- **Built on standards** — HTTP, SSE, JSON-RPC (familiar to enterprise stacks)
- **Enterprise-grade security** — OpenAPI-parity authentication schemes, mTLS, signed Agent Cards
- **Modality-agnostic** — text, files, structured data, images via Parts

## Protocol Versions

| Version | Date       | Key additions                                                     |
| ------- | ---------- | ----------------------------------------------------------------- |
| 0.1     | April 2025 | Initial spec: JSON-RPC, Agent Card, Task lifecycle, SSE streaming |
| 0.3     | July 2025  | gRPC support, signed security cards, extended Python SDK          |

## Sources

- https://a2a-protocol.org/latest/specification
- https://github.com/a2aproject/A2A
- https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/
- https://cloud.google.com/blog/products/ai-machine-learning/agent2agent-protocol-is-getting-an-upgrade
- /websites/a2a-protocol
- /google/a2a
