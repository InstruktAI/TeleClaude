"""Interactive configuration view with guided setup and inline env editing."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from instrukt_ai_logging import get_logger
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.css.query import NoMatches, WrongType
from textual.events import Key, Paste
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.config_handlers import EnvVarStatus, ValidationResult
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.views._config_constants import (
    _ADAPTER_TABS,
    _SUBTABS,
    AdapterSectionProjection,
    ConfigTuiOutcome,
    Subtab,
    observe_config_tui,
    project_adapter_sections,
)
from teleclaude.cli.tui.views.config_editing import ConfigContentEditingMixin
from teleclaude.cli.tui.views.config_operations import (
    ConfigOperationFailed,
    ConfigOperations,
    PersonSecretInventory,
    SubjectSnapshot,
)
from teleclaude.cli.tui.views.config_render import ConfigContentRenderMixin
from teleclaude.cli.tui.views.lenient_model import lenient_model
from teleclaude.cli.tui.views.reflection import (
    EnvironmentProvenance,
    ReflectedField,
    apply_machine_environment,
    bind_environment_references,
    mark_write_only,
    reflect_schema,
)
from teleclaude.config._chiptunes import ChiptunesConfig
from teleclaude.config._defaults import DEFAULT_CONFIG
from teleclaude.config._machine_build import deep_merge
from teleclaude.config._models import (
    BackupConfig,
    ComputerConfig,
    DaemonConfig,
    DiscordConfig,
    EmailConfig,
    RedisConfig,
    STTConfig,
    TelegramConfig,
    TTSConfig,
    WhatsAppConfig,
)
from teleclaude.config._summarizer import SummarizerConfig
from teleclaude.config.identity_schema import PersonEntry
from teleclaude.config.operation_answers import EnvironmentReferenceRow
from teleclaude.config.person_resource import IDENTITY_SECTION, SETTINGS_SECTION
from teleclaude.config.schema import PersonConfig
from teleclaude.config.subject_operations import ConfigFailureKind
from teleclaude.config.tiers import Tier
from teleclaude.config_subjects import ConfigEnvironment, ConfigSubjectKind
from teleclaude.core.session_start_messages import SESSION_START_MESSAGES
from teleclaude.project_manifest import ConfigKind

__all__ = ["ConfigContent", "ConfigView"]

logger = get_logger(__name__)

_TELEGRAM_SECTION = "telegram"
_WHATSAPP_SECTION = "whatsapp"
_EMAIL_SECTION = "email"


def _default_section(name: str) -> dict[str, Any]:  # guard: loose-dict - DEFAULT_CONFIG holds the untyped YAML defaults
    """Return a DEFAULT_CONFIG section as a plain dict for safe merge/unpack."""
    section = DEFAULT_CONFIG.get(name, {})
    return section if isinstance(section, dict) else {}


def _apply_tts_applicability(tts: TTSConfig, fields: list[ReflectedField]) -> list[ReflectedField]:
    """Drop engine-inapplicable TTS leaves and surface the built-in session_start default.

    Engine capabilities are derived from the data, not a fixed registry (MLX engines
    are any service with a ``model``): name-based engines never use ``voice_id``,
    static engines never consume ``model``/``params``/``cli_bin``/``instruct``, and
    an engine without a voice list has no ``voices`` leaf.
    """
    drop: set[str] = set()
    for name, svc in (tts.services or {}).items():
        base = f"tts.services.{name}"
        if not svc.model:
            drop.add(f"{base}.model")
            drop.add(f"{base}.params")
            drop.add(f"{base}.cli_bin")
            drop.add(f"{base}.instruct")
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


_COMPUTER_SECTION = "computer"
_KIND_FIELD = "kind"
_SLUG_FIELD = "slug"
_OVERLAY_UNPRESENTABLE = "The overlay of {slug} cannot be presented"
_IDENTITY_PREFIX = "identity"
_OVERLAY_PREFIX = "overlay"
_IDENTITY_SECTION_LABEL = "Global Identity"
_OVERLAY_SECTION_LABEL = "Overlay Settings"
_SECRETS_SECTION_LABEL = "Secrets"
_IDENTITY_SOURCE = "global"
_OVERLAY_SOURCE = "per-person"
_SECRET_SOURCE = "personal-mcp-secret"
_SECRET_KEY_PREFIX = "secrets."
_PERSON_CACHE_KEY = "person:{slug}"
_OUTPUT_VISIBILITY_FIELDS = ("system_messages", "tool_calls")
_STATUS_TEMPLATE = "{prefix}: {error}"
_LOAD_MACHINE_FAILED = "Failed to load machine configuration"
_LOAD_ENV_FAILED = "Failed to load env vars"
_LOAD_PEOPLE_FAILED = "Failed to load people"
_LOAD_SECRETS_FAILED = "Failed to load personal secrets"
_API_ATTRIBUTE = "api"
_LOAD_GROUP = "config-load"
_SECRETS_GROUP = "config-secrets"
_VALIDATE_GROUP = "config-validate"
_DAEMON_UNAVAILABLE = "The daemon is not reachable."


def _person_entry(slug: str, identity: dict[str, object]) -> PersonEntry:  # guard: loose-dict - effective view
    """The identity entry of a person, built from the effective identity section the daemon answered."""
    declared = {name: value for name, value in identity.items() if name in PersonEntry.model_fields}
    return PersonEntry.model_construct(**declared, slug=slug)


def _person_overlay(slug: str, settings: dict[str, object]) -> PersonConfig:  # guard: loose-dict - effective view
    """The typed overlay of a person from its effective settings; a partial projection keeps the values it holds."""
    return lenient_model(PersonConfig, {**settings, _KIND_FIELD: ConfigKind.PERSON.value, _SLUG_FIELD: slug})


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
            content.clear_personal_secret_or_edit_buffer()
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
        self._outside_scope: tuple[str, ...] = ()
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
        self._raw_config: dict[str, Any] = {}  # guard: loose-dict - the daemon's effective machine document
        self._machine_revision: str | None = None
        self._machine_references: dict[str, EnvironmentReferenceRow] = {}
        self._variable_is_set: dict[str, bool] = {}
        self._people: dict[str, SubjectSnapshot] = {}
        self._person_secrets: dict[str, PersonSecretInventory] = {}
        self._write_lock = asyncio.Lock()
        self._load_pending = True
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
        render_cycle_id = str(uuid4())
        observe_config_tui(ConfigTuiOutcome.RENDER_REQUESTED, render_cycle_id=render_cycle_id, subtab=tab.value)
        fields = self._build_reflected_fields(tab)
        apply_machine_environment(fields, self._machine_references, self._variable_is_set)
        observe_config_tui(
            ConfigTuiOutcome.RENDERED,
            render_cycle_id=render_cycle_id,
            field_paths=[field.key for field in fields],
            source_kinds={field.key: self._field_source_kind(field) for field in fields},
        )
        self._reflected_cache[tab] = fields
        return fields

    def _field_source_kind(self, field: ReflectedField) -> str:
        """Classify a rendered field source without exposing its value."""
        if field.env_var:
            return "placeholder"
        node: object = self._raw_config
        for part in field.key.split("."):
            if not isinstance(node, dict) or part not in node:
                return "default"
            node = node[part]
        return "literal"

    def _build_reflected_fields(self, tab: Subtab) -> list[ReflectedField]:
        """Construct the reflected fields for a subtab from the current raw config."""
        if tab == Subtab.INFRA:
            computer_data = self._raw_config.get("computer", {})
            computer_fields = set(ComputerConfig.model_fields)
            filtered_computer = {k: v for k, v in computer_data.items() if k in computer_fields}
            computer_obj = ComputerConfig.model_construct(
                name=filtered_computer.get("name", "Mac"),
                user=filtered_computer.get("user", ""),
                role=filtered_computer.get("role", "development"),
                timezone=filtered_computer.get("timezone", "Europe/Amsterdam"),
                default_working_dir=filtered_computer.get("default_working_dir", ""),
                is_master=filtered_computer.get("is_master", True),
                is_ingress_node=filtered_computer.get("is_ingress_node", False),
                host=filtered_computer.get("host", None),
            )
            fields = reflect_schema(
                computer_obj, prefix="computer", section="Computer", owning_source="machine", inherited_tier=Tier.TUI
            )

            daemon_data = deep_merge(_default_section("daemon"), self._raw_config.get("daemon", {}))
            daemon_obj: DaemonConfig = DaemonConfig.model_validate(daemon_data)
            fields.extend(
                reflect_schema(
                    daemon_obj,
                    prefix="daemon",
                    section="Daemon",
                    owning_source="machine",
                    inherited_tier=Tier.TUI,
                )
            )

            redis_data = self._raw_config.get("redis", {})
            merged_redis = deep_merge(_default_section("redis"), redis_data)
            redis_fields = set(RedisConfig.model_fields)
            filtered_redis = {k: v for k, v in merged_redis.items() if k in redis_fields}
            redis_obj = RedisConfig.model_construct(**filtered_redis)
            fields.extend(
                reflect_schema(
                    redis_obj, prefix="redis", section="Redis", owning_source="machine", inherited_tier=Tier.TUI
                )
            )

            chiptunes_data = self._raw_config.get("chiptunes", {})
            merged_chiptunes = deep_merge(_default_section("chiptunes"), chiptunes_data)
            chiptunes_fields = set(ChiptunesConfig.model_fields)
            filtered_chiptunes = {k: v for k, v in merged_chiptunes.items() if k in chiptunes_fields}
            chiptunes_obj = ChiptunesConfig.model_construct(**filtered_chiptunes)
            fields.extend(
                reflect_schema(
                    chiptunes_obj,
                    prefix="chiptunes",
                    section="Chiptunes",
                    owning_source="machine",
                    inherited_tier=Tier.TUI,
                )
            )
            return fields

        if tab == Subtab.ADAPTERS:
            fields: list[ReflectedField] = []
            if _TELEGRAM_SECTION not in self._outside_scope:
                telegram_data = self._raw_config.get("telegram", {})
                merged_telegram = deep_merge(_default_section("telegram"), telegram_data)
                telegram_fields = set(TelegramConfig.model_fields)
                filtered_telegram = {k: v for k, v in merged_telegram.items() if k in telegram_fields}
                telegram_obj = TelegramConfig.model_construct(**filtered_telegram)
                fields.extend(
                    reflect_schema(
                        telegram_obj,
                        prefix="telegram",
                        section="Telegram",
                        owning_source="machine",
                        inherited_tier=Tier.TUI,
                    )
                )

            discord_data = self._raw_config.get("discord", {})
            merged_discord = deep_merge(_default_section("discord"), discord_data)
            discord_fields = set(DiscordConfig.model_fields)
            filtered_discord = {k: v for k, v in merged_discord.items() if k in discord_fields}
            discord_obj = DiscordConfig.model_construct(**filtered_discord)
            fields.extend(
                reflect_schema(
                    discord_obj, prefix="discord", section="Discord", owning_source="machine", inherited_tier=Tier.TUI
                )
            )

            if _WHATSAPP_SECTION not in self._outside_scope:
                whatsapp_data = self._raw_config.get("whatsapp", {})
                merged_whatsapp = deep_merge(_default_section("whatsapp"), whatsapp_data)
                whatsapp_fields = set(WhatsAppConfig.model_fields)
                filtered_whatsapp = {k: v for k, v in merged_whatsapp.items() if k in whatsapp_fields}
                whatsapp_obj = WhatsAppConfig.model_construct(**filtered_whatsapp)
                fields.extend(
                    reflect_schema(
                        whatsapp_obj,
                        prefix="whatsapp",
                        section="WhatsApp",
                        owning_source="machine",
                        inherited_tier=Tier.TUI,
                    )
                )
            return fields

        if tab == Subtab.PROVIDERS:
            backup_data = deep_merge(_default_section("backup"), self._raw_config.get("backup", {}))
            backup_fields = set(BackupConfig.model_fields)
            backup_obj = BackupConfig.model_construct(
                **{key: value for key, value in backup_data.items() if key in backup_fields}
            )
            fields = reflect_schema(
                backup_obj, prefix="backup", section="Providers", owning_source="machine", inherited_tier=Tier.TUI
            )
            if _EMAIL_SECTION not in self._outside_scope:
                email_data = self._raw_config.get("email", {})
                merged_email = deep_merge(_default_section("email"), email_data)
                email_fields = set(EmailConfig.model_fields)
                email_obj = EmailConfig.model_construct(
                    **{key: value for key, value in merged_email.items() if key in email_fields}
                )
                fields.extend(
                    reflect_schema(
                        email_obj, prefix="email", section="Email", owning_source="machine", inherited_tier=Tier.TUI
                    )
                )
            return fields

        if tab == Subtab.SUMMARIZER:
            summarizer_raw = self._raw_config.get("summarizer") or {}
            summarizer_obj = SummarizerConfig.model_validate(summarizer_raw) if summarizer_raw else SummarizerConfig()
            fields = reflect_schema(
                summarizer_obj,
                prefix="summarizer",
                section="Summarizer",
                owning_source="machine",
                inherited_tier=Tier.TUI,
            )
            return fields

        if tab == Subtab.TTS_STT:
            merged_stt = deep_merge(_default_section("stt"), self._raw_config.get("stt", {}))
            merged_tts = deep_merge(_default_section("tts"), self._raw_config.get("tts", {}))
            stt_obj = STTConfig.model_validate(merged_stt) if merged_stt else STTConfig(enabled=False)
            tts_obj = TTSConfig.model_validate(merged_tts) if merged_tts else TTSConfig(enabled=False)

            fields = reflect_schema(
                stt_obj, prefix="stt", section="STT", owning_source="machine", inherited_tier=Tier.TUI
            )
            tts_fields = reflect_schema(
                tts_obj, prefix="tts", section="TTS", owning_source="machine", inherited_tier=Tier.TUI
            )
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

        cache_key = _PERSON_CACHE_KEY.format(slug=self._expanded_person)
        cached = self._reflected_cache.get(cache_key)  # type: ignore[call-overload]
        if cached is not None:
            return cached

        slug = self._expanded_person
        person_entry = next((p for p in self._people_data if (p.slug or p.name) == slug), None)
        snapshot = self._people.get(slug)
        if person_entry is None or snapshot is None:
            return []

        render_cycle_id = str(uuid4())
        logger.info("config_tui_person_overlay_requested", schema="PersonConfig", render_cycle_id=render_cycle_id)

        entry_fields = reflect_schema(
            person_entry,
            prefix=_IDENTITY_PREFIX,
            section=_IDENTITY_SECTION_LABEL,
            owning_source=_IDENTITY_SOURCE,
            inherited_tier=Tier.TUI,
        )
        try:
            overlay_fields = reflect_schema(
                _person_overlay(slug, snapshot.section(SETTINGS_SECTION)),
                prefix=_OVERLAY_PREFIX,
                section=_OVERLAY_SECTION_LABEL,
                owning_source=_OVERLAY_SOURCE,
                inherited_tier=Tier.TUI,
            )
        except (TypeError, ValueError, AttributeError) as error:
            self._report_failure(_OVERLAY_UNPRESENTABLE.format(slug=slug), error)
            return []
        bind_environment_references(entry_fields, snapshot.references_under(IDENTITY_SECTION), _IDENTITY_PREFIX)
        bind_environment_references(overlay_fields, snapshot.references_under(SETTINGS_SECTION), _OVERLAY_PREFIX)
        mark_write_only(entry_fields)
        mark_write_only(overlay_fields)
        secret_fields = self._person_secret_fields(self._person_secrets.get(slug))
        fields = entry_fields + overlay_fields + secret_fields
        logger.info(
            "config_tui_person_overlay_rendered",
            render_cycle_id=render_cycle_id,
            output_visibility_fields=list(_OUTPUT_VISIBILITY_FIELDS),
        )
        self._reflected_cache[cache_key] = fields  # type: ignore[index]
        return fields

    @staticmethod
    def _person_secret_fields(inventory: PersonSecretInventory | None) -> list[ReflectedField]:
        """The write-only secret rows of a person: their inventory, or the note that their store is unavailable."""
        if inventory is None:
            return []
        if not inventory.available:
            return [
                ReflectedField(
                    key="secrets.unavailable",
                    name="Personal MCP secrets",
                    field_type=str,
                    value="",
                    section="Secrets",
                    owning_source="personal-mcp-secret",
                    write_only=True,
                    secret_available=False,
                    description="Personal secret storage is unavailable.",
                )
            ]
        return [
            ReflectedField(
                key=f"{_SECRET_KEY_PREFIX}{secret.name}",
                name=secret.name,
                field_type=str,
                value="",
                section=_SECRETS_SECTION_LABEL,
                owning_source=_SECRET_SOURCE,
                environment=EnvironmentProvenance(secret.name, ConfigEnvironment.PERSON),
                write_only=True,
                secret_is_set=secret.is_set,
                requiring_services=secret.requiring_servers,
            )
            for secret in inventory.secrets
        ]

    @property
    def person_editable_fields(self) -> list[str]:
        """Return the keys of person_reflected_fields."""
        return [f.key for f in self.person_reflected_fields]

    def _operations(self) -> ConfigOperations | None:
        """The daemon requests of this tab, or None while the TUI has not connected to the daemon."""
        api = getattr(self.app, _API_ATTRIBUTE, None)
        if api is None or not api.is_connected:
            return None
        return ConfigOperations(api)

    def refresh_data(self) -> None:
        """Ask the daemon for the machine configuration, environment state, and people, and show them."""
        operations = self._operations()
        if operations is None:
            self._load_pending = True
            return
        self._load_pending = False
        self.run_worker(self._load_snapshot(operations), exclusive=True, group=_LOAD_GROUP)

    def load_when_connected(self) -> None:
        """Load the first snapshot once the TUI has connected to the daemon."""
        if self._load_pending:
            self.refresh_data()

    async def _load_snapshot(self, operations: ConfigOperations) -> None:
        """Read the subjects this tab shows, each failure reported where it happened."""
        try:
            machine = await operations.get(ConfigSubjectKind.COMPUTER)
            self._raw_config = machine.section(_COMPUTER_SECTION)
            self._machine_revision = machine.revision
            self._machine_references = machine.references_under(_COMPUTER_SECTION)
            self._outside_scope = machine.outside_scope
        except Exception as exc:
            self._raw_config = {}
            self._machine_revision = None
            self._machine_references = {}
            self._outside_scope = ()
            self._report_failure(_LOAD_MACHINE_FAILED, exc)

        try:
            statuses = await operations.environment_variables()
            self._variable_is_set = {status.info.name: status.is_set for status in statuses}
            self._env_data = [status for status in statuses if status.info.adapter not in self._outside_scope]
        except Exception as exc:
            self._variable_is_set = {}
            self._env_data = []
            self._report_failure(_LOAD_ENV_FAILED, exc)

        self._adapter_sections = project_adapter_sections(self._env_data)
        await self._load_people(operations)
        self._reflected_cache.clear()
        self._clamp_current_cursor()

        if self._guided_mode:
            self._apply_guided_step()
            self._auto_advance_completed_steps()

        self.refresh(layout=True)

    async def _load_people(self, operations: ConfigOperations) -> None:
        """Read the people the operator may see: all of them for an administrator, else their own."""
        self._people = {}
        self._people_data = []
        try:
            try:
                slugs = await operations.list_instances(ConfigSubjectKind.PERSON)
            except ConfigOperationFailed as refusal:
                if refusal.kind is not ConfigFailureKind.REFUSED:
                    raise
                own_slug = await operations.own_person_slug()
                if own_slug is None:
                    raise
                slugs = [own_slug]
            snapshots = await asyncio.gather(*(operations.get(ConfigSubjectKind.PERSON, slug) for slug in slugs))
        except Exception as exc:
            self._report_failure(_LOAD_PEOPLE_FAILED, exc)
            return
        self._people = dict(zip(slugs, snapshots, strict=True))
        self._people_data = [
            _person_entry(slug, snapshot.section(IDENTITY_SECTION)) for slug, snapshot in self._people.items()
        ]
        if self._expanded_person is not None and self._expanded_person in self._people:
            await self._load_person_secrets(operations, self._expanded_person)

    async def _load_person_secrets(self, operations: ConfigOperations, slug: str) -> None:
        try:
            self._person_secrets[slug] = await operations.person_secrets(slug)
        except Exception as exc:
            self._report_failure(_LOAD_SECRETS_FAILED, exc)
        self._reflected_cache.pop(_PERSON_CACHE_KEY.format(slug=slug), None)  # type: ignore[call-overload]

    def _person_overlay_model(self, slug: str) -> PersonConfig:
        """The typed overlay of a person, as the daemon's effective settings give it."""
        snapshot = self._people.get(slug)
        return _person_overlay(slug, snapshot.section(SETTINGS_SECTION) if snapshot is not None else {})

    def load_expanded_person_secrets(self) -> None:
        """Read the expanded person's personal secret inventory from the daemon."""
        operations = self._operations()
        slug = self._expanded_person
        if operations is None or slug is None:
            return
        self.run_worker(self._reload_person_secrets(operations, slug), exclusive=True, group=_SECRETS_GROUP)

    async def _reload_person_secrets(self, operations: ConfigOperations, slug: str) -> None:
        await self._load_person_secrets(operations, slug)
        self.refresh(layout=True)

    def _report_failure(self, prefix: str, error: Exception) -> None:
        """Show a failed request in the status line: the daemon's refusal as it worded it, else the failure."""
        self._status_message = _STATUS_TEMPLATE.format(prefix=prefix, error=error)
        self._status_is_error = True

    def run_validation(self) -> None:
        """Run the full config validation suite and surface the summary."""
        operations = self._operations()
        if operations is None:
            self._status_message = _DAEMON_UNAVAILABLE
            self._status_is_error = True
            self.refresh(layout=True)
            return
        self.run_worker(self._validate(operations), exclusive=True, group=_VALIDATE_GROUP)

    async def _validate(self, operations: ConfigOperations) -> None:
        try:
            self._validation_results = await operations.validate()
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
