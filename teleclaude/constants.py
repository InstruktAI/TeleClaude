"""Constants used across TeleClaude.

This module defines shared constants to ensure consistency.
"""

# Default Claude Code command with all required flags
# Used when config.mcp.claude_command is not set
DEFAULT_CLAUDE_COMMAND = 'claude --dangerously-skip-permissions --settings \'{"forceLoginMethod": "claudeai"}\''
