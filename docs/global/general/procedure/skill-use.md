---
description: Use the global skills index curated by TeleClaude. This catalog allows agents to discover and use skills without up front awareness. It is a curated list of skills that have been validated and tested and are ready to use. Use when human has requested skill use, or their language implies a need for one, or your current job is in need of a skill.
---

# Skill Use — Procedure

## Goal

Find and use an existing curated TeleClaude skill.

## Preconditions

- The human has requested skill use, or their language implies a need for one, or your current job is in need of a skill.

## Steps

1. **Read the index.** The catalog is deliberately not preloaded, so list it now:

   ```sh
   for f in ~/.teleclaude/skills/*/SKILL.md; do
     awk -v path="$f" '
       /^name:[[:space:]]*/ { n = $0; sub(/^name:[[:space:]]*/, "", n) }
       /^description:[[:space:]]*/ { d = $0; sub(/^description:[[:space:]]*/, "", d) }
       END { if (n != "" && d != "") printf("- %s (%s): %s\n", n, path, d) }
     ' "$f"
   done
   ```

   Each line is one curated skill: its name, its `SKILL.md` path, and what it does.

2. **Use a match.** If a listed skill fits the need, read its `SKILL.md` at the printed
   path and follow it. A skill read this way is usable immediately; it does not need to
   be installed anywhere first. Steps end here.

3. **Escalate a miss.** If nothing matches, follow `general/procedure/skill-management`
   to find a package upstream, verify it, and incorporate it. Fetching and evaluating an
   upstream package needs no approval; adopting one into the catalog or a project does.

## Outputs

- The curated catalog rendered into the session, or an explicit miss.
- On a match, the skill's own instructions loaded and in force for the remaining work.
- A new skill incorporated into the global catalog, or a project-local skill installed into the current project.

## Recovery

- If the listing command prints nothing, no global skill is deployed for this host;
  continue at step 3 rather than assuming the catalog is broken.
- If a listed `SKILL.md` path does not resolve, the catalog pointer is stale — run
  `telec sync` and list again before treating the skill as unavailable.
