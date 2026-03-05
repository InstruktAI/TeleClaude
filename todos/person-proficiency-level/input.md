# person-proficiency-level — Input

## Person Proficiency Level — Feature

Add a `proficiency` field to PersonEntry so agents know the human's proficiency level at session start and derive all behavioral calibration from it.

### What

One field on the person: `proficiency: novice | intermediate | advanced | expert`

- **novice** — little to no technical proficiency
- **intermediate** — understands technology at a user level
- **advanced** — understands how systems work technically
- **expert** — deep systems and architectural understanding

Stored in global config:

```yaml
people:
  - name: Maurice Faber
    email: maurice@instrukt.ai
    role: admin
    proficiency: expert
```

### Why

Agents currently have no way to know who they're talking to. They ask questions that the human can't answer (novice) or doesn't want to answer (expert). Communication is at the wrong level. The proficiency level is the single static fact from which agents derive all behavioral calibration — communication register, autonomy level, what to surface vs handle silently.

The agent reads "expert" and knows: full autonomy, dense communication, architecture-level only, almost never ask. The agent reads "novice" and knows: lead everything, explain simply, never ask technical questions, take them by the hand. No behavioral mapping table needed — the agent is a language model and knows what these words mean.

### How — injection chain

1. `_print_memory_injection()` in `teleclaude/hooks/receiver.py` (line 235) already fires on AGENT_SESSION_START
2. It already reads the session row from DB (line 250), has `row.human_email`
3. Extend it to look up the matching PersonEntry from global config to get `proficiency`
4. Prepend one line to the memory context: `Human in the loop: Maurice Faber (expert)`
5. Flows through existing `adapter.format_memory_injection()` → stdout → additionalContext

### Files to change

1. **`teleclaude/config/schema.py`** — add `proficiency: Literal["novice", "intermediate", "advanced", "expert"] = "intermediate"` to `PersonEntry`
2. **`teleclaude/hooks/receiver.py`** — extend `_print_memory_injection()` to look up person entry by human_email from global config, prepend proficiency line to context
3. **`teleclaude/cli/config_cli.py`** — add `--proficiency` to `_people_add()` and `_people_edit()`, add to `PersonInfo` dataclass
4. **`teleclaude/api_models.py`** — add `proficiency` to `PersonDTO`

### Behavioral contract

The proficiency level is a static fact, not a behavioral directive. It gets overridden in-the-moment by existing principles:

- Attunement senses when the human needs something different than the default
- Autonomy policy's escalation gates still apply regardless of proficiency level
- If the human is upset or the agent is making wrong decisions, real-time signals override the proficiency-based defaults

Default for new people: `intermediate` (safe middle ground).
