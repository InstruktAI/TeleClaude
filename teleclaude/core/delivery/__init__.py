"""Destination-addressed delivery seam: Router, Destination, DeliveryPlan.

See docs/local/spec/session-output-routing.md for the routing contract and
docs/local/design/architecture/adapter-client.md for the Router/Destination
invariants this module implements.
"""

from .models import DeliveryPlan, DeliveryScope, Destination, InvalidDestinationOverrideError
from .router import Router, resolve_destination

__all__ = [
    "DeliveryPlan",
    "DeliveryScope",
    "Destination",
    "InvalidDestinationOverrideError",
    "Router",
    "resolve_destination",
]
