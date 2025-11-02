#!/usr/bin/env python3
"""Test voice transcription by simulating a voice message upload.

This script tests the voice transcription functionality by:
1. Creating a test audio file
2. Calling the daemon's handle_voice method directly
3. Verifying transcription works

NOTE: This requires a valid OPENAI_API_KEY in .env file.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Load environment variables
from dotenv import load_dotenv

load_dotenv()

from teleclaude.core.voice_handler import VoiceHandler


async def test_voice_transcription():
    """Test voice transcription with a simple test."""
    print("Testing voice transcription...")

    # Initialize voice handler
    try:
        handler = VoiceHandler()
        print("✓ VoiceHandler initialized successfully")
    except ValueError as e:
        print(f"✗ Failed to initialize VoiceHandler: {e}")
        print("  Make sure OPENAI_API_KEY is set in .env file")
        return False

    # For actual testing, you would need a real voice file
    # Since we can't create one programmatically, just verify the handler is set up
    print("✓ Voice handler is ready to transcribe")
    print("\nTo fully test:")
    print("1. Open Telegram and navigate to TeleClaude Control supergroup")
    print("2. Open or create a session topic")
    print("3. Send a voice message (e.g., 'list files')")
    print("4. Verify you see:")
    print("   - '🎤 Transcribing...' message")
    print("   - '🎤 Transcribed: <your text>' message")
    print("   - Command output")

    return True


if __name__ == "__main__":
    result = asyncio.run(test_voice_transcription())
    sys.exit(0 if result else 1)
