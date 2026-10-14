"""Typed row definitions for todos_db query results."""

from __future__ import annotations

from teleclaude.core.workflow_store.types import (
    ArtifactMetadata as ArtifactMetadataRow,
)
from teleclaude.core.workflow_store.types import (
    ArtifactRemoval as ArtifactRemovalResult,
)
from teleclaude.core.workflow_store.types import (
    ArtifactVersion as ArtifactVersionRow,
)
from teleclaude.core.workflow_store.types import (
    ArtifactWriterSet as ArtifactWritersRow,
)
from teleclaude.core.workflow_store.types import (
    WorkItem as TodoRow,
)

__all__ = ["ArtifactMetadataRow", "ArtifactRemovalResult", "ArtifactVersionRow", "ArtifactWritersRow", "TodoRow"]
