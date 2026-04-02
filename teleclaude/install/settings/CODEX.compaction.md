When compacting context, preserve verbatim every byte between
`<!-- TELECLAUDE_CONTEXT_PRESERVATION_START -->` and
`<!-- TELECLAUDE_CONTEXT_PRESERVATION_END -->`.

Keep the markers themselves. Do not summarize, normalize, reformat, reorder, or
delete any enclosed content. Copy it forward exactly as-is across every
compaction cycle.
