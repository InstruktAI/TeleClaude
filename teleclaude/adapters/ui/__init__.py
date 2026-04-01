"""UI adapter dataclass components."""

from teleclaude.adapters.ui.output_delivery import DeliveryOptions
from teleclaude.adapters.ui.threaded_output import OverflowContext, OverflowPlan, ThreadDelivery

__all__ = [
    "DeliveryOptions",
    "OverflowContext",
    "OverflowPlan",
    "ThreadDelivery",
]
