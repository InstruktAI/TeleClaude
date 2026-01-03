"""Unit tests for set_dependencies validation logic.

Tests validation rules (tested directly, not via MCP):
1. Circular dependency detection works correctly
2. Dependency read/write functions work correctly
"""

import json
import tempfile
from pathlib import Path

from teleclaude.core.next_machine import (
    detect_circular_dependency,
    read_dependencies,
    write_dependencies,
)
