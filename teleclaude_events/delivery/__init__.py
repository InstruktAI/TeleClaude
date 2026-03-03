"""Delivery adapters — push notifications to external channels."""

from teleclaude_events.delivery.discord import DiscordDeliveryAdapter
from teleclaude_events.delivery.telegram import TelegramDeliveryAdapter
from teleclaude_events.delivery.whatsapp import WhatsAppDeliveryAdapter

__all__ = ["DiscordDeliveryAdapter", "TelegramDeliveryAdapter", "WhatsAppDeliveryAdapter"]
