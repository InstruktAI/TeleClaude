#!/usr/bin/env python3
"""Test what happens when creating duplicate tmux session."""

import asyncio


async def test_duplicate():
    """Test creating duplicate tmux session."""

    session_name = "test-duplicate-12345"

    # Create first session
    print(f"Creating session: {session_name}")
    proc = await asyncio.create_subprocess_exec(
        "tmux", "new-session", "-d", "-s", session_name, "-c", "~", "-x", "80", "-y", "24", "/bin/zsh -l",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    print(f"First create - Return code: {proc.returncode}")
    print(f"Stdout: {stdout.decode()}")
    print(f"Stderr: {stderr.decode()}")

    # Try to create again (duplicate)
    print(f"\nAttempting to create duplicate session: {session_name}")
    proc = await asyncio.create_subprocess_exec(
        "tmux", "new-session", "-d", "-s", session_name, "-c", "~", "-x", "80", "-y", "24", "/bin/zsh -l",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    print(f"Second create - Return code: {proc.returncode}")
    print(f"Stdout: {stdout.decode()}")
    print(f"Stderr: {stderr.decode()}")

    # Check if session exists
    print(f"\nChecking if session exists...")
    proc = await asyncio.create_subprocess_exec(
        "tmux", "has-session", "-t", session_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    print(f"has-session - Return code: {proc.returncode}")
    print(f"Exists: {proc.returncode == 0}")

    # Clean up
    print(f"\nCleaning up...")
    await asyncio.create_subprocess_exec("tmux", "kill-session", "-t", session_name)


if __name__ == "__main__":
    asyncio.run(test_duplicate())
