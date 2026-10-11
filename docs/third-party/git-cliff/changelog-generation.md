---
description: git-cliff range selection, complete-commit configuration, templating and file output.
---

# git-cliff changelog generation

The CLI accepts an explicit Git revision range and a tag label. Its output and
prepend options write generated sections to files; its context output exposes
commit identities and raw messages to templates. Version bumping is a separate
optional operation.

Configuration can include conventional and unconventional commits without
parsing their messages. Commit parsers, path filters, skip rules, split settings
and commit limits independently affect coverage. A template can render the
commit ID and the first line of the raw message as a linked subject list.
The no-exec option disables configured external command execution.

## Sources

- https://git-cliff.org/docs/usage/args/
- https://git-cliff.org/docs/configuration/git/
- https://git-cliff.org/docs/templating/context/
