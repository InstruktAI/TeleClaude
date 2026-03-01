# Bug: 

## Symptom

^\\nValueError: invalid literal for int() with base 16: 'co'"
2026-03-01T13:06:59.241Z level=ERROR logger=teleclaude.cli.tui.widgets.banner msg="Banner render crashed" exc="Traceback (most recent call last):\\n  File \"/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/cli/tui/widgets/banner.py\", line 86, in render\\n    return self._render_banner()\\n           ^^^^^^^^^^^^^^^^^^^^^\\n  File \"/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/cli/tui/widgets/banner.py\", line 170, in _render_banner\\n    color_str = _dim_color(color_str, 0.8)\\n                ^^^^^^^^^^^^^^^^^^^^^^^^^^\\n  File \"/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/cli/tui/widgets/banner.py\", line 55, in _dim_color\\n    r = int(int(h[0:2], 16) * factor)\\n            ^^^^^^^^^^^^^^

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-01

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
