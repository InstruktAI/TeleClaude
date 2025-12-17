"""Constants used across TeleClaude.

This module defines shared constants to ensure consistency.
"""

# MCP Configuration
MCP_SOCKET_PATH = "/tmp/teleclaude.sock"
MCP_ENABLED = True

# Default Claude Code command with all required flags
DEFAULT_CLAUDE_COMMAND = 'claude --dangerously-skip-permissions --settings \'{"forceLoginMethod": "claudeai"}\''

# Default Gemini command
DEFAULT_GEMINI_COMMAND = "gemini --yolo"

# Default Codex command
DEFAULT_CODEX_COMMAND = "codex --dangerously-bypass-approvals-and-sandbox --search"

# Resume command templates for agents (used when restarting sessions)
# {base_cmd} = agent's base command with flags, {session_id} = native session ID
# Claude/Gemini: append --resume flag to base command
# Codex: uses subcommand "resume" instead of flag (flags still required)
AGENT_RESUME_TEMPLATES = {
    "claude": "{base_cmd} --resume {session_id}",
    "gemini": "{base_cmd} --resume {session_id}",
    "codex": "{base_cmd} resume {session_id}",
}

# Session directories for agents (standard locations)
AGENT_SESSION_DIRS = {
    "claude": "~/.claude/sessions",
    "gemini": "~/.gemini/tmp",
    "codex": "~/.codex/sessions",
}

# Log file patterns for agents
AGENT_LOG_PATTERNS = {
    "claude": "*.jsonl",
    "gemini": "*.jsonl",
    "codex": "*.jsonl",
}

# Internal configuration (not user-configurable)
DIRECTORY_CHECK_INTERVAL = 5  # Seconds between directory change checks

# Redis internal settings
REDIS_MAX_CONNECTIONS = 10
REDIS_SOCKET_TIMEOUT = 60  # Increased to accommodate poor network conditions
REDIS_MESSAGE_STREAM_MAXLEN = 10000  # Max messages to keep per computer
REDIS_OUTPUT_STREAM_MAXLEN = 10000  # Max output messages per session
REDIS_OUTPUT_STREAM_TTL = 3600  # Auto-expire output streams after 1 hour
