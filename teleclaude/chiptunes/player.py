"""ChipTunes streaming player — drives 6502 emulation and routes PCM to sounddevice."""

from __future__ import annotations

import array
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.chiptunes.sid_cpu import SIDDriver
from teleclaude.chiptunes.sid_parser import SIDHeader, is_pal, parse_sid_file
from teleclaude.chiptunes.sid_renderer import SIDRenderer

try:
    import sounddevice as sd

    _sounddevice_available = True
except ImportError:
    _sounddevice_available = False
    sd = None

logger = get_logger(__name__)

_PREBUFFER_SECONDS = 1.0  # seconds of audio pre-buffered before stream starts (emulation runs ~9x realtime)
_QUEUE_MAX_CHUNKS = 200  # maximum queue depth (each chunk is a batch of frames)
_BATCH_FRAMES = 25  # render 25 frames (~500ms at 50Hz) per queue chunk to reduce GIL contention
_SAMPLE_RATE = 48000
_DEVICE_POLL_INTERVAL_S = 2.0  # how often to check for default output device changes
_FADE_DURATION_S = 3.0  # fade-out window before track end


def _apply_fade(pcm: bytes, factor: float) -> bytes:
    """Scale all int16 samples by factor (0.0-1.0)."""
    samples = array.array("h")
    samples.frombytes(pcm)
    samples = array.array("h", [int(s * factor) for s in samples])
    return samples.tobytes()


def _reinitialize_portaudio() -> bool:
    """Re-enumerate audio devices by cycling PortAudio.

    sounddevice caches the device list when PortAudio first initializes. A
    long-lived process that outlives a default-device change (headphones
    unplugged, output switched) keeps seeing the old devices, so opening a
    stream fails — on macOS with CoreAudio -10851 / PortAudio -9986, and the
    open can hang rather than raise. Terminating and re-initializing PortAudio
    forces a fresh device enumeration against the current hardware.
    """
    if not _sounddevice_available:
        return False
    try:
        sd._terminate()  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType]
        sd._initialize()  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType]
        return True
    except Exception as exc:
        logger.warning("PortAudio reinitialize failed: %s", exc)
        return False


def _get_default_output_device() -> int | None:  # used by ChiptunesPlayer._open_stream and _device_monitor_loop
    """Return the current default output device index, or None on failure."""
    if not _sounddevice_available:
        return None
    try:
        raw: object = sd.default.device  # pyright: ignore[reportUnknownMemberType]
        if isinstance(raw, tuple | list):  # pyright: ignore[reportUnnecessaryIsInstance]
            val = raw[1]
            return int(val) if val is not None else None
        return int(str(raw)) if raw is not None else None
    except Exception:
        return None


class ChiptunesPlayer:
    """Plays a SID file in a background thread via sounddevice."""

    def __init__(self, volume: float = 1.0) -> None:
        self._volume = max(0.0, min(1.0, volume))
        self._stop_event = threading.Event()
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._thread: threading.Thread | None = None
        self._stream: object | None = None  # sounddevice.RawOutputStream
        self._stream_blocksize: int | None = None
        self._last_track_end_reason: str | None = None
        self._stream_lock = threading.RLock()
        self._pcm_queue: queue.Queue[bytes] = queue.Queue(maxsize=_QUEUE_MAX_CHUNKS)
        self._callback_remainder = b""
        self._status_log_interval_s = 2.0
        self._last_status_log_ts = 0.0
        self._suppressed_status_logs = 0
        self._playing = False
        self._paused = False
        self._pause_lock = threading.Lock()
        self._playback_position_seconds = 0.0
        self._position_lock = threading.Lock()
        self.on_track_end: Callable[[str | None], None] | None = None
        self._stream_device_id: int | None = None
        self._device_monitor_thread: threading.Thread | None = None
        self._max_duration: float | None = None

    @property
    def is_playing(self) -> bool:
        """Return True if playback is actively advancing and audible."""
        return self._playing and not self._stop_event.is_set() and not self._paused

    @property
    def is_paused(self) -> bool:
        """Return True if playback is loaded but currently paused."""
        return self._paused and not self._stop_event.is_set()

    @property
    def track_end_reason(self) -> str | None:
        """Return the last track-end reason for diagnostics."""
        return self._last_track_end_reason

    @property
    def playback_position_seconds(self) -> float:
        """Current playback position within the active track."""
        with self._position_lock:
            return self._playback_position_seconds

    def play(
        self,
        sid_path: Path,
        *,
        start_paused: bool = False,
        start_position_seconds: float = 0.0,
        max_duration: float | None = None,
    ) -> None:
        """Parse and start playing a SID file in the background."""
        if not _sounddevice_available:
            raise ImportError(
                "sounddevice is required for audio playback. Install it with: pip install 'teleclaude[chiptunes]'"
            )
        self.stop()

        self._last_track_end_reason = None

        try:
            header = parse_sid_file(sid_path)
        except Exception as exc:
            logger.warning("Failed to parse SID file %s: %s", sid_path, exc)
            self._notify_track_end("sid_parse_failed")
            return

        self._stop_event.clear()
        self._playing = True
        self._paused = start_paused
        with self._position_lock:
            self._playback_position_seconds = max(0.0, start_position_seconds)
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
        self._callback_remainder = b""
        self._max_duration = max_duration

        self._thread = threading.Thread(
            target=self._emulation_loop,
            args=(header, max(0.0, start_position_seconds), max_duration),
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
        # Each queue item is a batch of _BATCH_FRAMES frames
        prebuffer_chunks = max(1, int(_PREBUFFER_SECONDS * frame_rate / _BATCH_FRAMES))

        # Block until enough chunks are buffered or stop is signalled
        deadline = time.monotonic() + _PREBUFFER_SECONDS
        while time.monotonic() < deadline and not self._stop_event.is_set():
            if self._pcm_queue.qsize() >= prebuffer_chunks:
                break
            self._stop_event.wait(0.05)

        if self._stop_event.is_set():
            logger.debug("ChipTunes: prebuffer aborted (stop event)")
            return
        buffered = self._pcm_queue.qsize()
        if buffered < prebuffer_chunks:
            logger.warning(
                "ChipTunes: prebuffer incomplete (%d/%d chunks) — opening stream anyway", buffered, prebuffer_chunks
            )
        else:
            logger.debug("ChipTunes: prebuffer complete (%d chunks), opening stream", buffered)
        with self._pause_lock:
            paused = self._paused
        if paused:
            logger.debug("ChipTunes: skipping stream open (paused during prebuffer)")
            return
        if not self._open_stream():
            logger.error("ChipTunes: stream open failed after prebuffer — stopping track")
            self._stop_event.set()
            self._playing = False
            self._notify_track_end("stream_open_failed")
        else:
            logger.info("ChipTunes: audio stream opened, playback active")

    def _stream_callback(
        self,
        out: object,
        frames: int,
        _time: object,
        status: object,
    ) -> None:
        chunk_size = frames * 2  # int16 = 2 bytes per sample

        with self._pause_lock:
            if self._paused:
                out[:chunk_size] = bytes(chunk_size)  # type: ignore[index]
                return

        self._log_stream_status(status)
        out_view = memoryview(out)[:chunk_size]  # type: ignore[arg-type]
        pos = 0

        # Consume any carry-over first to preserve strict FIFO sample ordering.
        if self._callback_remainder:
            use = min(chunk_size, len(self._callback_remainder))
            out_view[:use] = self._callback_remainder[:use]
            pos += use
            self._callback_remainder = self._callback_remainder[use:]

        while pos < chunk_size:
            try:
                chunk = self._pcm_queue.get_nowait()
                use = min(chunk_size - pos, len(chunk))
                out_view[pos : pos + use] = chunk[:use]
                if use < len(chunk):
                    self._callback_remainder += chunk[use:]
                pos += use
            except queue.Empty:
                break  # rest stays silence-filled

        if pos < chunk_size:
            out_view[pos:chunk_size] = b"\x00" * (chunk_size - pos)

    def _log_stream_status(self, status: object) -> None:
        """Log callback status flags with throttling to avoid log spam."""
        flags = self._status_flags(status)
        if not flags:
            return
        now = time.monotonic()
        if now - self._last_status_log_ts < self._status_log_interval_s:
            self._suppressed_status_logs += 1
            return
        if self._suppressed_status_logs > 0:
            logger.warning(
                "ChipTunes: stream callback status=%s (suppressed=%d)",
                ",".join(flags),
                self._suppressed_status_logs,
            )
            self._suppressed_status_logs = 0
        else:
            logger.warning("ChipTunes: stream callback status=%s", ",".join(flags))
        self._last_status_log_ts = now

    @staticmethod
    def _status_flags(status: object) -> list[str]:
        names = [
            "output_underflow",
            "output_overflow",
            "input_underflow",
            "input_overflow",
            "priming_output",
        ]
        flags = [name for name in names if bool(getattr(status, name, False))]
        if flags:
            return flags
        if bool(status):
            return [str(status)]
        return []

    def _open_stream(self) -> bool:
        """Open the output stream for the current track if it is not already active."""
        blocksize = self._stream_blocksize
        if blocksize is None:
            return False

        with self._stream_lock:
            if self._stop_event.is_set():
                return False
            if self._stream is not None:
                return True
            # First attempt uses the cached device list; on failure, re-enumerate
            # PortAudio devices once and retry — recovers from a stale default
            # device after the process outlives a hardware change.
            for attempt in range(2):
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
                    self._stream_device_id = _get_default_output_device()
                    stream.start()
                    self._start_device_monitor()
                    return True
                except Exception as exc:
                    logger.error("Failed to open audio stream (attempt %d/2): %s", attempt + 1, exc)
                    self._stream = None
                    if attempt == 0 and _reinitialize_portaudio():
                        continue
                    return False
            return False

    def _close_stream(self) -> None:
        """Stop and release the active output stream."""
        with self._stream_lock:
            if self._stream is None:
                return
            stream = self._stream
            self._stream = None
            self._stream_device_id = None
        try:
            stream.stop()  # type: ignore
            stream.close()  # type: ignore
        except Exception as exc:
            logger.debug("Stream cleanup error: %s", exc)

    def _start_device_monitor(self) -> None:
        """Start the default-device polling thread if not already running."""
        if self._device_monitor_thread is not None and self._device_monitor_thread.is_alive():
            return
        self._device_monitor_thread = threading.Thread(
            target=self._device_monitor_loop,
            daemon=True,
            name="chiptunes-device-monitor",
        )
        self._device_monitor_thread.start()

    def _device_monitor_loop(self) -> None:
        """Poll for default output device changes and reopen the stream when needed."""
        while not self._stop_event.wait(_DEVICE_POLL_INTERVAL_S):
            with self._pause_lock:
                if self._paused:
                    continue
            with self._stream_lock:
                if self._stream is None:
                    continue
                current_default = _get_default_output_device()
                if current_default is None or current_default == self._stream_device_id:
                    continue
                logger.info(
                    "Default output device changed (%s -> %s), reopening audio stream",
                    self._stream_device_id,
                    current_default,
                )
                old_stream = self._stream
                self._stream = None
            # Close old stream outside the lock
            try:
                old_stream.stop()  # type: ignore
                old_stream.close()  # type: ignore
            except Exception as exc:
                logger.debug("Old stream cleanup on device switch: %s", exc)
            # Re-enumerate devices before reopening: PortAudio's cached list still
            # points at the old default, so opening directly would fail or hang.
            _reinitialize_portaudio()
            # Open new stream on the new default device
            if not self._open_stream():
                logger.warning("Failed to reopen stream after device change")

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

    def _emulation_loop(  # noqa: C901 # TODO: refactor to reduce complexity
        self,
        header: SIDHeader,
        start_position_seconds: float = 0.0,
        max_duration: float | None = None,
    ) -> None:
        """Background thread: emulate CPU + SID and push PCM chunks to the queue."""
        pal = is_pal(header)
        subtune = max(0, header.start_song - 1)

        try:
            driver = SIDDriver(header)
            renderer = SIDRenderer(
                sample_rate=_SAMPLE_RATE,
                pal=pal,
                volume=self._volume,
            )
            # Init-time writes set master volume / filter / voice state that some
            # tunes configure only once; replay them into the renderer so they
            # are not rendered silent after the opening envelope decays.
            renderer.apply_writes(driver.init_tune(subtune))
            frame_rate = driver.frame_rate(pal)
            frame_duration = 1.0 / frame_rate
            logger.debug("ChipTunes: emulation started (subtune=%d, pal=%s, frame_rate=%.3f)", subtune, pal, frame_rate)
        except Exception as exc:
            logger.error("SID init failed: %s", exc)
            self._playing = False
            self._notify_track_end("init_failed")
            return

        playback_elapsed = 0.0
        if start_position_seconds > 0.0:
            target_frames = int(start_position_seconds / frame_duration)
            for _ in range(target_frames):
                if self._stop_event.is_set():
                    break
                driver.play_frame()
                playback_elapsed += frame_duration
            with self._position_lock:
                self._playback_position_seconds = playback_elapsed

        while not self._stop_event.is_set():
            if not self._resume_event.wait(timeout=0.1):
                continue
            if self._stop_event.is_set():
                break
            try:
                # Batch-render multiple frames into one PCM chunk to reduce
                # GIL contention between the emulation thread and the audio
                # callback thread. Each queue item is ~500ms of audio.
                batch_pcm = bytearray()
                done = False
                for _ in range(_BATCH_FRAMES):
                    if self._stop_event.is_set():
                        done = True
                        break
                    writes = driver.play_frame()
                    pcm = renderer.render_frame(writes, frame_duration)
                    if max_duration:  # 0.0 / None both mean "no listed duration" — never auto-fade
                        fade_start = max_duration  # fade AFTER the listed duration, not before
                        if playback_elapsed >= fade_start:
                            factor = max(0.0, 1.0 - (playback_elapsed - fade_start) / _FADE_DURATION_S)
                            if factor <= 0.0:
                                print(
                                    f"[CHIPTUNES] FADE COMPLETE: "
                                    f"elapsed={playback_elapsed:.1f}s max_duration={max_duration}",
                                    flush=True,
                                )
                                done = True
                                break
                            pcm = _apply_fade(pcm, factor)
                    batch_pcm.extend(pcm)
                    playback_elapsed += frame_duration
                    with self._position_lock:
                        self._playback_position_seconds = playback_elapsed
                if done and not batch_pcm:
                    break
                if batch_pcm:
                    if not self._enqueue_pcm(bytes(batch_pcm), frame_duration * _BATCH_FRAMES):
                        pass
                if done:
                    break
            except Exception as exc:
                print(f"[CHIPTUNES] EMULATION ERROR: {exc}", flush=True)
                logger.warning("Emulation error (skipping track): %s", exc)
                self._notify_track_end("emulation_error")
                break
            # Adaptive pacing: yield CPU when buffer is healthy.
            qsize = self._pcm_queue.qsize()
            if qsize > _QUEUE_MAX_CHUNKS // 2:
                self._stop_event.wait(frame_duration * _BATCH_FRAMES)
            elif qsize > _QUEUE_MAX_CHUNKS // 4:
                self._stop_event.wait(frame_duration * _BATCH_FRAMES * 0.5)

        self._playing = False
        reason = self._last_track_end_reason or ("stopped" if self._stop_event.is_set() else "track_completed")
        print(
            f"[CHIPTUNES] END: reason={reason} elapsed={playback_elapsed:.1f}s max_duration={max_duration}", flush=True
        )
        if not self._stop_event.is_set() and self._last_track_end_reason is None:
            self._notify_track_end("track_completed")

    def stop(self) -> None:
        """Stop playback and clean up resources."""
        self._stop_event.set()
        self._resume_event.set()
        self._playing = False
        self._paused = False
        self._stream_blocksize = None
        self._callback_remainder = b""
        with self._position_lock:
            self._playback_position_seconds = 0.0

        self._close_stream()

        # Wait for device monitor to exit (it checks _stop_event)
        if self._device_monitor_thread is not None:
            self._device_monitor_thread.join(timeout=_DEVICE_POLL_INTERVAL_S + 1.0)
            self._device_monitor_thread = None

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
        if should_reopen:
            if not self._open_stream():
                logger.warning("Failed to reopen audio stream on resume — stopping track")
                self.stop()
                return
            logger.debug("ChipTunes: stream reopened on resume")
        self._resume_event.set()
        logger.debug("ChipTunes: resumed playback")

    def _notify_track_end(self, reason: str | None = None) -> None:
        self._last_track_end_reason = reason
        if self.on_track_end is not None:
            try:
                self.on_track_end(reason)
            except Exception as exc:
                logger.warning("on_track_end callback error: %s", exc)
