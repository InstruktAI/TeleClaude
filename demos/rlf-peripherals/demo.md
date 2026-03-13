# Demo: rlf-peripherals

Structural decomposition of 6 large peripheral modules into focused packages.
No behavior changes — only internal file organization.

## Validation

Verify each module was decomposed into a package and no file exceeds the hard ceiling.

```bash
# All 6 original flat files must be gone
for f in \
  teleclaude/helpers/youtube_helper.py \
  teleclaude/hooks/checkpoint.py \
  teleclaude/resource_validation.py \
  teleclaude/hooks/receiver.py \
  "teleclaude/utils/transcript.py" \
  teleclaude/transport/redis_transport.py; do
  if [ -f "$f" ]; then
    echo "FAIL: $f still exists as flat file"
    exit 1
  fi
done
echo "OK: all 6 flat files replaced by packages"
```

```bash
# Packages must exist and be importable
.venv/bin/python -c "
from teleclaude.helpers.youtube_helper import YouTubeHelper
from teleclaude.hooks.checkpoint import CheckpointManager
from teleclaude.resource_validation import ResourceValidator
from teleclaude.hooks.receiver import ReceiverApp
from teleclaude.utils.transcript import parse_claude_transcript, render_agent_output
from teleclaude.transport.redis_transport import RedisTransport
print('OK: all 6 packages import correctly')
"
```

```bash
# No module exceeds 800-line hard ceiling
python_files=$(find \
  teleclaude/helpers/youtube_helper/ \
  teleclaude/hooks/checkpoint/ \
  teleclaude/hooks/receiver/ \
  teleclaude/transport/redis_transport/ \
  teleclaude/utils/transcript/ \
  -name "*.py" 2>/dev/null)

resource_files=$(find teleclaude/resource_validation/ -name "*.py" 2>/dev/null)

failed=0
for f in $python_files $resource_files; do
  lines=$(wc -l < "$f")
  if [ "$lines" -gt 800 ]; then
    echo "FAIL: $f has $lines lines (max 800)"
    failed=1
  fi
done

if [ "$failed" -eq 0 ]; then
  echo "OK: all submodules within 800-line ceiling"
fi
[ "$failed" -eq 0 ]
```

```bash
# Tests must pass
make test 2>&1 | grep -E "passed|failed|error"
```

## Guided Presentation

Each of the 6 original modules was >1000 lines. The decomposition creates packages
with backward-compatible `__init__.py` re-exports, so all existing call sites work
unchanged.

**Package structures:**

- `youtube_helper/` — 4 modules: `_api.py`, `_transcript.py`, `_channel.py`, `_main.py`
- `checkpoint/` — 4 modules: `_injection.py`, `_session.py`, `_output.py`, `_main.py`
- `resource_validation/` — 3 modules split by validation domain
- `receiver/` — focused modules for hook reception logic
- `transcript/` — 7 modules: parsers, utils, block renderers, iterators, rendering, extraction, tool calls
- `redis_transport/` — 9 mixin modules: connection, refresh, messaging, heartbeat, pull, peers, request/response, adapter no-ops, main class
