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
