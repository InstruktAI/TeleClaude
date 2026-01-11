#!/usr/bin/env python3
"""Script to add timeouts to subprocess operations in terminal_bridge.py."""

import re
from pathlib import Path


def fix_file(file_path: Path) -> None:
    """Add timeout wrappers to all subprocess wait() and communicate() calls."""
    content = file_path.read_text()

    # Pattern 1: await result.wait() -> await wait_with_timeout(result, SUBPROCESS_TIMEOUT_QUICK, "operation")
    # We'll use QUICK timeout for most tmux operations as they should be fast
    content = re.sub(
        r'(\s+)await (\w+)\.wait\(\)',
        r'\1await wait_with_timeout(\2, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")',
        content
    )

    # Pattern 2: await result.communicate() -> await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "operation")
    content = re.sub(
        r'(\s+)([\w_]+),\s*([\w_]+)\s*=\s*await (\w+)\.communicate\(\)',
        r'\1\2, \3 = await communicate_with_timeout(\4, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")',
        content
    )

    # Pattern 3: await result.communicate(input_data)
    content = re.sub(
        r'(\s+)([\w_]+),\s*([\w_]+)\s*=\s*await (\w+)\.communicate\(([^)]+)\)',
        r'\1\2, \3 = await communicate_with_timeout(\4, \5, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")',
        content
    )

    file_path.write_text(content)
    print(f"Fixed {file_path}")


if __name__ == "__main__":
    file_path = Path("teleclaude/core/terminal_bridge.py")
    if not file_path.exists():
        print(f"Error: {file_path} not found")
        exit(1)

    fix_file(file_path)
    print("Done! Please review the changes and run tests.")
