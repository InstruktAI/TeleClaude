# Demo: fix-core-bugs-round-1

## Validation

```bash
# Demonstrate get_session_data tmux fallback strips ANSI before tail slicing
# using a real tmux pane and a real session row.
python - <<'PY'
import asyncio
import shlex
import subprocess
import uuid

from teleclaude.core import command_handlers
from teleclaude.core.db import db
from teleclaude.config import config
from teleclaude.types.commands import GetSessionDataCommand

session_id = f"demo-ansi-{uuid.uuid4().hex[:8]}"
tmux_name = f"tc_demo_ansi_{uuid.uuid4().hex[:8]}"
ansi_payload = "abc\\033[38;2;181;107;145mX\\033[0mdef"

async def run_demo() -> None:
    if not db.is_initialized():
        await db.initialize()

    tmux_cmd = f"printf {shlex.quote(ansi_payload)}; sleep 15"
    subprocess.run([config.computer.tmux_binary, "new-session", "-d", "-s", tmux_name, tmux_cmd], check=True)

    try:
        await db.create_session(
            computer_name=config.computer.name,
            tmux_session_name=tmux_name,
            last_input_origin="terminal",
            title="Demo ANSI fallback",
            session_id=session_id,
            active_agent="codex",
        )

        await asyncio.sleep(0.2)
        payload = await command_handlers.get_session_data(
            GetSessionDataCommand(session_id=session_id, tail_chars=400)
        )
        messages = str(payload.get("messages", ""))
        print(f"Rendered output tail: {messages!r}")
        if "Xdef" not in messages:
            raise SystemExit(f"Expected sanitized marker 'Xdef' not found: {messages!r}")
        if "\x1b" in messages:
            raise SystemExit(f"Unexpected ANSI escape codes in output: {messages!r}")
    finally:
        subprocess.run([config.computer.tmux_binary, "kill-session", "-t", tmux_name], check=False)
        try:
            await db.delete_session(session_id)
        except Exception:
            pass

asyncio.run(run_demo())
PY
```

## Guided Presentation

1. Run the validation block. It starts a temporary tmux session with ANSI-colored output, registers a real TeleClaude session row, and calls `get_session_data` with a short tail window.
2. Observe `Rendered output tail: ...` containing `Xdef` and no ANSI escapes. This confirms tmux fallback output is stripped before truncation and no ANSI escape fragments leak into the response.
3. Open `todos/fix-core-bugs-round-1/bug.md` and walk through Investigation, Root Cause, and Fix Applied to connect the observed behavior with the implementation.
