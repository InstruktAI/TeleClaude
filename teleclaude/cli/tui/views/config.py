"""Interactive configuration view with guided setup and inline env editing."""

from __future__ import annotations

import dataclasses
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.css.query import NoMatches, WrongType
from textual.events import Key, Paste
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.config_handlers import (
    EnvVarStatus,
    ValidationResult,
    check_env_vars,
    get_person_config,
    list_people,
    validate_all,
)
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.views._config_constants import (
    _ADAPTER_TABS,
    _SUBTABS,
    AdapterSectionProjection,
    AIKeysConfig,
    BackupAdapterConfig,
    EmailAdapterConfig,
    FirecrawlAdapterConfig,
    ProvidersConfig,
    Subtab,
    project_adapter_sections,
)
from teleclaude.cli.tui.views._project_actions import _load_raw_config, _resolve_config_path
from teleclaude.cli.tui.views.config_editing import ConfigContentEditingMixin
from teleclaude.cli.tui.views.config_render import ConfigContentRenderMixin
from teleclaude.cli.tui.views.reflection import ReflectedField, reflect_schema, resolve_env_placeholders
from teleclaude.config import (
    DEFAULT_CONFIG,
    ChiptunesConfig,
    ComputerConfig,
    DiscordConfig,
    RedisConfig,
    STTConfig,
    SummarizerConfig,
    TelegramConfig,
    TTSConfig,
    WhatsAppConfig,
    deep_merge,
    parse_stt_config,
    parse_tts_config,
)
from teleclaude.config._summarizer import parse_summarizer_config
from teleclaude.config.schema import PersonEntry
from teleclaude.core.session_start_messages import SESSION_START_MESSAGES

__all__ = ["ConfigContent", "ConfigView"]


def _default_section(name: str) -> dict[str, Any]:  # guard: loose-dict - DEFAULT_CONFIG holds the untyped YAML defaults
    """Return a DEFAULT_CONFIG section as a plain dict for safe merge/unpack."""
    section = DEFAULT_CONFIG.get(name, {})
    return section if isinstance(section, dict) else {}


def _apply_tts_applicability(tts: TTSConfig, fields: list[ReflectedField]) -> list[ReflectedField]:
    """Drop engine-inapplicable TTS leaves and surface the built-in session_start default.

    Engine capabilities are derived from the data, not a fixed registry (MLX engines
    are any service with a ``model``): name-based engines never use ``voice_id``,
    static engines never consume ``model``/``params``, and an engine without a voice
    list has no ``voices`` leaf.
    """
    drop: set[str] = set()
    for name, svc in (tts.services or {}).items():
        base = f"tts.services.{name}"
        if not svc.model:
            drop.add(f"{base}.model")
            drop.add(f"{base}.params")
        voices = svc.voices
        if not voices:
            drop.add(f"{base}.voices")
        elif not any(voice.voice_id for voice in voices):
            drop.update(f"{base}.voices.{index}.voice_id" for index in range(len(voices)))

    kept = [f for f in fields if f.key not in drop]
    for field in kept:
        if field.key == "tts.events.session_start.messages" and not field.value:
            field.value = list(SESSION_START_MESSAGES)
    return kept


class ConfigView(Widget, can_focus=True):
    """Configuration tab with guided setup and inline edit behavior."""

    DEFAULT_CSS = """
    ConfigView {
        width: 100%;
        height: 1fr;
    }
    ConfigView VerticalScroll {
        width: 100%;
        height: 1fr;
        scrollbar-size: 0 0;
    }
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Up", key_display="↑", group=Binding.Group("Nav", compact=True), show=False),
        Binding("down", "cursor_down", "Down", key_display="↓", group=Binding.Group("Nav", compact=True), show=False),
        Binding("enter", "activate", "Select/Edit", key_display="↵"),
        Binding("escape", "cancel", "Cancel", key_display="Esc"),
        Binding("g", "toggle_guided_mode", "Guided"),
        Binding("v", "run_validation", "Validate"),
        Binding("r", "refresh_config", "Refresh", key_display="↻"),
        Binding("tab", "next_subtab", "Tab", key_display="⇥", group=Binding.Group("Tabs", compact=True)),
        Binding("shift+tab", "prev_subtab", "Back", key_display="⇤", group=Binding.Group("Tabs", compact=True)),
        Binding(
            "left",
            "prev_adapter_tab",
            "Prev",
            key_display="←",
            group=Binding.Group("Adapters", compact=True),
            show=False,
        ),
        Binding(
            "right",
            "next_adapter_tab",
            "Next",
            key_display="→",
            group=Binding.Group("Adapters", compact=True),
            show=False,
        ),
    ]

    active_subtab = reactive(0)
    active_adapter_tab = reactive(0)

    def _content_or_none(self) -> ConfigContent | None:
        """Return the mounted content widget when available."""
        if not self.is_attached:
            return None
        try:
            return self.query_one("#config-content", ConfigContent)
        except (NoMatches, WrongType):
            return None

    def _sync_from_content(self) -> None:
        """Mirror tab state back from the content widget."""
        content = self._content_or_none()
        if content is None:
            return
        self.active_subtab = content.active_subtab
        self.active_adapter_tab = content.active_adapter_tab

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Limit adapter tab movement to relevant subviews."""
        del parameters
        if action in ("next_adapter_tab", "prev_adapter_tab"):
            content = self._content_or_none()
            if content is not None and content.is_on_enum_field:
                return True
            return self.active_subtab == _SUBTABS.index(Subtab.ADAPTERS)
        return True

    def watch_active_subtab(self, _value: int) -> None:
        """Propagate subtab changes to the inner content widget."""
        self._sync_content()
        if self.is_attached:
            self.app.refresh_bindings()

    def watch_active_adapter_tab(self, _value: int) -> None:
        """Propagate adapter tab changes to the inner content widget."""
        self._sync_content()
        if self.is_attached:
            self.app.refresh_bindings()

    def compose(self) -> ComposeResult:
        """Compose the scrollable configuration content."""
        scroll = VerticalScroll(id="config-scroll")
        scroll.can_focus = False
        with scroll:
            yield ConfigContent(id="config-content")

    def on_mount(self) -> None:
        """Load configuration data once the widget is mounted."""
        self._refresh_content()

    def on_focus(self) -> None:
        """Refresh bindings and clear any focus border decoration."""
        self.styles.border = ("none", "transparent")
        self.app.refresh_bindings()

    def on_click(self) -> None:
        """Focus the widget when it is clicked."""
        self.focus()

    def on_config_content_subtab_selected(self, msg: ConfigContent.SubtabSelected) -> None:
        """Sync the outer subtab index from a click inside the content."""
        self.active_subtab = msg.idx

    def on_config_content_adapter_tab_selected(self, msg: ConfigContent.AdapterTabSelected) -> None:
        """Sync the outer adapter tab index from a click inside the content."""
        self.active_adapter_tab = msg.idx

    @property
    def paste_safe(self) -> bool:
        """Accept paste/key bursts only while an inline field is being edited."""
        content = self._content_or_none()
        return content is not None and content.is_editing

    def on_paste(self, event: Paste) -> None:
        """Insert pasted text into the active edit buffer; ignore otherwise."""
        content = self._content_or_none()
        if content is None or not content.is_editing:
            return
        content.append_edit_text(event.text)
        event.stop()

    def on_key(self, event: Key) -> None:
        """Forward editing keystrokes or list reordering keys to the content widget."""
        content = self._content_or_none()
        if content is None:
            return

        if not content.is_editing:
            if event.key == "left_square_bracket":
                content.reorder_reflected_list(-1)
                event.stop()
                return
            if event.key == "right_square_bracket":
                content.reorder_reflected_list(1)
                event.stop()
                return
            return

        if event.key == "backspace":
            content.backspace_edit()
            event.stop()
            return
        if event.key == "ctrl+u":
            content.clear_edit_buffer()
            event.stop()
            return
        if event.character and event.is_printable:
            content.append_edit_character(event.character)
            event.stop()

    def _refresh_content(self) -> None:
        """Ask the content widget to reload its underlying config data."""
        content = self.query_one("#config-content", ConfigContent)
        content.refresh_data()

    def _sync_content(self) -> None:
        """Push the current tab state into the content widget."""
        content = self.query_one("#config-content", ConfigContent)
        content.active_subtab = self.active_subtab
        content.active_adapter_tab = self.active_adapter_tab

    def action_run_validation(self) -> None:
        """Run config validation for the current content."""
        content = self.query_one("#config-content", ConfigContent)
        content.run_validation()

    def action_refresh_config(self) -> None:
        """Reload config data from disk."""
        self._refresh_content()

    def action_cursor_up(self) -> None:
        """Move the config cursor up."""
        content = self.query_one("#config-content", ConfigContent)
        content.move_cursor(-1)

    def action_cursor_down(self) -> None:
        """Move the config cursor down."""
        content = self.query_one("#config-content", ConfigContent)
        content.move_cursor(1)

    def action_activate(self) -> None:
        """Activate the currently selected field or row."""
        content = self.query_one("#config-content", ConfigContent)
        content.activate_current()
        self._sync_from_content()

    def action_cancel(self) -> None:
        """Cancel the active edit, expansion, or guided mode step."""
        content = self.query_one("#config-content", ConfigContent)
        if content.is_editing:
            content.cancel_edit()
        elif content.is_person_expanded:
            content.collapse_person()
        elif content.guided_mode:
            content.toggle_guided_mode()
            self._sync_from_content()

    def action_toggle_guided_mode(self) -> None:
        """Toggle guided mode on the content widget."""
        content = self.query_one("#config-content", ConfigContent)
        content.toggle_guided_mode()
        self._sync_from_content()

    def action_next_subtab(self) -> None:
        """Switch to the next config subtab."""
        self.active_subtab = (self.active_subtab + 1) % len(_SUBTABS)
        self._sync_content()

    def action_prev_subtab(self) -> None:
        """Switch to the previous config subtab."""
        self.active_subtab = (self.active_subtab - 1) % len(_SUBTABS)
        self._sync_content()

    def action_next_adapter_tab(self) -> None:
        """Advance to the next adapter tab or enum value."""
        content = self._content_or_none()
        if content is not None and content.is_on_enum_field:
            content.cycle_enum_field(1)
            return
        if self.active_subtab == _SUBTABS.index(Subtab.ADAPTERS):
            self.active_adapter_tab = (self.active_adapter_tab + 1) % len(_ADAPTER_TABS)
            self._sync_content()

    def action_prev_adapter_tab(self) -> None:
        """Move to the previous adapter tab or enum value."""
        content = self._content_or_none()
        if content is not None and content.is_on_enum_field:
            content.cycle_enum_field(-1)
            return
        if self.active_subtab == _SUBTABS.index(Subtab.ADAPTERS):
            self.active_adapter_tab = (self.active_adapter_tab - 1) % len(_ADAPTER_TABS)
            self._sync_content()


class ConfigContent(
    ConfigContentEditingMixin,
    ConfigContentRenderMixin,
    TelecMixin,
    Widget,
):
    """Renders guided config sections with inline env editing."""

    DEFAULT_CSS = """
    ConfigContent {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    """

    class SubtabSelected(Message):
        """Posted when a config subtab is selected by mouse."""

        def __init__(self, idx: int) -> None:
            super().__init__()
            self.idx = idx

    class AdapterTabSelected(Message):
        """Posted when an adapter card is selected by mouse."""

        def __init__(self, idx: int) -> None:
            super().__init__()
            self.idx = idx

    active_subtab = reactive(0, layout=True)
    active_adapter_tab = reactive(0, layout=True)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._env_data: list[EnvVarStatus] = []
        self._people_data: list[PersonEntry] = []
        self._validation_results: list[ValidationResult] = []
        self._adapter_sections: list[AdapterSectionProjection] = []
        self._cursor_by_context: dict[str, int] = {}
        self._editing_var_name: str | None = None
        self._edit_buffer = ""
        self._status_message = ""
        self._status_is_error = False
        self._guided_mode = False
        self._guided_step_index = 0
        self._tab_click_regions: list[tuple[int, int, int, int]] = []  # (row, x_start, x_end, subtab_idx)
        self._row_click_map: dict[int, tuple[str, Any]] = {}  # {content_row: action_tuple}
        self._expanded_person: str | None = None
        self._person_field_cursor: int = 0
        self._raw_config: dict[str, Any] = {}  # guard: loose-dict - raw config.yml tree
        self._list_element_idx: int = 0
        self._reflected_cache: dict[Subtab, list[ReflectedField]] = {}

    @property
    def reflected_fields(self) -> list[ReflectedField]:
        """Reflected fields for the active subtab, cached until the config reloads.

        Reflection rebuilds typed objects and resolves type hints — too costly to
        recompute on every render and keystroke, so results are memoized per subtab
        and invalidated by refresh_data when the underlying config changes.
        """
        tab = _SUBTABS[self.active_subtab]
        cached = self._reflected_cache.get(tab)
        if cached is not None:
            return cached
        fields = self._build_reflected_fields(tab)
        resolve_env_placeholders(fields)
        self._reflected_cache[tab] = fields
        return fields

    def _build_reflected_fields(self, tab: Subtab) -> list[ReflectedField]:
        """Construct the reflected fields for a subtab from the current raw config."""
        if tab == Subtab.INFRA:
            computer_data = self._raw_config.get("computer", {})
            computer_fields = {f.name for f in dataclasses.fields(ComputerConfig)}
            filtered_computer = {k: v for k, v in computer_data.items() if k in computer_fields}
            computer_obj = ComputerConfig(
                name=filtered_computer.get("name", "Mac"),
                user=filtered_computer.get("user", ""),
                role=filtered_computer.get("role", "development"),
                timezone=filtered_computer.get("timezone", "Europe/Amsterdam"),
                default_working_dir=filtered_computer.get("default_working_dir", ""),
                help_desk_dir=filtered_computer.get("help_desk_dir", ""),
                is_master=filtered_computer.get("is_master", True),
                is_ingress_node=filtered_computer.get("is_ingress_node", False),
                trusted_dirs=[],
                host=filtered_computer.get("host", None),
            )
            fields = reflect_schema(computer_obj, prefix="computer", section="Computer", owning_source="machine")

            redis_data = self._raw_config.get("redis", {})
            merged_redis = deep_merge(_default_section("redis"), redis_data)
            redis_fields = {f.name for f in dataclasses.fields(RedisConfig)}
            filtered_redis = {k: v for k, v in merged_redis.items() if k in redis_fields}
            redis_obj = RedisConfig(**filtered_redis)
            fields.extend(reflect_schema(redis_obj, prefix="redis", section="Redis", owning_source="machine"))

            chiptunes_data = self._raw_config.get("chiptunes", {})
            merged_chiptunes = deep_merge(_default_section("chiptunes"), chiptunes_data)
            chiptunes_fields = {f.name for f in dataclasses.fields(ChiptunesConfig)}
            filtered_chiptunes = {k: v for k, v in merged_chiptunes.items() if k in chiptunes_fields}
            chiptunes_obj = ChiptunesConfig(**filtered_chiptunes)
            fields.extend(
                reflect_schema(chiptunes_obj, prefix="chiptunes", section="Chiptunes", owning_source="machine")
            )
            return fields

        if tab == Subtab.ADAPTERS:
            telegram_data = self._raw_config.get("telegram", {})
            merged_telegram = deep_merge(_default_section("telegram"), telegram_data)
            telegram_fields = {f.name for f in dataclasses.fields(TelegramConfig)}
            filtered_telegram = {k: v for k, v in merged_telegram.items() if k in telegram_fields}
            telegram_obj = TelegramConfig(**filtered_telegram)
            fields = reflect_schema(telegram_obj, prefix="telegram", section="Telegram", owning_source="machine")

            # Add environment-backed Telegram bot token manually
            fields.append(
                ReflectedField(
                    key="telegram.bot_token",
                    name="Bot Token",
                    field_type=str,
                    value=telegram_data.get("bot_token", "${TELEGRAM_BOT_TOKEN}"),
                    description="Telegram Bot API token from @BotFather",
                    section="Telegram",
                    owning_source="machine",
                )
            )

            discord_data = self._raw_config.get("discord", {})
            merged_discord = deep_merge(_default_section("discord"), discord_data)
            discord_fields = {f.name for f in dataclasses.fields(DiscordConfig)}
            filtered_discord = {k: v for k, v in merged_discord.items() if k in discord_fields}
            discord_obj = DiscordConfig(**filtered_discord)
            fields.extend(reflect_schema(discord_obj, prefix="discord", section="Discord", owning_source="machine"))

            whatsapp_data = self._raw_config.get("whatsapp", {})
            merged_whatsapp = deep_merge(_default_section("whatsapp"), whatsapp_data)
            whatsapp_fields = {f.name for f in dataclasses.fields(WhatsAppConfig)}
            filtered_whatsapp = {k: v for k, v in merged_whatsapp.items() if k in whatsapp_fields}
            whatsapp_obj = WhatsAppConfig(**filtered_whatsapp)
            fields.extend(reflect_schema(whatsapp_obj, prefix="whatsapp", section="WhatsApp", owning_source="machine"))
            return fields

        if tab == Subtab.PROVIDERS:
            # Providers remain environment-only settings
            providers_obj = ProvidersConfig(
                ai=AIKeysConfig(
                    anthropic_api_key="${ANTHROPIC_API_KEY}",
                    openai_api_key="${OPENAI_API_KEY}",
                    google_api_key="${GOOGLE_API_KEY}",
                ),
                email=EmailAdapterConfig(
                    email_from="${EMAIL_FROM}",
                    email_replyto="${EMAIL_REPLYTO}",
                    smtp_username="${SMTP_USERNAME}",
                    smtp_key="${SMTP_KEY}",
                    smtp_relay="${SMTP_RELAY}",
                ),
                backup=BackupAdapterConfig(
                    aws_access_key_id="${AWS_ACCESS_KEY_ID}",
                    aws_secret_access_key="${AWS_SECRET_ACCESS_KEY}",
                    aws_s3_host="${AWS_S3_HOST}",
                    aws_s3_region="${AWS_S3_REGION}",
                    aws_s3_bucket="${AWS_S3_BUCKET}",
                    backup_prefix="${TELECLAUDE_BACKUP_PREFIX}",
                ),
                firecrawl=FirecrawlAdapterConfig(api_key="${FIRECRAWL_API_KEY}"),
            )
            return reflect_schema(providers_obj, section="Providers", owning_source="machine")

        if tab == Subtab.SUMMARIZER:
            summarizer_obj = parse_summarizer_config(self._raw_config.get("summarizer", {})) or SummarizerConfig()
            fields = reflect_schema(summarizer_obj, prefix="summarizer", section="Summarizer", owning_source="machine")
            # Map summarizer models to their correct YAML paths
            for f in fields:
                if f.key.startswith("summarizer.models."):
                    provider = f.key.split(".")[-1]
                    f.key = f"summarizer.{provider}.model"
            return fields

        if tab == Subtab.TTS_STT:
            merged_stt = deep_merge(_default_section("stt"), self._raw_config.get("stt", {}))
            merged_tts = deep_merge(_default_section("tts"), self._raw_config.get("tts", {}))
            stt_obj = parse_stt_config(merged_stt) or STTConfig(enabled=False)
            tts_obj = parse_tts_config(merged_tts) or TTSConfig(enabled=False)

            fields = reflect_schema(stt_obj, prefix="stt", section="STT", owning_source="machine")
            tts_fields = reflect_schema(tts_obj, prefix="tts", section="TTS", owning_source="machine")
            fields.extend(_apply_tts_applicability(tts_obj, tts_fields))
            return fields

        return []

    @property
    def guided_mode(self) -> bool:
        """Whether guided setup mode is active."""
        return self._guided_mode

    @property
    def is_editing(self) -> bool:
        """Whether an env var or person field is being edited."""
        return self._editing_var_name is not None

    @property
    def is_person_expanded(self) -> bool:
        """Whether a person's details are currently expanded."""
        return self._expanded_person is not None

    @property
    def person_reflected_fields(self) -> list[ReflectedField]:
        """Return the reflected fields for the expanded person."""
        if self._expanded_person is None:
            return []

        cache_key = f"person:{self._expanded_person}"
        cached = self._reflected_cache.get(cache_key)  # type: ignore[arg-type]
        if cached is not None:
            return cached

        person_entry = next((p for p in self._people_data if (p.slug or p.name) == self._expanded_person), None)
        if person_entry is None:
            return []

        person_config = get_person_config(self._expanded_person)

        entry_fields = reflect_schema(
            person_entry, prefix="identity", section="Global Identity", owning_source="global"
        )
        overlay_fields = reflect_schema(
            person_config, prefix="overlay", section="Overlay Settings", owning_source="per-person"
        )

        fields = entry_fields + overlay_fields
        resolve_env_placeholders(fields)
        self._reflected_cache[cache_key] = fields  # type: ignore[index]
        return fields

    @property
    def person_editable_fields(self) -> list[str]:
        """Return the keys of person_reflected_fields."""
        return [f.key for f in self.person_reflected_fields]

    def refresh_data(self) -> None:
        """Reload env vars, people, derived projections, and config.yml from disk."""
        self._reflected_cache.clear()
        try:
            self._raw_config = _load_raw_config(_resolve_config_path())  # type: ignore[assignment]
        except Exception as exc:
            self._raw_config = {}
            self._status_message = f"Failed to load config.yml: {exc}"
            self._status_is_error = True

        try:
            self._env_data = check_env_vars()
        except Exception as exc:
            self._env_data = []
            self._status_message = f"Failed to load env vars: {exc}"
            self._status_is_error = True

        self._adapter_sections = project_adapter_sections(self._env_data)

        try:
            self._people_data = list_people()
        except Exception as exc:
            self._people_data = []
            self._status_message = f"Failed to load people: {exc}"
            self._status_is_error = True

        self._clamp_current_cursor()

        if self._guided_mode:
            self._apply_guided_step()
            self._auto_advance_completed_steps()

        self.refresh(layout=True)

    def run_validation(self) -> None:
        """Run the full config validation suite and surface the summary."""
        try:
            self._validation_results = validate_all()
            passed = sum(1 for result in self._validation_results if result.passed)
            self._status_message = f"Validation complete: {passed}/{len(self._validation_results)} checks passed"
            self._status_is_error = passed != len(self._validation_results)
        except Exception as exc:
            self._validation_results = []
            self._status_message = f"Validation failed: {exc}"
            self._status_is_error = True
        self.refresh(layout=True)

    def _current_context_key(self) -> str:
        """Return the cursor context key for the active subtab."""
        tab = _SUBTABS[self.active_subtab]
        if tab == Subtab.ADAPTERS:
            return f"adapter:{_ADAPTER_TABS[self.active_adapter_tab]}"
        return tab

    def _get_active_adapter_section(self) -> AdapterSectionProjection | None:
        """Return the adapter section for the active adapter tab."""
        if not self._adapter_sections:
            return None
        idx = max(0, min(self.active_adapter_tab, len(self._adapter_sections) - 1))
        return self._adapter_sections[idx]

    def _selectable_env_rows(self) -> list[EnvVarStatus]:
        """Return the env rows available for the active subtab."""
        tab = _SUBTABS[self.active_subtab]
        if tab == Subtab.ADAPTERS:
            section = self._get_active_adapter_section()
            if section is None:
                return []
            return section.env_statuses
        if tab == Subtab.ENV:
            return self._env_data
        return []

    def _current_cursor(self) -> int:
        """Return the cursor position for the active context."""
        return self._cursor_by_context.get(self._current_context_key(), 0)

    def _set_current_cursor(self, index: int) -> None:
        """Persist the cursor position for the active context."""
        self._cursor_by_context[self._current_context_key()] = index

    def _clamp_current_cursor(self) -> None:
        """Clamp the cursor to the available rows in the active context."""
        tab = _SUBTABS[self.active_subtab]
        if tab == Subtab.PEOPLE:
            count = len(self._people_data)
            if count:
                self._set_current_cursor(max(0, min(self._current_cursor(), count - 1)))
            else:
                self._set_current_cursor(0)
            self._person_field_cursor = max(0, min(self._person_field_cursor, len(self.person_editable_fields) - 1))
            return
        if tab in (Subtab.INFRA, Subtab.ADAPTERS, Subtab.PROVIDERS, Subtab.SUMMARIZER, Subtab.TTS_STT):
            count = len(self.reflected_fields)
            if count:
                self._set_current_cursor(max(0, min(self._current_cursor(), count - 1)))
            else:
                self._set_current_cursor(0)
            return
        rows = self._selectable_env_rows()
        if not rows:
            self._set_current_cursor(0)
            return
        cursor = self._current_cursor()
        self._set_current_cursor(max(0, min(cursor, len(rows) - 1)))

    def _current_selected_env(self) -> EnvVarStatus | None:
        """Return the currently selected env row, if any."""
        rows = self._selectable_env_rows()
        if not rows:
            return None
        cursor = self._current_cursor()
        if cursor < 0 or cursor >= len(rows):
            return None
        return rows[cursor]
