# Claude Code Permission Sandbox Tests

Testing whether `permissions.deny` rules restrict reads when combined with
`--add-dir` for allowed external paths, while keeping all tools auto-approved.

**Expected outcomes:**

| Check | Expected |
|---|---|
| Read `~/.zshrc` | BLOCKED — home dir denied |
| Read `~/.teleclaude/state/` | ALLOWED — added back via `--add-dir` |
| Glob `../../teleclaude/**/*.py` | BLOCKED — outside CWD, not in `--add-dir` |
| `telec version` | ALLOWED — Bash auto-approved, uses `~/.teleclaude/` |

---

## Confirmed working: `--permission-mode acceptEdits` + `--allowedTools 'Bash(*)'`

> Test A (`--dangerously-skip-permissions`) was tried and deny rules were **ignored**.
> Test B (`--permission-mode acceptEdits`) enforced deny rules but blocked Bash.
> This is the fixed version of Test B with Bash auto-approved.

```bash
claude --permission-mode acceptEdits \
  --add-dir ~/.teleclaude \
  --allowedTools 'Bash(*)' \
  --settings '{"permissions":{"deny":["Read(~/**)"]},"forceLoginMethod":"claudeai"}' \
  -p "Perform these four checks in order. 1) Try to read the file ~/.zshrc. 2) Try to list files in ~/.teleclaude/state/. 3) Try to glob ../../teleclaude/**/*.py. 4) Run the shell command: telec version. For each check, attempt it and note whether it succeeded or was blocked by a permission error. Then output ONLY the following report, nothing else:

RESULT: read ~/.zshrc          → [BLOCKED|ALLOWED] (actual: <one line of output or error>)
RESULT: read ~/.teleclaude/    → [BLOCKED|ALLOWED] (actual: <one line of output or error>)
RESULT: glob ../../            → [BLOCKED|ALLOWED] (actual: <file count or error>)
RESULT: telec version          → [BLOCKED|ALLOWED] (actual: <one line of output or error>)
VERDICT: deny rules [ENFORCED|IGNORED] under --permission-mode acceptEdits + --allowedTools Bash(*)"
```

---

## What we learned

| Flag | Deny rules enforced? | Bash auto-approved? |
|---|---|---|
| `--dangerously-skip-permissions` | NO | YES |
| `--permission-mode acceptEdits` | YES | NO |
| `--permission-mode acceptEdits` + `--allowedTools 'Bash(*)'` | YES | YES ← use this |

---

## Worker profile for `constants.py`

```python
"default": (
    "--permission-mode acceptEdits"
    " --add-dir ~/.teleclaude"
    " --add-dir ~/.claude"
    " --allowedTools 'Bash(*)'"
    ' --settings \'{"permissions":{"deny":["Read(~/**)"]},"forceLoginMethod":"claudeai"}\''
),
```
