"""Core Router: session -> DeliveryPlan, and per-platform Destination resolution.

Consolidates the recipient-selection resolvers formerly inlined in
``core/adapter_client/_output.py`` (``_resolve_origin_ui_adapter``,
``_resolve_admin_output_target``, ``_resolve_final_output_targets``,
``_origin_section_has_channel``) and the per-platform coordinate resolution
formerly inlined in each adapter (Discord's ``_resolve_destination_channel``
override precedence, Telegram's ``user_id``-derived chat_id, WhatsApp's
``phone_number``).

Router operates on plain session data and the set of currently-registered UI
adapter type keys — never on adapter instances — so this module has no
adapter imports (``software-development`` adapter-boundaries: core never
imports adapter modules).
"""

from collections.abc import Iterable

from teleclaude.core.models import (
    DiscordAdapterMetadata,
    MessageMetadata,
    Session,
    WhatsAppAdapterMetadata,
)

from .models import (
    MESSAGE_INTENT_TO_SCOPE,
    DeliveryPlan,
    DeliveryScope,
    Destination,
    InvalidDestinationOverrideError,
    MessageIntent,
)


def _parse_required_int(value: object) -> int:
    """Parse an explicit override value, raising when it cannot be parsed.

    Unlike a session-derived default (absent means "no destination"), a
    caller-supplied override that is present but malformed is a contract
    error — never a cue to silently fall back to a different recipient.
    """
    text = str(value).strip()
    if not text.isdigit():
        raise InvalidDestinationOverrideError(f"metadata.channel_id override {value!r} is not a valid channel id")
    return int(text)


def resolve_destination(session: Session, platform: str, *, metadata: MessageMetadata | None = None) -> Destination:
    """Resolve a session's concrete delivery coords for one platform.

    Pure coordinate resolution only — no live platform I/O, no scope/intent
    decision. Honors the Discord ``metadata.channel_id`` override ahead of
    the session-derived default (precedence:
    ``metadata.channel_id -> discord.thread_id -> discord.channel_id``).
    A present-but-malformed override raises ``InvalidDestinationOverrideError``
    rather than silently falling back to the session-derived channel.
    """
    if platform == "discord":
        metadata_channel_id = _parse_required_int(metadata.channel_id) if metadata and metadata.channel_id else None
        discord_meta = DiscordAdapterMetadata.from_dict(session.get_origin_section("discord"))
        return Destination(
            platform="discord",
            session_id=session.session_id,
            channel_id=metadata_channel_id or discord_meta.thread_id or discord_meta.channel_id,
        )
    if platform == "telegram":
        user_id = session.origin_metadata.get("user_id") or session.origin_metadata.get("telegram_user_id")
        return Destination(
            platform="telegram",
            session_id=session.session_id,
            chat_id=int(str(user_id)) if user_id else None,
        )
    if platform == "whatsapp":
        whatsapp_meta = WhatsAppAdapterMetadata.from_dict(session.get_origin_section("whatsapp"))
        return Destination(
            platform="whatsapp",
            session_id=session.session_id,
            phone_number=whatsapp_meta.phone_number,
            last_customer_message_at=whatsapp_meta.last_customer_message_at,
        )
    return Destination(platform=platform, session_id=session.session_id)


class Router:
    """Resolve a session's recipients: which UI adapter(s), and their Destinations."""

    def __init__(self, registered_ui_adapters: Iterable[str]) -> None:
        self._registered = frozenset(registered_ui_adapters)

    def resolve_origin_ui_adapter(self, session: Session) -> str | None:
        """Return the session's origin adapter when it is a registered UI adapter."""
        origin_adapter = (session.last_input_origin or "").strip()
        if not origin_adapter or origin_adapter not in self._registered:
            return None
        return origin_adapter

    def resolve_admin_output_target(self, session: Session, origin_adapter: str | None) -> str | None:
        """Return "discord" when the session is eligible for the admin output copy.

        - System-role sessions skip (integrator/finalizer/worker noise).
        - Discord-origin sessions skip (origin delivery already hits Discord).
        - Discord must be a registered UI adapter.
        """
        if session.system_role:
            return None
        if origin_adapter == "discord":
            return None
        if "discord" not in self._registered:
            return None
        return "discord"

    @staticmethod
    def origin_section_has_channel(session: Session, adapter_type: str) -> bool:
        """Return True when the adapter has a resolvable delivery destination for this session.

        Telegram delivers through the private-chat ``chat_id`` (derived from
        ``user_id``/``telegram_user_id``), not the origin section's ``topic_id`` —
        checked via the same ``resolve_destination`` the live delivery path uses,
        so final-output repair and live delivery agree on origin viability.
        """
        if adapter_type == "telegram":
            return resolve_destination(session, "telegram").chat_id is not None
        origin_section = session.get_origin_section(adapter_type)
        if not origin_section:
            return False
        if adapter_type == "discord":
            discord_meta = DiscordAdapterMetadata.from_dict(origin_section)
            return discord_meta.thread_id is not None or discord_meta.channel_id is not None
        if adapter_type == "whatsapp":
            whatsapp_meta = WhatsAppAdapterMetadata.from_dict(origin_section)
            return whatsapp_meta.conversation_id is not None or whatsapp_meta.phone_number is not None
        return False

    def resolve_final_output_targets(self, session: Session) -> set[str]:
        """Return the explicit UI adapters eligible for final-output repair.

        Dual-lane contract (mirrors live ``send_output_update``):
        - origin UI adapter when its channel was provisioned
        - Discord admin copy when the session is eligible
        """
        targets: set[str] = set()
        origin_adapter = self.resolve_origin_ui_adapter(session)
        if origin_adapter is not None and self.origin_section_has_channel(session, origin_adapter):
            targets.add(origin_adapter)
        admin_target = self.resolve_admin_output_target(session, origin_adapter)
        if admin_target is not None:
            targets.add(admin_target)
        return targets

    def plan(
        self,
        session: Session,
        message_intent: MessageIntent,
        *,
        metadata: MessageMetadata | None = None,
    ) -> DeliveryPlan:
        """Resolve ``(session, message_intent)`` to a full :class:`DeliveryPlan`.

        Scope follows ``project/spec/session-output-routing#message-intent-to-scope-mapping``.
        """
        scope = MESSAGE_INTENT_TO_SCOPE[message_intent]
        if scope is DeliveryScope.CTRL:
            return DeliveryPlan(scope=scope)

        origin_adapter = self.resolve_origin_ui_adapter(session)
        origin_endpoint = (
            resolve_destination(session, origin_adapter, metadata=metadata) if origin_adapter is not None else None
        )

        if scope is DeliveryScope.ORIGIN_ONLY:
            return DeliveryPlan(scope=scope, origin_endpoint=origin_endpoint)

        admin_target = self.resolve_admin_output_target(session, origin_adapter)
        admin_lane = (
            (resolve_destination(session, admin_target, metadata=metadata),) if admin_target is not None else ()
        )

        if scope is DeliveryScope.ADMIN_ONLY:
            return DeliveryPlan(scope=scope, admin_lane_destinations=admin_lane)

        return DeliveryPlan(scope=scope, origin_endpoint=origin_endpoint, admin_lane_destinations=admin_lane)
