"""Standalone helper functions for agent_coordinator.

Contains pure/stateless functions used by AgentCoordinator and its mixins,
plus the _SuppressionState dataclass and module-level constants.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from teleclaude.constants import (
    CHECKPOINT_MESSAGE,
    CHECKPOINT_PREFIX,
)
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.origins import InputOrigin

if TYPE_CHECKING:
    from teleclaude.core.models import Session

_NOOP_LOG_INTERVAL_SECONDS = 30.0
_MAX_FORWARDED_LINK_OUTPUT_CHARS = 12000

SESSION_START_MESSAGES = [
    "Standing by with grep patterns locked and loaded. What can I find?",
    "Warmed up and ready to hunt down that bug!",
    "Cache cleared, mind fresh. What's the task?",
    "All systems nominal, ready to ship some code!",
    "Initialized and ready to make those tests pass. What needs fixing?",
    "Compiled with optimism and ready to refactor!",
    "Ready to turn coffee into code. Where do we start?",
    "Standing by like a well-indexed database!",
    "Alert and ready to parse whatever you need. What's up?",
    "Primed to help you ship that feature!",
    "Spun up and ready to debug. What's broken?",
    "Loaded and eager to make things work!",
    "Ready to dig into the details. What should I investigate?",
    "All systems go for some serious coding!",
    "Prepared to tackle whatever you throw at me. What's the challenge?",
    "Standing by to help ship something awesome!",
    "Ready to make the build green. What needs attention?",
    "Warmed up and waiting to assist!",
    "Initialized and ready to solve problems. What's the issue?",
    "All set to help you build something great!",
]


@dataclass
class _SuppressionState:
    """Tracks repeated no-op events so logs can be sampled."""

    signature: str
    started_at: datetime
    last_log_at: datetime
    suppressed: int = 0


def _is_checkpoint_prompt(
    prompt: str,
    *,
    raw_payload: object = None,
) -> bool:
    """Return True when prompt text is our system checkpoint message.

    Matches both the generic Phase 1 message and context-aware Phase 2
    messages by checking known prefixes.  Codex synthetic input detection
    truncates captured prompt text, so we also accept 40-char prefixes of
    the generic constant for synthetic events.
    """
    prompt_clean = (prompt or "").strip()
    if not prompt_clean:
        return False

    # Canonical prefix match covers all checkpoint variants.
    if prompt_clean.startswith(CHECKPOINT_PREFIX):
        return True

    # Exact match for the generic constant (backward compat).
    checkpoint_clean = CHECKPOINT_MESSAGE.strip()
    if prompt_clean == checkpoint_clean:
        return True

    # Truncated Codex synthetic prompt (from output polling / fast-poll)
    is_codex_synthetic = False
    if isinstance(raw_payload, dict):
        source = raw_payload.get("source")
        is_codex_synthetic = (
            bool(raw_payload.get("synthetic")) and isinstance(source, str) and source.startswith("codex_")
        )

    if is_codex_synthetic and len(prompt_clean) >= 40 and checkpoint_clean.startswith(prompt_clean):
        return True

    return False


def _is_codex_synthetic_prompt_event(raw_payload: object) -> bool:
    """Return True for Codex synthetic prompt events derived from output polling."""
    if not isinstance(raw_payload, Mapping):
        return False
    source = raw_payload.get("source")
    return bool(raw_payload.get("synthetic")) and isinstance(source, str) and source.startswith("codex_")


def _has_active_output_message(session: "Session") -> bool:
    """Check if any adapter has an active output message in metadata."""
    meta = session.get_metadata().get_ui()
    return bool(
        meta.get_telegram().output_message_id
        or meta.get_discord().output_message_id
        or meta.get_whatsapp().output_message_id
    )


def _coerce_nonempty_str(value: object) -> str | None:
    """Normalize value to a non-empty string when possible."""
    if value is None:
        return None
    text = value.strip() if isinstance(value, str) else str(value).strip()
    return text or None


def _resolve_hook_actor_name(session: "Session") -> str:
    """Resolve actor label for hook-reflected user input."""
    ui_meta = session.get_metadata().get_ui()
    telegram_user_id = ui_meta.get_telegram().user_id
    discord_user_id = ui_meta.get_discord().user_id
    whatsapp_phone = _coerce_nonempty_str(ui_meta.get_whatsapp().phone_number)

    origin_hint = (session.last_input_origin or "").strip().lower()
    resolver = get_identity_resolver()

    def _resolve_identity_name(origin: str, channel_meta: Mapping[str, object]) -> str | None:
        identity = resolver.resolve(origin, channel_meta)
        if not identity:
            return None
        return _coerce_nonempty_str(identity.person_name)

    if origin_hint == InputOrigin.TELEGRAM.value and telegram_user_id is not None:
        telegram_meta: Mapping[str, object] = {
            "user_id": str(telegram_user_id),
            "telegram_user_id": str(telegram_user_id),
        }
        resolved = _resolve_identity_name(InputOrigin.TELEGRAM.value, telegram_meta)
        if resolved:
            return resolved

    if origin_hint == InputOrigin.DISCORD.value and discord_user_id:
        discord_meta: Mapping[str, object] = {
            "user_id": str(discord_user_id),
            "discord_user_id": str(discord_user_id),
        }
        resolved = _resolve_identity_name(InputOrigin.DISCORD.value, discord_meta)
        if resolved:
            return resolved

    if origin_hint == InputOrigin.WHATSAPP.value and whatsapp_phone:
        whatsapp_meta: dict[str, object] = {  # guard: loose-dict - Identity resolver channel metadata is dynamic.
            "phone_number": whatsapp_phone
        }
        resolved = _resolve_identity_name(InputOrigin.WHATSAPP.value, whatsapp_meta)
        if resolved:
            return resolved

    if telegram_user_id is not None:
        telegram_meta = {
            "user_id": str(telegram_user_id),
            "telegram_user_id": str(telegram_user_id),
        }
        resolved = _resolve_identity_name(InputOrigin.TELEGRAM.value, telegram_meta)
        if resolved:
            return resolved

    if discord_user_id:
        discord_meta = {
            "user_id": str(discord_user_id),
            "discord_user_id": str(discord_user_id),
        }
        resolved = _resolve_identity_name(InputOrigin.DISCORD.value, discord_meta)
        if resolved:
            return resolved

    if whatsapp_phone:
        whatsapp_meta = {"phone_number": whatsapp_phone}
        resolved = _resolve_identity_name(InputOrigin.WHATSAPP.value, whatsapp_meta)
        if resolved:
            return resolved

    human_email = _coerce_nonempty_str(session.human_email)
    if human_email:
        return human_email

    if origin_hint == InputOrigin.TELEGRAM.value and telegram_user_id is not None:
        return f"telegram:{telegram_user_id}"
    if origin_hint == InputOrigin.DISCORD.value and discord_user_id:
        return f"discord:{discord_user_id}"
    if origin_hint == InputOrigin.WHATSAPP.value and whatsapp_phone:
        return f"whatsapp:{whatsapp_phone}"
    if telegram_user_id is not None:
        return f"telegram:{telegram_user_id}"
    if discord_user_id:
        return f"discord:{discord_user_id}"
    if whatsapp_phone:
        return f"whatsapp:{whatsapp_phone}"

    return "operator"


def _to_utc(ts: datetime) -> datetime:
    """Normalize naive datetimes to UTC for stable comparisons."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _is_codex_input_already_recorded(
    session: "Session | None",
    prompt_text: str,
) -> bool:
    """Return True when session state already reflects this Codex prompt turn."""
    if not session:
        return False

    existing_prompt = (session.last_message_sent or "").strip()
    candidate_prompt = (prompt_text or "").strip()
    if not existing_prompt or not candidate_prompt:
        return False
    prompts_match = (
        existing_prompt == candidate_prompt
        or existing_prompt.startswith(candidate_prompt)
        or candidate_prompt.startswith(existing_prompt)
    )
    if not prompts_match:
        return False
    if not isinstance(session.last_message_sent_at, datetime):
        return False

    message_at = _to_utc(session.last_message_sent_at)
    if not isinstance(session.last_output_at, datetime):
        return True
    feedback_at = _to_utc(session.last_output_at)
    return message_at > feedback_at
