"""Constants used across TeleClaude.

This module defines shared constants to ensure consistency.
"""

# MCP Configuration
MCP_SOCKET_PATH = "/tmp/teleclaude.sock"
MCP_ENABLED = True

# Internal configuration (not user-configurable)
DIRECTORY_CHECK_INTERVAL = 5  # Seconds between directory change checks

# Redis internal settings
REDIS_MAX_CONNECTIONS = 10
REDIS_SOCKET_TIMEOUT = 60  # Increased to accommodate poor network conditions
REDIS_MESSAGE_STREAM_MAXLEN = 10000  # Max messages to keep per computer
REDIS_OUTPUT_STREAM_MAXLEN = 10000  # Max output messages per session
REDIS_OUTPUT_STREAM_TTL = 3600  # Auto-expire output streams after 1 hour
