"""Cluster node event declarations: the node, as a computer, is the subject."""

from __future__ import annotations

from teleclaude.events.catalog import DeclaredEvent, EventData, PlatformEvent
from teleclaude.events.references import ComputerRef


class NodeData(EventData):
    """A node event states everything in its type and subject."""


class NodeAlive(PlatformEvent[ComputerRef, NodeData]):
    NAME = "teleclaude.node.alive"
    DESCRIPTION = "Node heartbeat or presence announcement"


class NodeLeaving(PlatformEvent[ComputerRef, NodeData]):
    NAME = "teleclaude.node.leaving"
    DESCRIPTION = "Node is departing the cluster gracefully"


class NodeDescriptorUpdated(PlatformEvent[ComputerRef, NodeData]):
    NAME = "teleclaude.node.descriptor_updated"
    DESCRIPTION = "Node metadata or capabilities changed"


DECLARED: tuple[DeclaredEvent, ...] = (NodeAlive, NodeLeaving, NodeDescriptorUpdated)
