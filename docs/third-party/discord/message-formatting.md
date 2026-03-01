# Discord Message Formatting

## Purpose

Reference for Discord message formatting capabilities relevant to bot output rendering.

## Supported Markdown

### Text styling

| Syntax | Result |
|--------|--------|
| `**text**` | Bold |
| `*text*` or `_text_` | Italics |
| `***text***` | Bold italics |
| `__text__` | Underline |
| `~~text~~` | Strikethrough |
| `` `code` `` | Inline code |
| ` ```lang ``` ` | Fenced code block (30+ languages) |

### Structure

| Syntax | Result |
|--------|--------|
| `# Heading` | H1 (also `##`, `###`) |
| `-# text` | Subtext (small, de-emphasized) |
| `> quote` | Block quote (single line) |
| `>>> quote` | Block quote (multi-line) |
| `- item` or `* item` | Unordered list |
| `1. item` | Ordered list |
| `[text](url)` | Masked link |

### Content hiding

| Syntax | Result |
|--------|--------|
| `\|\|text\|\|` | Spoiler tag — blurred until clicked |

Spoiler tags are the **only** native mechanism for hiding content in Discord messages. There is no collapsible/expandable section support.

## Not Supported

- **HTML `<details>/<summary>` tags**: Not rendered. Discord does not process HTML in messages.
- **Collapsible/accordion sections**: No native support. Frequently requested but not implemented.
- **Expandable embed fields**: Embeds have no collapsible field option.

## Workarounds for Collapsible Content

For long content that should be collapsed by default (e.g., agent thinking blocks):

| Approach | Mechanism | UX |
|----------|-----------|-----|
| **Spoiler tags** | `\|\|thinking content\|\|` | Blurred inline, click to reveal. Works at any length. No summary label — the hidden block cannot be prefixed with a visible description that groups visually with it. |
| **File attachment** | Send content as `.txt` or `.md` file | Discord renders a collapsible file preview with expand button. Has a visible filename as summary label. |
| **Truncation** | Show first N chars, append `...` | Loses content; not truly collapsible. |

### Spoiler tags for thinking blocks

Spoiler tags work well for hiding thinking content. The content is blurred and revealed on click. Works at any length. The limitation is purely cosmetic: there is no built-in way to attach a visible label (like "Thinking...") that visually groups with the spoiler block. A workaround is to place the label on the line above:

```
**Thinking:**
||The agent's reasoning content here...||
```

### File attachment for thinking blocks

File attachments provide a labeled collapsible with the filename as the summary. Discord displays attached text files with a compact preview that users can expand inline.

```python
# discord.py example
import io

thinking_file = discord.File(
    io.BytesIO(thinking_text.encode()),
    filename="thinking.md",
)
await channel.send(content=response_text, file=thinking_file)
```

## Sources

- [Discord Markdown Text 101](https://support.discord.com/hc/en-us/articles/210298617)
- [Discord Spoiler Tags](https://support.discord.com/hc/en-us/articles/360022320632)
- [Discord Developer Portal](https://discord.com/developers/docs)
