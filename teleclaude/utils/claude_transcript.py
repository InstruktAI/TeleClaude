"""Parse and convert Claude Code session transcripts to markdown."""

import json
from pathlib import Path


def parse_claude_transcript(transcript_path: str, title: str) -> str:
    """Convert Claude Code JSONL transcript to markdown.

    Args:
        transcript_path: Path to Claude session .jsonl file
        session: TeleClaude session object for title/metadata

    Returns:
        Markdown formatted conversation with tool calls/responses as separate sections
    """
    path = Path(transcript_path).expanduser()
    if not path.exists():
        return f"Transcript file not found: {transcript_path}"

    lines = []

    # Add title from session
    lines.append(f"# {title}")
    lines.append("")

    last_section = None  # Track last section type to group consecutive blocks

    try:
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)

                # Skip summary entries
                if entry.get("type") == "summary":
                    continue

                # Extract message content (nested in 'message' field for Claude Code transcripts)
                message = entry.get("message", {})
                role = message.get("role")
                content = message.get("content", [])

                # Skip if no role
                if not role:
                    continue

                # Process content blocks - separate tool_use/tool_result from text
                if isinstance(content, str):
                    # User message (string content)
                    if last_section != "user":
                        lines.append("")
                        lines.append("## 👤 User")
                        lines.append("")
                        last_section = "user"
                    lines.append(content)
                elif isinstance(content, list):
                    # Assistant or user message with blocks
                    for block in content:
                        block_type = block.get("type")

                        if block_type == "text":
                            # Text from assistant
                            if role == "assistant" and last_section != "assistant":
                                lines.append("")
                                lines.append("## 🤖 Assistant")
                                lines.append("")
                                last_section = "assistant"
                            text = block.get("text", "")
                            lines.append(text)

                        elif block_type == "thinking":
                            # Thinking block (only in assistant messages)
                            if last_section != "assistant":
                                lines.append("")
                                lines.append("## 🤖 Assistant")
                                lines.append("")
                                last_section = "assistant"
                            formatted_thinking = _format_thinking(block.get("thinking", ""))
                            lines.append(formatted_thinking)

                        elif block_type == "tool_use":
                            # Tool call - single line with serialized JSON
                            tool_name = block.get("name", "unknown")
                            tool_input = block.get("input", {})
                            serialized_input = json.dumps(tool_input)
                            lines.append("")
                            lines.append(f"🔧 **TOOL CALL:** {tool_name} {serialized_input}")
                            last_section = "tool_use"

                        elif block_type == "tool_result":
                            # Tool response - blockquote expandable format
                            is_error = block.get("is_error", False)
                            status_emoji = "❌" if is_error else "✅"
                            content_data = block.get("content", "")
                            lines.append("")
                            lines.append(f"{status_emoji} **TOOL RESPONSE:**")
                            lines.append("")
                            lines.append("<blockquote expandable>")
                            lines.append(str(content_data))
                            lines.append("</blockquote>")
                            last_section = "tool_result"

    except Exception as e:
        return f"Error parsing transcript: {e}"

    return "\n".join(lines)


def _format_thinking(text: str) -> str:
    """Format thinking block with italics, preserving code blocks.

    Args:
        text: Thinking block text

    Returns:
        Formatted markdown with italics for non-code lines, blank line after
    """
    lines = text.split("\n")
    result_lines = []
    in_code_block = False

    for line in lines:
        if line.strip().startswith("```"):
            if not in_code_block:
                # Add blank line before opening backticks
                result_lines.append("")
            result_lines.append(line)
            in_code_block = not in_code_block
        elif in_code_block or not line.strip():
            result_lines.append(line)
        else:
            result_lines.append(f"*{line}*")

    # Add blank line after thinking block
    result_lines.append("")

    return "\n".join(result_lines)
