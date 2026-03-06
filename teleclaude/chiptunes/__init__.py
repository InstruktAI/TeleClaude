"""ChipTunes SID playback package.

Requires optional dependencies: pyresidfp, py65emu, sounddevice.
Install with: pip install 'teleclaude[chiptunes]'

PortAudio system dependency (macOS): brew install portaudio
"""

from teleclaude.chiptunes.manager import ChiptunesManager

__all__ = ["ChiptunesManager"]
