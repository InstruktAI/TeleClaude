# Demo: Consolidate Methodology Skills

## Goal

Demonstrate that six methodology skills were added under `agents/skills`, validate through `telec sync --validate-only`, and verify distribution to all runtimes.

## 1) Verify local skill artifacts exist

```bash
set -euo pipefail
for skill in \
  systematic-debugging \
  test-driven-development \
  verification-before-completion \
  brainstorming \
  receiving-code-review \
  frontend-design
  do
  test -f "agents/skills/${skill}/SKILL.md"
  echo "found agents/skills/${skill}/SKILL.md"
done
```

Expected result: all six skill files are present.

## 2) Validate artifacts via TeleClaude sync validator

```bash
set -euo pipefail
telec sync --validate-only >/tmp/telec-sync-validate.log

echo "telec sync --validate-only exited 0"
```

Expected result: command exits successfully.

## 3) Verify runtime distribution

```bash
set -euo pipefail
for runtime in "$HOME/.claude/skills" "$HOME/.codex/skills" "$HOME/.gemini/skills"
do
  echo "runtime=${runtime}"
  for skill in \
    systematic-debugging \
    test-driven-development \
    verification-before-completion \
    brainstorming \
    receiving-code-review \
    frontend-design
  do
    test -f "${runtime}/${skill}/SKILL.md"
    echo "  distributed ${skill}"
  done
done
```

Expected result: all six skills exist in each runtime directory.
