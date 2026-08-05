# Third Party Skills - Curated by TeleClaude

The global skills in this directory are curated and modified by TeleClaude.

When asked to include or use one in a project, resolve
`~/.teleclaude/skills/{name}` to its exact
`~/.teleclaude/skill-store/{digest}/{name}` target and symlink that immutable
snapshot into the project's `./.agents/skills` directory. Never link the project
through the floating catalog name. Call `telec sync` to make the selected snapshot
available to every enabled agent CLI, then use it as any other project skill. It is
not retroactively added to the current session's preloaded context, but you may read
the installed skill directly.

## Skill index

<!-- @exec: for f in ~/.teleclaude/skills/*/SKILL.md; do awk -v path="$f" 'BEGIN{n="";d=""} /^name:[[:space:]]*/{n=$0; sub(/^name:[[:space:]]*/,"",n)} /^description:[[:space:]]*/{d=$0; sub(/^description:[[:space:]]*/,"",d)} END{if(n!=""&&d!=""){sub(/^skills\//,"./",path); printf("- [%s](%s): %s\n",n,path,d)}}' "$f"; done -->
