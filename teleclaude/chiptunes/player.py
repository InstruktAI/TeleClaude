"""ChipTunes streaming player — drives 6502 emulation and routes PCM to sounddevice."""

from __future__ import annotations

import ctypes
import queue
import threading
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
_QUEUE_MAX_CHUNKS = 200  # maximum queue depth (~200 frames at 50Hz ≈ 4s)
_SAMPLE_RATE = 48000


class ChiptunesPlayer:  # pylint: disable=too-many-instance-attributes
    """Plays a SID file in a background thread via sounddevice."""

    def __init__(self, volume: float = 0.5) -> None:
        self._volume = max(0.0, min(1.0, volume))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream: object | None = None  # sounddevice.RawOutputStream
        self._pcm_queue: queue.Queue[bytes] = queue.Queue(maxsize=_QUEUE_MAX_CHUNKS)
        self._playing = False
        self._paused = False
        self._pause_lock = threading.Lock()
        self.on_track_end: Callable[[], None] | None = None

    @property
    def is_playing(self) -> bool:
        """Return True if playback is active and not stopped."""
        return self._playing and not self._stop_event.is_set()

    def play(self, sid_path: Path) -> None:
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
        self._paused = False
        self._pcm_queue = queue.Queue(maxsize=_QUEUE_MAX_CHUNKS)

        self._thread = threading.Thread(
            target=self._emulation_loop,
            args=(header,),
            daemon=True,
            name="chiptunes-emulator",
        )
        self._thread.start()

        # Wait until pre-buffer is filled before opening the audio stream
        self._start_stream_after_prebuffer(header)

    def _start_stream_after_prebuffer(self, header: SIDHeader) -> None:
        """Wait for pre-buffer, then open the sounddevice stream."""
        pal = is_pal(header)
        frame_rate = 50.0 if pal else 60.0
        frame_duration = 1.0 / frame_rate
        samples_per_frame = int(_SAMPLE_RATE * frame_duration)
        prebuffer_frames = int(_PREBUFFER_SECONDS * frame_rate)

        # Block until enough frames are buffered or stop is signalled
        waited = 0
        while waited < prebuffer_frames and not self._stop_event.is_set():
            if self._pcm_queue.qsize() >= prebuffer_frames:
                break
            threading.Event().wait(0.05)
            waited += 1

        if self._stop_event.is_set():
            return

        def _callback(
            out: object,
            frames: int,
            _time: object,
            _status: object,
        ) -> None:
            with self._pause_lock:
                if self._paused:
                    # Write silence when paused
                    if hasattr(out, "write"):
                        out.write(bytes(frames * 2))  # type: ignore[union-attr]
                    else:
                        ctypes.memmove(out, bytes(frames * 2), frames * 2)  # type: ignore[arg-type]
                    return

            chunk_size = frames * 2
            buf = bytearray(chunk_size)
            pos = 0
            while pos < chunk_size:
                needed = chunk_size - pos
                try:
                    chunk = self._pcm_queue.get_nowait()
                    use = min(needed, len(chunk))
                    buf[pos : pos + use] = chunk[:use]
                    if use < len(chunk):
                        # Put remainder back (best-effort: drop if full)
                        try:
                            self._pcm_queue.put_nowait(chunk[use:])
                        except queue.Full:
                            pass
                    pos += use
                except queue.Empty:
                    break  # Fill rest with silence

            if hasattr(out, "write"):
                out.write(bytes(buf))  # type: ignore[union-attr]
            else:
                ctypes.memmove(out, bytes(buf), chunk_size)  # type: ignore[arg-type]

        try:
            stream = sd.RawOutputStream(
                samplerate=_SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=samples_per_frame,
                callback=_callback,
            )
            self._stream = stream
            stream.start()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Failed to open audio stream: %s", exc)
            self._playing = False
            self._notify_track_end()

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

        while not self._stop_event.is_set():
            try:
                writes = driver.play_frame()
                pcm = renderer.render_frame(writes, frame_duration)
                try:
                    self._pcm_queue.put(pcm, timeout=1.0)
                except queue.Full:
                    # Drain one old frame to make room
                    try:
                        self._pcm_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._pcm_queue.put_nowait(pcm)
                    except queue.Full:
                        pass
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("Emulation error (skipping track): %s", exc)
                break

        self._playing = False
        if not self._stop_event.is_set():
            self._notify_track_end()

    def stop(self) -> None:
        """Stop playback and clean up resources."""
        self._stop_event.set()
        self._playing = False

        if self._stream is not None:
            try:
                stream = self._stream
                self._stream = None
                stream.stop()  # type: ignore[union-attr]
                stream.close()  # type: ignore[union-attr]
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.debug("Stream cleanup error: %s", exc)

        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        # Drain queue
        while not self._pcm_queue.empty():
            try:
                self._pcm_queue.get_nowait()
            except queue.Empty:
                break

    def pause(self) -> None:
        """Pause audio output (write silence to stream)."""
        with self._pause_lock:
            self._paused = True

    def resume(self) -> None:
        """Resume audio output after a pause."""
        with self._pause_lock:
            self._paused = False

    def _notify_track_end(self) -> None:
        if self.on_track_end is not None:
            try:
                self.on_track_end()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("on_track_end callback error: %s", exc)
