"""Typed outcomes for the configured speech-to-text chain."""


class STTServiceUnavailableError(RuntimeError):
    """A configured speech-to-text service cannot run on this computer."""


class NoSTTServiceError(RuntimeError):
    """No configured speech-to-text service can run on this computer."""


class STTTranscriptionFailedError(RuntimeError):
    """Speech-to-text services ran but did not produce a transcript."""
