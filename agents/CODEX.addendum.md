# Codex Addendum

## Preserve the User's Distinctions

- Codex collapses qualified boundaries into simpler binary rules. Preserve the distinctions the user is drawing and optimize for their intended meaning rather than the narrowest literal parse.
- A tests-only scope never authorizes production changes. When a failing test references a missing symbol, inspect the removing commit and trace transitive callers before deciding whether the test or production code is stale; never restore deliberately removed production code under a tests-only scope.
- When the human challenges whether Codex read the governing source, stop answering from recall and read it before continuing.

## Do Not Replace a Silent Worker

- Codex reacts to startup silence by probing, restarting, or duplicating work. Silence alone proves none of those actions necessary. Never restart or duplicate a dispatched worker from silence; first read the authoritative session record and investigate concrete evidence.

## Preserve Durable Operations

- Durable-operation invocation uses a 600-second outer yield. When a CLI owns polling a durable receipt, give it that terminal bound; never treat an early yield as completion or take over receipt polling.

## Preserve Other Work

- Codex treats a dirty tree as cleanup work. Dirty tracked files, staged changes, untracked files, and generated-looking drift outside the current task belong to another actor unless evidence proves otherwise.
- Never revert, normalize, restage, reformat, or otherwise clean out-of-scope work. Isolate the requested path scope. If an out-of-scope change blocks a required action, report the blocker rather than undoing it.
- Restore an accidental out-of-scope edit only when Codex's exact delta is mechanically distinguishable; otherwise leave it untouched and surface the ambiguity.

## Preserve Command Shape

- Never create a todo without an explicit `--kind`.
- When passing Markdown or prose through a shell, use a single-quoted argument with correct embedded-quote handling. Never place prose containing backticks or shell substitutions inside double quotes.
