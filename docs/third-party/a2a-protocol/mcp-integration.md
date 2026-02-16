# A2A and MCP Integration

## What it is

A2A and MCP are complementary protocols that address different layers of agent communication. MCP standardizes agent-to-tool interactions (vertical), while A2A standardizes agent-to-agent collaboration (horizontal).

## Layered Architecture

```
  Agent A                              Agent B
  +------------------+                +------------------+
  |  A2A Client      |----(A2A)----->|  A2A Server      |
  |                  |                |                  |
  |  MCP Client      |               |  MCP Client      |
  |  +-- Tool 1      |               |  +-- Tool X      |
  |  +-- Tool 2      |               |  +-- Tool Y      |
  |  +-- Database    |               |  +-- API         |
  +------------------+                +------------------+
```

| Layer          | Protocol | Interaction                                 | State                           |
| -------------- | -------- | ------------------------------------------- | ------------------------------- |
| Agent-to-Agent | A2A      | Conversational, multi-turn, opaque peers    | Stateful (tasks with lifecycle) |
| Agent-to-Tool  | MCP      | Structured function calls, well-defined I/O | Typically stateless             |

## When to Use Each

**MCP alone** — Single agent accessing tools, APIs, databases. Stateless or short-lived interactions with well-structured inputs/outputs.

**A2A alone** — Peer agents collaborating on complex tasks. No shared internal state needed.

**Both together** — Multi-agent systems where each agent has its own toolset. A2A for inter-agent coordination, MCP for each agent's internal tool access.

## Key Differences

| Aspect        | MCP                                  | A2A                                   |
| ------------- | ------------------------------------ | ------------------------------------- |
| Discovery     | Tool descriptions (function schemas) | Agent Cards (high-level capabilities) |
| Granularity   | Individual tools/functions           | Whole-agent capabilities              |
| State         | Typically stateless                  | Stateful tasks with lifecycle         |
| Communication | Structured function calls            | Conversational messages               |
| Transparency  | Tool internals exposed               | Agent internals opaque                |

## Integration Example

A purchasing system with multiple agents:

1. **User Agent** sends purchase request to **Procurement Agent** via A2A
2. **Procurement Agent** uses MCP to query internal inventory database
3. **Procurement Agent** contacts **Supplier Agent** via A2A to check availability
4. **Supplier Agent** uses MCP to access its pricing API and warehouse system
5. Results flow back through A2A to the user

## Python A2A + MCP Bridge

The `python-a2a` library provides `MCPAgent` for bridging:

```python
from python_a2a.mcp import MCPAgent
from python_a2a import run_server

# Agent that exposes A2A interface but uses MCP tools internally
agent = MCPAgent(
    name="Inventory Assistant",
    description="Checks stock levels and manages orders",
    mcp_server_url="http://localhost:8000"
)

run_server(agent, port=5000)
```

## Sources

- https://a2a-protocol.org/latest/topics/a2a-and-mcp/
- https://auth0.com/blog/mcp-vs-a2a/
- https://www.clarifai.com/blog/mcp-vs-a2a-clearly-explained
- https://blogs.cisco.com/ai/mcp-and-a2a-a-network-engineers-mental-model-for-agentic-ai
- /themanojdesai/python-a2a
- /websites/a2a-protocol
