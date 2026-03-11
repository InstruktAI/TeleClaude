"""Delivery adapters — push notifications to external channels."""

from teleclaude.events.delivery.discord import DiscordDeliveryAdapter
from teleclaude.events.delivery.telegram import TelegramDeliveryAdapter
from teleclaude.events.delivery.whatsapp import WhatsAppDeliveryAdapter

__all__ = ["DiscordDeliveryAdapter", "TelegramDeliveryAdapter", "WhatsAppDeliveryAdapter"]
