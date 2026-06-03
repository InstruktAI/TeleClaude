"""Constants for guarding TUI controls from paste/key-burst input."""

PASTE_IGNORED_NOTIFICATION = "paste ignored on TUI controls — focus an agent pane to paste"
POST_PASTE_KEY_SUPPRESSION_MS = 100
POST_PASTE_KEY_SUPPRESSION_SECONDS = POST_PASTE_KEY_SUPPRESSION_MS / 1000
BURST_THRESHOLD = 30
