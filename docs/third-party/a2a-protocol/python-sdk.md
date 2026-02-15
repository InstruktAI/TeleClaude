# A2A Python SDK

## What it is

`python-a2a` is the primary Python library for implementing A2A protocol servers and clients. It provides classes for building agents, handling tasks, and bridging with MCP.

## Installation

```bash
pip install python-a2a
```

## Building an A2A Server

```python
from python_a2a import A2AServer, run_server

class MyAgent(A2AServer):
    def handle_message(self, message):
        # Process incoming message, return response
        text = message.parts[0].text
        return {
            "role": "agent",
            "parts": [{"kind": "text", "text": f"Processed: {text}"}]
        }

agent = MyAgent()
run_server(agent, port=5000)
```

## Building an A2A Client

```python
from python_a2a import A2AClient

client = A2AClient("https://agent.example.com/a2a/v1")

# Send a message and get response
response = client.send_message({
    "role": "user",
    "parts": [{"kind": "text", "text": "Hello agent"}]
})
```

## MCP Bridge Agent

Expose MCP tools through an A2A interface:

```python
from python_a2a.mcp import FastMCP, MCPAgent
from python_a2a import run_server
import threading

# Define MCP tools
calculator = FastMCP(name="Calculator")

@calculator.tool()
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b

@calculator.tool()
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b

# Start MCP server
threading.Thread(
    target=run_server, args=(calculator,),
    kwargs={"port": 8000}, daemon=True
).start()

# A2A agent that uses MCP tools
agent = MCPAgent(
    name="Math Assistant",
    description="Performs calculations",
    mcp_server_url="http://localhost:8000"
)

run_server(agent, port=5000)
```

## Key Classes

| Class        | Purpose                                           |
| ------------ | ------------------------------------------------- |
| `A2AServer`  | Base class for A2A agent servers                  |
| `A2AClient`  | Client for calling A2A agents                     |
| `MCPAgent`   | A2A server that bridges to MCP tools              |
| `FastMCP`    | Quick MCP server builder with `@tool()` decorator |
| `run_server` | Utility to start HTTP server for any agent        |

## Google ADK Integration

Google's Agent Development Kit (ADK) has native A2A support:

```python
# ADK agents can be exposed as A2A servers directly
# See: https://google.github.io/adk-docs/a2a/
```

## Sources

- https://github.com/themanojdesai/python-a2a
- https://google.github.io/adk-docs/a2a/
- /themanojdesai/python-a2a
