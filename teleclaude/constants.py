"""Constants used across TeleClaude.

This module defines shared constants to ensure consistency.
"""

# MCP Configuration
MCP_SOCKET_PATH = "/tmp/teleclaude.sock"

# Internal configuration (not user-configurable)
DIRECTORY_CHECK_INTERVAL = 5  # Seconds between directory change checks
UI_MESSAGE_MAX_CHARS = 3900  # Telegram limit minus formatting overhead

# Redis internal settings
REDIS_MAX_CONNECTIONS = 10
REDIS_SOCKET_TIMEOUT = 60  # Increased to accommodate poor network conditions
REDIS_MESSAGE_STREAM_MAXLEN = 10000  # Max messages to keep per computer
REDIS_OUTPUT_STREAM_MAXLEN = 10000  # Max output messages per session
REDIS_OUTPUT_STREAM_TTL = 3600  # Auto-expire output streams after 1 hour

# Agent metadata (NOT user-configurable)
AGENT_METADATA: dict[str, dict[str, str | dict[str, str]]] = {
    "claude": {
        "session_dir": "~/.claude/sessions",
        "log_pattern": "*.jsonl",
        "model_flags": {
            "fast": "--model haiku",
            "med": "--model sonnet",
            "slow": "--model opus",
        },
        "exec_subcommand": "",
        "interactive_flag": "",
        "non_interactive_flag": "-p",
        "resume_template": "{base_cmd} --resume {session_id}",
        "continue_template": "{base_cmd} --continue",
    },
    "gemini": {
        "session_dir": "~/.gemini/sessions",
        "log_pattern": "*.jsonl",
        "model_flags": {
            "fast": "-m gemini-2.5-flash-lite",
            "med": "-m gemini-3-flash-preview",
            "slow": "-m gemini-3-pro-preview",
        },
        "exec_subcommand": "",
        "interactive_flag": "-i",
        "non_interactive_flag": "-p",
        "resume_template": "{base_cmd} --resume {session_id}",
        "continue_template": "{base_cmd} --resume latest",
    },
    "codex": {
        "session_dir": "~/.codex/sessions",
        "log_pattern": "*.jsonl",
        "model_flags": {
            "fast": "-m gpt-5.2-codex --config model_reasoning_effort='low'",
            "med": "-m gpt-5.2-codex --config model_reasoning_effort='medium'",
            "slow": "-m gpt-5.2-codex --config model_reasoning_effort='high'",
            "deep": "-m gpt-5.2-codex --config model_reasoning_effort='xhigh'",
        },
        "exec_subcommand": "exec",
        "interactive_flag": "",
        "non_interactive_flag": "",
        "resume_template": "{base_cmd} resume {session_id}",
        "continue_template": "{base_cmd} resume --last",
    },
}
