"""Unit tests for terminal metadata contract helpers."""

from teleclaude.core.terminal_events import TerminalEventMetadata


def test_terminal_event_metadata_roundtrip() -> None:
    """Test that TerminalEventMetadata round-trips through channel metadata."""
    meta = TerminalEventMetadata(
        tty_path="/dev/pts/7",
        parent_pid=1234,
    )

    channel = meta.to_channel_metadata()
    assert channel == {
        "terminal": {
            "tty_path": "/dev/pts/7",
            "parent_pid": 1234,
        }
    }

    parsed = TerminalEventMetadata.from_channel_metadata(channel)
    assert parsed == meta


def test_terminal_event_metadata_handles_missing() -> None:
    """Test that missing channel metadata yields empty TerminalEventMetadata."""
    parsed = TerminalEventMetadata.from_channel_metadata(None)
    assert parsed.tty_path is None
    assert parsed.parent_pid is None
