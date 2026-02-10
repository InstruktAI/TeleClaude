#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
#     "instruktai-python-logger",
# ]
# ///

import json
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from teleclaude.constants import MAIN_MODULE

# Define the valid MCP handshake messages
INIT_MSG = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "1.0"},
    },
}

NOTIFY_MSG = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}

CALL_MSG = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {"name": "teleclaude__list_computers", "arguments": {}},
}


def run_test():
    print("--- Starting Wrapper Resilience Test ---")

    # Start the wrapper subprocess
    wrapper = subprocess.Popen(
        ["python3", "bin/mcp-wrapper.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        bufsize=0,  # Unbuffered
    )

    print(f"Wrapper started with PID {wrapper.pid}")

    try:
        # 1. Perform Handshake
        print("Sending Initialize...")
        wrapper.stdin.write(json.dumps(INIT_MSG) + "\n")
        wrapper.stdin.flush()

        # Read Initialize Response
        response = wrapper.stdout.readline()
        print(f"Init Response: {response.strip()}")

        print("Sending Initialized Notification...")
        wrapper.stdin.write(json.dumps(NOTIFY_MSG) + "\n")
        wrapper.stdin.flush()

        # 2. Call Tool (Before Restart)
        print("Calling teleclaude__list_computers (Pre-Restart)...")
        wrapper.stdin.write(json.dumps(CALL_MSG) + "\n")
        wrapper.stdin.flush()

        response = wrapper.stdout.readline()
        print(f"Tool Response (Pre-Restart): {response[:100]}...")

        # 3. RESTART DAEMON (User Action Simulation)
        print("\n!!! RESTARTING DAEMON (5s pause) !!!")
        subprocess.run(["make", "restart"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)  # Give it a moment to come back

        # 4. Call Tool (Post-Restart)
        # If the wrapper works, this should SUCCEED transparently
        print("Calling teleclaude__list_computers (Post-Restart)...")

        # Use a new ID for the second call
        CALL_MSG["id"] = 3
        wrapper.stdin.write(json.dumps(CALL_MSG) + "\n")
        wrapper.stdin.flush()

        response = wrapper.stdout.readline()
        if response:
            print(f"Tool Response (Post-Restart): {response[:100]}...")
            print("\nSUCCESS: Connection survived daemon restart!")
        else:
            print("\nFAILURE: No response after restart (pipe broken).")

    except Exception as e:
        print(f"\nERROR: {e}")
    finally:
        wrapper.terminate()


if __name__ == MAIN_MODULE:
    run_test()
