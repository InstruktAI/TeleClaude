"""TelecAppMediaMixin — animation, TTS, and ChipTunes management."""

from __future__ import annotations

import asyncio

from instrukt_ai_logging import get_logger
from textual import work

from teleclaude.cli.models import ChiptunesStatusInfo
from teleclaude.cli.tui.widgets.banner import Banner
from teleclaude.cli.tui.widgets.box_tab_bar import BoxTabBar
from teleclaude.cli.tui.widgets.telec_footer import TelecFooter

logger = get_logger(__name__)


class TelecAppMediaMixin:
    """Animation engine, TTS, and ChipTunes management."""

    # --- Animation and TTS keyboard actions ---

    def action_cycle_animation(self) -> None:
        """a: cycle animation mode (off → periodic → party → off)."""
        cycle = ["off", "periodic", "party"]
        status_bar = self.query_one("#telec-footer", TelecFooter)  # type: ignore[attr-defined]
        idx = cycle.index(status_bar.animation_mode) if status_bar.animation_mode in cycle else 0
        new_mode = cycle[(idx + 1) % len(cycle)]
        self._cycle_animation(new_mode)

    def _force_spawn_sky(self, sprite: object | None = None) -> None:
        """Force-spawn a sky entity (or random if sprite is None)."""
        from teleclaude.cli.tui.animations.general import GlobalSky

        slot = self._animation_engine._targets.get("header")  # type: ignore[attr-defined]
        if slot and isinstance(slot.animation, GlobalSky):
            slot.animation.force_spawn(sprite)

    def action_spawn_ufo(self) -> None:
        """u: force a UFO to spawn in the sky animation."""
        from teleclaude.cli.tui.animations.sprites.ufo import UFO_SPRITE

        self._force_spawn_sky(UFO_SPRITE)

    def action_spawn_car(self) -> None:
        """c: force a car to spawn in the sky animation."""
        from teleclaude.cli.tui.animations.sprites.cars import CAR_SPRITE

        self._force_spawn_sky(CAR_SPRITE)

    def action_toggle_tts(self) -> None:
        """v: toggle TTS on/off.

        Key choice: 's' was considered but conflicts irreconcilably with
        PreparationView's 'start_work' binding enabled on all todo/project/file
        nodes. 'v' (Voice) is used instead.
        """
        self._toggle_tts()

    def action_chiptunes_play_pause(self) -> None:
        """m: play/pause ChipTunes."""
        self._chiptunes_play_pause()

    # --- TTS toggle ---

    @work(exclusive=True, group="settings")
    async def _toggle_tts(self) -> None:
        """Toggle TTS on/off via API."""
        from teleclaude.cli.models import SettingsPatchInfo, TTSSettingsPatchInfo

        new_val = not self.query_one("#telec-footer", TelecFooter).tts_enabled  # type: ignore[attr-defined]
        try:
            await self.api.patch_settings(SettingsPatchInfo(tts=TTSSettingsPatchInfo(enabled=new_val)))  # type: ignore[attr-defined]
            status_bar = self.query_one("#telec-footer", TelecFooter)  # type: ignore[attr-defined]
            status_bar.tts_enabled = new_val
        except Exception as e:
            self.notify(f"Failed to toggle TTS: {e}", severity="error")  # type: ignore[attr-defined]

    # --- ChipTunes player controls ---

    @work(exclusive=False, group="settings")
    async def _chiptunes_play_pause(self) -> None:
        """Play/pause toggle: resume/enable if cold or paused, else pause.

        Uses optimistic local updates for instant visual feedback.
        ChiptunesStateEvent WS broadcasts correct state eventually.
        """
        footer = self.query_one("#telec-footer", TelecFooter)  # type: ignore[attr-defined]

        # Sync fresh state from daemon before deciding pause vs resume
        try:
            await self._sync_chiptunes_footer_state()
        except Exception:
            pass  # proceed with cached state if sync fails
        try:
            if footer.chiptunes_playing:
                footer.chiptunes_playing = False
                receipt = await self.api.chiptunes_pause()  # type: ignore[attr-defined]
            else:
                footer.chiptunes_playing = True
                receipt = await self.api.chiptunes_resume()  # type: ignore[attr-defined]
            self._apply_chiptunes_receipt(receipt.command_id, receipt.action)
            self._schedule_chiptunes_reconcile()
        except Exception as e:
            self.notify(f"Failed to pause/resume: {e}", severity="error")  # type: ignore[attr-defined]

    @work(exclusive=False, group="settings")
    async def _chiptunes_next(self) -> None:
        """Skip to the next chiptunes track."""
        footer = self.query_one("#telec-footer", TelecFooter)  # type: ignore[attr-defined]
        if not footer.chiptunes_loaded:
            return
        try:
            receipt = await self.api.chiptunes_next()  # type: ignore[attr-defined]
            self._apply_chiptunes_receipt(receipt.command_id, receipt.action)
            self._schedule_chiptunes_reconcile()
        except Exception as e:
            self.notify(f"Failed to skip track: {e}", severity="error")  # type: ignore[attr-defined]

    @work(exclusive=False, group="settings")
    async def _chiptunes_prev(self) -> None:
        """Go back to the previous chiptunes track."""
        footer = self.query_one("#telec-footer", TelecFooter)  # type: ignore[attr-defined]
        if not footer.chiptunes_loaded:
            return
        try:
            receipt = await self.api.chiptunes_prev()  # type: ignore[attr-defined]
            self._apply_chiptunes_receipt(receipt.command_id, receipt.action)
            self._schedule_chiptunes_reconcile()
        except Exception as e:
            self.notify(f"Failed to go to previous track: {e}", severity="error")  # type: ignore[attr-defined]

    def _apply_chiptunes_footer_state(
        self,
        *,
        loaded: bool,
        playback: str,
        state_version: int | None,
        playing: bool,
        track: str,
        sid_path: str,
        pending_command_id: str,
        pending_action: str,
    ) -> None:
        from teleclaude.chiptunes.favorites import is_favorited

        if state_version is not None and state_version < self._chiptunes_state_version:  # type: ignore[attr-defined]
            return
        if state_version is not None:
            self._chiptunes_state_version = state_version  # type: ignore[attr-defined]

        footer = self.query_one("#telec-footer", TelecFooter)  # type: ignore[attr-defined]
        footer.chiptunes_loaded = loaded
        footer.chiptunes_playback = playback
        footer.chiptunes_playing = playing
        footer.chiptunes_track = track
        footer.chiptunes_sid_path = sid_path
        footer.chiptunes_pending_command_id = pending_command_id
        footer.chiptunes_pending_action = pending_action
        footer.chiptunes_favorited = is_favorited(sid_path) if sid_path else False

    def _apply_chiptunes_status(self, status: ChiptunesStatusInfo) -> None:
        self._apply_chiptunes_footer_state(
            loaded=bool(getattr(status, "loaded", False)),
            playback=str(getattr(status, "playback", "cold")),
            state_version=int(getattr(status, "state_version", 0)),
            playing=bool(getattr(status, "playing", False)),
            track=str(getattr(status, "track", "")),
            sid_path=str(getattr(status, "sid_path", "")),
            pending_command_id=str(getattr(status, "pending_command_id", "")),
            pending_action=str(getattr(status, "pending_action", "")),
        )

    def _apply_chiptunes_receipt(self, command_id: str, action: str) -> None:
        footer = self.query_one("#telec-footer", TelecFooter)  # type: ignore[attr-defined]
        footer.chiptunes_pending_command_id = command_id
        footer.chiptunes_pending_action = action
        if action in {"resume", "next", "prev"}:
            footer.chiptunes_playback = "loading"

    def _schedule_chiptunes_reconcile(self) -> None:
        async def _reconcile() -> None:
            await asyncio.sleep(0.2)
            try:
                await self._sync_chiptunes_footer_state()
            except Exception:
                logger.debug("ChipTunes reconcile sync failed", exc_info=True)

        asyncio.create_task(_reconcile())

    async def _sync_chiptunes_footer_state(self) -> None:
        status = await self.api.get_chiptunes_status()  # type: ignore[attr-defined]
        self._apply_chiptunes_status(status)

    @work(exclusive=False, group="settings")
    async def _chiptunes_favorite(self) -> None:
        """Toggle the current track in favorites."""
        footer = self.query_one("#telec-footer", TelecFooter)  # type: ignore[attr-defined]
        if not footer.chiptunes_loaded:
            return
        if not footer.chiptunes_sid_path:
            return
        from teleclaude.chiptunes.favorites import is_favorited, remove_favorite, save_favorite

        sid_path = footer.chiptunes_sid_path
        track = footer.chiptunes_track

        already_favorited = await asyncio.to_thread(is_favorited, sid_path)
        if already_favorited:
            try:
                removed = await asyncio.to_thread(remove_favorite, sid_path)
            except OSError as e:
                self.notify(f"Failed to remove favorite: {e}", severity="error")  # type: ignore[attr-defined]
                return

            if removed:
                footer.chiptunes_favorited = False
                self.notify("Removed from favorites")  # type: ignore[attr-defined]
            return

        try:
            await asyncio.to_thread(save_favorite, track, sid_path)
        except OSError as e:
            self.notify(f"Failed to save favorite: {e}", severity="error")  # type: ignore[attr-defined]
            return

        footer.chiptunes_favorited = True
        self.notify("⭐ Added to favorites")  # type: ignore[attr-defined]

    # --- Banner compactness ---

    def _update_banner_compactness(self, num_stickies: int) -> None:
        """Switch between full banner (6-line) and compact logo (3-line).

        Uses sticky count (not preview) to avoid flickering on every click.
        Compact at 4 or 6 total panes (2x2 and 3x2 grids) where the TUI
        pane is small enough that vertical space matters.
        """
        banner_panes = 1 + num_stickies  # TUI + stickies (preview excluded)
        is_compact = banner_panes in (4, 6)
        try:
            self.query_one(Banner).is_compact = is_compact  # type: ignore[attr-defined]
        except Exception:
            pass

    # --- Animation management ---

    def _start_animation_mode(self, mode: str) -> None:
        """Configure ambient sky and banner cadence for the given mode."""
        from teleclaude.cli.tui.animation_triggers import ActivityTrigger, PeriodicTrigger

        self._stop_banner_animation()

        self._animation_engine.is_enabled = True  # type: ignore[attr-defined]
        self._animation_engine.animation_mode = mode  # type: ignore[attr-defined]

        self._ensure_header_sky(show_extra_motion=mode != "off")

        if mode in ("periodic", "party"):
            interval = 10 if mode == "party" else 60
            trigger = PeriodicTrigger(self._animation_engine, interval_sec=interval)  # type: ignore[attr-defined]
            trigger.task = asyncio.ensure_future(trigger.start())
            self._periodic_trigger = trigger  # type: ignore[attr-defined]

        if mode == "party":
            self._activity_trigger = ActivityTrigger(self._animation_engine)  # type: ignore[attr-defined]

        if self._animation_timer is None:  # type: ignore[attr-defined]
            # Start the render tick interval (~250ms — balances smoothness vs terminal output volume)
            self._animation_timer = self.set_interval(0.25, self._animation_tick)  # type: ignore[attr-defined]

    def _ensure_header_sky(
        self,
        *,
        show_extra_motion: bool,
    ) -> None:
        from teleclaude.cli.tui.animation_colors import palette_registry
        from teleclaude.cli.tui.animation_engine import AnimationPriority
        from teleclaude.cli.tui.animations.general import GlobalSky

        header_slot = self._animation_engine._targets.get("header")  # type: ignore[attr-defined]
        existing = header_slot.animation if header_slot is not None else None
        if isinstance(existing, GlobalSky):
            existing.set_extra_motion(show_extra_motion)
            existing.animation_mode = self._animation_engine.animation_mode  # type: ignore[attr-defined]
            self._animation_engine.set_looping("header", True)  # type: ignore[attr-defined]
            return

        sky = GlobalSky(
            palette=palette_registry.get("spectrum"),
            is_big=True,
            duration_seconds=3600,
            show_extra_motion=show_extra_motion,
        )
        self._animation_engine.play(sky, priority=AnimationPriority.PERIODIC, target="header")  # type: ignore[attr-defined]
        self._animation_engine.set_looping("header", True)  # type: ignore[attr-defined]

    def _stop_banner_animation(self) -> None:
        """Stop banner/logo effects while leaving the ambient sky scene intact."""
        from teleclaude.cli.tui.animation_triggers import PeriodicTrigger

        if isinstance(self._periodic_trigger, PeriodicTrigger):  # type: ignore[attr-defined]
            self._periodic_trigger.stop()  # type: ignore[attr-defined]
        self._periodic_trigger = None  # type: ignore[attr-defined]
        self._activity_trigger = None  # type: ignore[attr-defined]

        self._animation_engine.stop_target("banner")  # type: ignore[attr-defined]
        self._animation_engine.stop_target("logo")  # type: ignore[attr-defined]

    def _stop_animation(self) -> None:
        """Stop all animation output, including the ambient sky scene."""
        self._stop_banner_animation()

        self._animation_engine.stop()  # type: ignore[attr-defined]
        self._animation_engine.is_enabled = False  # type: ignore[attr-defined]

        timer = self._animation_timer  # type: ignore[attr-defined]
        if timer is not None and hasattr(timer, "stop"):
            timer.stop()  # type: ignore[union-attr]
        self._animation_timer = None  # type: ignore[attr-defined]

        # Clear any lingering animation colors from the banner
        try:
            self.query_one(Banner).refresh()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _apply_animation_runtime(self) -> None:
        """Apply the selected mode without focus-based or idle-based pausing."""
        self._start_animation_mode(self._animation_requested_mode)  # type: ignore[attr-defined]

    def _animation_tick(self) -> None:
        """Periodic tick: advance engine and refresh banner if frame changed."""
        try:
            changed = self._animation_engine.update()  # type: ignore[attr-defined]
        except Exception:
            logger.exception("Animation engine tick crashed")
            return
        if changed:
            try:
                self.query_one(Banner).refresh()  # type: ignore[attr-defined]
                self.query_one(BoxTabBar).refresh()  # type: ignore[attr-defined]
            except Exception:
                logger.exception("Header refresh failed after animation tick")

    def _cycle_animation(self, new_mode: str) -> None:
        """Set animation mode, reconfigure engine, and update status bar."""
        self._animation_requested_mode = new_mode  # type: ignore[attr-defined]
        self._apply_animation_runtime()
        status_bar = self.query_one("#telec-footer", TelecFooter)  # type: ignore[attr-defined]
        status_bar.animation_mode = new_mode
