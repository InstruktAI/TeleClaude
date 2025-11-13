"""Parse and convert Claude Code session transcripts to markdown."""

import json
from pathlib import Path


def parse_claude_transcript(transcript_path: str, title: str) -> str:
    """Convert Claude Code JSONL transcript to markdown.

    Args:
        transcript_path: Path to Claude session .jsonl file
        session: TeleClaude session object for title/metadata

    Returns:
        Markdown formatted conversation
    """
    path = Path(transcript_path).expanduser()
    if not path.exists():
        return f"Transcript file not found: {transcript_path}"

    lines = []

    # Add title from session
    lines.append(f"# {title}")
    lines.append("")

    last_role = None
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

                # Only add role header if role changed
                if role != last_role:
                    if last_role is not None:
                        lines.append("")  # Blank line after previous section
                        lines.append("")
                    if role == "user":
                        lines.append("## 👤 User")
                        lines.append("")
                    elif role == "assistant":
                        lines.append("## 🤖 Assistant")
                        lines.append("")
                    last_role = role

                # Append content (multiple blocks from same role get concatenated)
                formatted = _format_content(content)
                if formatted:
                    lines.append(formatted)

    except Exception as e:
        return f"Error parsing transcript: {e}"

    return "\n".join(lines)


def _format_content(content):  # type: ignore[no-untyped-def]
    """Format message content to markdown.

    Args:
        content: Either a string (user messages) or array of blocks (assistant messages)
    """
    # User messages have content as string - make bold
    if isinstance(content, str):
        return f"**{content}**"

    # Assistant messages have content as array of blocks
    parts = []

    for block in content:
        block_type = block.get("type")

        if block_type == "text":
            # Assistant text - make bold
            text = block.get("text", "")
            parts.append(f"**{text}**")

        elif block_type == "thinking":
            # Claude's thinking blocks (italic per line, no visible markers)
            text = block.get("thinking", "")

            # Process line by line, skipping code blocks
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
            parts.append("\n".join(result_lines))

        elif block_type == "tool_use":
            # Tool calls
            tool_name = block.get("name", "unknown")
            tool_input = block.get("input", {})
            parts.append(f"**🔧 Tool: {tool_name}**\n```json\n{json.dumps(tool_input, indent=2)}\n```")

        elif block_type == "tool_result":
            # Tool responses
            content_data = block.get("content", "")
            is_error = block.get("is_error", False)
            status = "❌ Error" if is_error else "✅ Result"
            parts.append(f"**{status}**\n```\n{content_data}\n```")

        prev_type = block_type

    return "\n".join(parts)
