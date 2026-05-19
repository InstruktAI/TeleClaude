---
id: 'project/spec/feature/config/trusted-bot-fleet-derivation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'The Telegram trusted_bots list is auto-derived at config load time as the ordered union of the local computer''s bot_username, every remote computer''s bot_username, and explicit trusted_bots entries — with nulls filtered and duplicates removed preserving first-seen order.'
---

# Trusted Bot Fleet Derivation — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

`telegram.trusted_bots` is the allowlist the Telegram adapter consults to decide
which bot usernames may interact with this machine. v1 does NOT take this list
verbatim from YAML. Instead, the config loader DERIVES the effective list at
load time by combining three sources in a fixed order:

1. The local computer's `computer.bot_username` (if any).
2. Each remote computer's `bot_username` (in `remote_computers` map order).
3. Explicit entries from `telegram.trusted_bots` in the YAML config.

Null/missing `bot_username` values are filtered out before merging. The
combined list is then deduplicated via `dict.fromkeys(...)` which preserves
first-seen order while removing repeats. The result becomes
`TelegramConfig.trusted_bots`.

The practical implication: an operator who declares a remote computer with a
`bot_username` does NOT have to also list that bot in
`telegram.trusted_bots` — the fleet entries are auto-merged. Conversely, an
operator listing the same bot in both places sees it appear once (fleet wins
the position; the explicit entry is dropped as a duplicate).

## Canonical fields

### Use cases

#### UC-CFG-FLEET-1: Local bot is included in trusted_bots automatically

```
Given a config with computer.bot_username = "@my-local-bot"
And remote_computers is empty
And telegram.trusted_bots = []
When the config loader runs
Then fleet_bots collects ["@my-local-bot"] (the local entry, filtered for truthy)
And explicit_bots is []
And merged_bots = dict.fromkeys(["@my-local-bot"] + []) = ["@my-local-bot"]
And TelegramConfig.trusted_bots == ["@my-local-bot"]
```

#### UC-CFG-FLEET-2: Remote computer bots are unioned with the local bot

```
Given computer.bot_username = "@local-bot"
And remote_computers has entries "alice" (bot_username "@alice-bot") and "bob" (bot_username "@bob-bot")
And telegram.trusted_bots = []
When the config loader runs
Then fleet_bots = ["@local-bot", "@alice-bot", "@bob-bot"] in remote-computer iteration order
And merged_bots = ["@local-bot", "@alice-bot", "@bob-bot"]
And TelegramConfig.trusted_bots holds all three in that order
```

#### UC-CFG-FLEET-3: Null bot_username values are filtered out

```
Given computer.bot_username is not set (or evaluates falsy in comp_raw.get("bot_username"))
And remote_computers contains one entry whose bot_username is None
And remote_computers contains another entry whose bot_username is "@only-real-bot"
And telegram.trusted_bots = ["@extra"]
When the config loader runs
Then local_bot is None
And the list comprehension `[b for b in [local_bot, *remote_bots] if b]` drops local_bot and the None remote entry
And fleet_bots == ["@only-real-bot"]
And merged_bots == ["@only-real-bot", "@extra"]
```

#### UC-CFG-FLEET-4: Explicit entries are appended to fleet entries

```
Given fleet derivation produces ["@local-bot", "@alice-bot"]
And telegram.trusted_bots = ["@external-bot", "@another-bot"]
When dict.fromkeys(fleet_bots + explicit_bots) runs
Then merged_bots == ["@local-bot", "@alice-bot", "@external-bot", "@another-bot"]
And the explicit entries appear after the fleet entries in the final list
```

#### UC-CFG-FLEET-5: Duplicates between fleet and explicit are removed, fleet position wins

```
Given fleet_bots = ["@local-bot", "@alice-bot"]
And telegram.trusted_bots = ["@alice-bot", "@new-bot"]
When dict.fromkeys(fleet_bots + explicit_bots) runs
Then dict.fromkeys preserves first-seen order and drops the second "@alice-bot"
And merged_bots == ["@local-bot", "@alice-bot", "@new-bot"]
And the position of "@alice-bot" matches its fleet-derived index, not its explicit-list index
```

#### UC-CFG-FLEET-6: Empty fleet AND empty explicit yields empty trusted_bots

```
Given computer.bot_username is unset
And remote_computers is empty
And telegram.trusted_bots = []
When the config loader runs
Then fleet_bots == []
And merged_bots == []
And TelegramConfig.trusted_bots == [] (no error raised; empty allowlist is valid)
```

### Implementation pointers (v1)

- `teleclaude/config/__init__.py:836-842` — fleet derivation: `local_bot` extracted from `comp_raw["bot_username"]`, `fleet_bots` filters null values from `[local_bot, *remote_bot_usernames]`, `merged_bots = list(dict.fromkeys(fleet_bots + explicit_bots))`.
- `teleclaude/config/__init__.py:886-889` — `TelegramConfig(trusted_bots=merged_bots, qos=TelegramQoSConfig())` instantiation.
- `teleclaude/config/__init__.py:177-182` — `TelegramConfig` dataclass declaring `trusted_bots: list[str]`.
- `teleclaude/config/__init__.py:411-413` — the default for `telegram.trusted_bots` in the base config dict is `[]` (explicit entries are optional).
- `teleclaude/config/_remote_computers.py` — `RemoteComputerConfig` dataclass and `parse_remote_computers` mapping; `bot_username` is optional per remote entry.

### Cross-context references

- Consumed by the Telegram adapter to allow-list inbound messages from known bots in the fleet.
- v2 inheritance: `fleet-redis-discovery` (per `v2-agent-runtime`) replaces the YAML-declared remote_computers list with Redis-based self-advertisement. The `remote_computers` schema field and its contribution to fleet bot derivation are slated for full removal in v2; the v2 trusted-bot list will be derived from live fleet topology in Redis instead of static YAML.

## Allowed values

- `computer.bot_username`: any string (typically a Telegram bot handle, e.g., `"@bot_name"`) or null/missing.
- Each `remote_computers.<name>.bot_username`: same shape, or null/missing.
- `telegram.trusted_bots`: list of strings; empty list permitted (default).

## Known caveats

- **No semantic validation of bot handles.** v1 only checks truthiness; any non-empty string passes through. Mistyped handles ("my-bot" without the `@`) reach `TelegramConfig.trusted_bots` unchanged. The adapter is responsible for handle-shape validation, not the schema.
- **Dedup is first-seen order via `dict.fromkeys`.** A duplicate between fleet and explicit lists keeps the FLEET position. An operator who expects their explicit `telegram.trusted_bots` ordering to control the result is mistaken — the fleet always runs first.
- **`tg_raw["trusted_bots"]` is required to exist.** The base config (see `teleclaude/config/__init__.py:411-413`) provides `telegram.trusted_bots: []` as a default; the loader does not guard against the key being absent. A custom raw input that lacks the key entirely will raise a KeyError at line 841.
- **Remote computer iteration order is dict-insertion order.** Python 3.7+ dicts preserve insertion order, so YAML mapping order determines the order of remote bot entries in `fleet_bots`. Reordering the YAML changes the order in `trusted_bots`.
- **The local `bot_username` always appears first when present.** The list literal `[local_bot, *remote_bot_usernames]` is constructed in that order; the local bot's position in the final `trusted_bots` is therefore index 0 (or absent entirely if null).
- **Fleet derivation is computed once at load, not on filesystem changes.** v1 has no watcher; if `remote_computers` or `computer.bot_username` change in the YAML, the daemon must reload to see the new `trusted_bots` list.
- **v2 retires the entire `remote_computers` field.** The `config` domain spec flags this for full removal. Operators relying on the auto-merge from `remote_computers` will need to migrate to the Redis-based fleet discovery model at v2 cutover.
