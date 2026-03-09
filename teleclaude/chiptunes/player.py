"""ChipTunes streaming player — drives 6502 emulation and routes PCM to sounddevice."""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Callable

from instrukt_ai_logging import get_logger

from teleclaude.chiptunes.sid_cpu import SIDDriver
from teleclaude.chiptunes.sid_parser import SIDHeader, is_pal, parse_sid_file, speed_for_subtune
from teleclaude.chiptunes.sid_renderer import SIDRenderer

try:
    import sounddevice as sd  # type: ignore[import-untyped]

    _sounddevice_available = True  # pylint: disable=invalid-name
except ImportError:
    _sounddevice_available = False  # pylint: disable=invalid-name
    sd = None  # type: ignore[assignment]

logger = get_logger(__name__)

_PREBUFFER_SECONDS = 2.5  # seconds of audio pre-buffered before stream starts
_QUEUE_MAX_CHUNKS = 400  # maximum queue depth (~400 frames at 50Hz ≈ 8s)
_SAMPLE_RATE = 48000


class ChiptunesPlayer:  # pylint: disable=too-many-instance-attributes
    """Plays a SID file in a background thread via sounddevice."""

    def __init__(self, volume: float = 0.5, max_track_duration: float = 300.0) -> None:
        self._volume = max(0.0, min(1.0, volume))
        self._max_track_duration = max_track_duration
        self._stop_event = threading.Event()
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._thread: threading.Thread | None = None
        self._stream: object | None = None  # sounddevice.RawOutputStream
        self._stream_blocksize: int | None = None
        self._stream_lock = threading.RLock()
        self._pcm_queue: queue.Queue[bytes] = queue.Queue(maxsize=_QUEUE_MAX_CHUNKS)
        self._playing = False
        self._paused = False
        self._pause_lock = threading.Lock()
        self.on_track_end: Callable[[], None] | None = None

    @property
    def is_playing(self) -> bool:
        """Return True if playback is actively advancing and audible."""
        return self._playing and not self._stop_event.is_set() and not self._paused

    @property
    def is_paused(self) -> bool:
        """Return True if playback is loaded but currently paused."""
        return self._paused and not self._stop_event.is_set()

    def play(self, sid_path: Path, *, start_paused: bool = False) -> None:
        """Parse and start playing a SID file in the background."""
        if not _sounddevice_available:
            raise ImportError(
                "sounddevice is required for audio playback. Install it with: pip install 'teleclaude[chiptunes]'"
            )
        self.stop()

        try:
            header = parse_sid_file(sid_path)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to parse SID file %s: %s", sid_path, exc)
            self._notify_track_end()
            return

        self._stop_event.clear()
        self._playing = True
        self._paused = start_paused
        if start_paused:
            self._resume_event.clear()
        else:
            self._resume_event.set()
        pal = is_pal(header)
        frame_rate = 50.0 if pal else 60.0
        frame_duration = 1.0 / frame_rate
        samples_per_frame = int(_SAMPLE_RATE * frame_duration)
        self._stream_blocksize = samples_per_frame * 4
        self._pcm_queue = queue.Queue(maxsize=_QUEUE_MAX_CHUNKS)

        self._thread = threading.Thread(
            target=self._emulation_loop,
            args=(header,),
            daemon=True,
            name="chiptunes-emulator",
        )
        self._thread.start()

        if start_paused:
            return

        # Wait until pre-buffer is filled before opening the audio stream
        self._start_stream_after_prebuffer(header)

    def _start_stream_after_prebuffer(self, header: SIDHeader) -> None:
        """Wait for pre-buffer, then open the sounddevice stream."""
        pal = is_pal(header)
        frame_rate = 50.0 if pal else 60.0
        prebuffer_frames = int(_PREBUFFER_SECONDS * frame_rate)

        # Block until enough frames are buffered or stop is signalled
        deadline = time.monotonic() + _PREBUFFER_SECONDS
        while time.monotonic() < deadline and not self._stop_event.is_set():
            if self._pcm_queue.qsize() >= prebuffer_frames:
                break
            self._stop_event.wait(0.05)

        if self._stop_event.is_set():
            return
        with self._pause_lock:
            paused = self._paused
        if paused:
            return
        if not self._open_stream():
            self._stop_event.set()
            self._playing = False
            self._notify_track_end()

    def _stream_callback(
        self,
        out: object,
        frames: int,
        _time: object,
        _status: object,
    ) -> None:
        chunk_size = frames * 2  # int16 = 2 bytes per sample

        with self._pause_lock:
            if self._paused:
                out[:chunk_size] = bytes(chunk_size)  # type: ignore[index]
                return

        buf = bytearray(chunk_size)
        pos = 0
        while pos < chunk_size:
            try:
                chunk = self._pcm_queue.get_nowait()
                use = min(chunk_size - pos, len(chunk))
                buf[pos : pos + use] = chunk[:use]
                if use < len(chunk):
                    try:
                        self._pcm_queue.put_nowait(chunk[use:])
                    except queue.Full:
                        pass
                pos += use
            except queue.Empty:
                break  # rest stays silence-filled

        out[:chunk_size] = bytes(buf)  # type: ignore[index]

    def _open_stream(self) -> bool:
        """Open the output stream for the current track if it is not already active."""
        if self._stop_event.is_set():
            return False
        blocksize = self._stream_blocksize
        if blocksize is None:
            return False

        with self._stream_lock:
            if self._stream is not None:
                return True
            try:
                stream = sd.RawOutputStream(
                    samplerate=_SAMPLE_RATE,
                    channels=1,
                    dtype="int16",
                    blocksize=blocksize,
                    latency="high",
                    callback=self._stream_callback,
                )
                self._stream = stream
                stream.start()
                return True
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("Failed to open audio stream: %s", exc)
                self._stream = None
                return False

    def _close_stream(self) -> None:
        """Stop and release the active output stream."""
        with self._stream_lock:
            if self._stream is None:
                return
            stream = self._stream
            self._stream = None
        try:
            stream.stop()  # type: ignore[union-attr]
            stream.close()  # type: ignore[union-attr]
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug("Stream cleanup error: %s", exc)

    def _enqueue_pcm(self, pcm: bytes, frame_duration: float) -> bool:
        """Push one rendered frame without long blocking in the daemon process."""
        wait_s = min(frame_duration * 0.5, 0.05)
        while not self._stop_event.is_set():
            if not self._resume_event.is_set():
                return False
            try:
                self._pcm_queue.put_nowait(pcm)
                return True
            except queue.Full:
                self._stop_event.wait(wait_s)
        return False

    def _emulation_loop(self, header: SIDHeader) -> None:
        """Background thread: emulate CPU + SID and push PCM chunks to the queue."""
        pal = is_pal(header)
        frame_rate = 50.0 if pal else 60.0
        frame_duration = 1.0 / frame_rate

        subtune = max(0, header.start_song - 1)
        speed = speed_for_subtune(header, subtune)
        if speed == "CIA":
            logger.warning("CIA-timer subtune: using VBI frame rate as fallback")

        try:
            driver = SIDDriver(header)
            renderer = SIDRenderer(
                sample_rate=_SAMPLE_RATE,
                pal=pal,
                volume=self._volume,
            )
            driver.init_tune(subtune)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("SID init failed: %s", exc)
            self._playing = False
            self._notify_track_end()
            return

        playback_elapsed = 0.0
        while not self._stop_event.is_set():
            if not self._resume_event.wait(timeout=0.1):
                continue
            if self._stop_event.is_set():
                break
            if playback_elapsed >= self._max_track_duration:
                logger.debug("ChipTunes: max track duration reached, advancing to next track")
                break
            try:
                writes = driver.play_frame()
                pcm = renderer.render_frame(writes, frame_duration)
                playback_elapsed += frame_duration
                if not self._enqueue_pcm(pcm, frame_duration):
                    continue
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("Emulation error (skipping track): %s", exc)
                break
            # Adaptive pacing: run flat-out when buffer is low, yield CPU when healthy.
            # This prevents 100% CPU usage from starving the audio callback thread.
            qsize = self._pcm_queue.qsize()
            if qsize > _QUEUE_MAX_CHUNKS // 2:
                self._stop_event.wait(frame_duration)
            elif qsize > _QUEUE_MAX_CHUNKS // 4:
                self._stop_event.wait(frame_duration * 0.5)

        self._playing = False
        if not self._stop_event.is_set():
            self._notify_track_end()

    def stop(self) -> None:
        """Stop playback and clean up resources."""
        self._stop_event.set()
        self._resume_event.set()
        self._playing = False
        self._paused = False
        self._stream_blocksize = None

        self._close_stream()

        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                logger.warning("Emulation thread did not exit within 2s — orphaned")
            self._thread = None

        # Drain queue
        while not self._pcm_queue.empty():
            try:
                self._pcm_queue.get_nowait()
            except queue.Empty:
                break

    def pause(self) -> None:
        """Pause playback without advancing emulation time."""
        with self._pause_lock:
            if self._paused:
                return
            self._paused = True
            self._resume_event.clear()
        self._close_stream()

    def resume(self) -> None:
        """Resume playback after a pause."""
        with self._pause_lock:
            if not self._paused:
                return
            self._paused = False
        should_reopen = (
            self._playing
            and not self._stop_event.is_set()
            and self._stream is None
            and self._stream_blocksize is not None
        )
        if should_reopen and not self._open_stream():
            logger.warning("Failed to reopen audio stream on resume — stopping track")
            self.stop()
            return
        self._resume_event.set()

    def _notify_track_end(self) -> None:
        if self.on_track_end is not None:
            try:
                self.on_track_end()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("on_track_end callback error: %s", exc)
