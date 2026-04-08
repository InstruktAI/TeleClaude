You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM that will resume the task.

Include:

- Current progress and key decisions made
- Important context, constraints, or user preferences
- What remains to be done (clear next steps)
- Any critical data, examples, or references needed to continue

Be concise, structured, and focused on helping the next LLM seamlessly continue the work.

When compacting context, preserve verbatim every byte between
`<!-- TELECLAUDE_CONTEXT_PRESERVATION_START -->` and
`<!-- TELECLAUDE_CONTEXT_PRESERVATION_END -->`.

Keep the markers themselves. Do not summarize, normalize, reformat, reorder, or
delete any enclosed content. Copy it forward exactly as-is across every
compaction cycle before the compaction output. This ensures that all critical information is retained
