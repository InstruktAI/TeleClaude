# Third Party Skills - Curated by TeleClaude

The global skills in this directory are curated and modified by TeleClaude.

When asked to include or use one in a project just symlink the `~/.teleclaude/skills/{name}` skill folder into that project's `./.agents/skills` directory and call `telec sync` which results in the skill made locally available to all agent CLIs, then use the skill as you would any other skill (its not available by then in your preloaded context but you can read the skill directly).

## Skill index

<!-- @exec: for f in ~/.teleclaude/skills/*/SKILL.md; do awk -v path="$f" 'BEGIN{n="";d=""} /^name:[[:space:]]*/{n=$0; sub(/^name:[[:space:]]*/,"",n)} /^description:[[:space:]]*/{d=$0; sub(/^description:[[:space:]]*/,"",d)} END{if(n!=""&&d!=""){sub(/^skills\//,"./",path); printf("- [%s](%s): %s\n",n,path,d)}}' "$f"; done -->
