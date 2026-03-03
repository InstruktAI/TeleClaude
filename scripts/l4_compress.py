#!/usr/bin/env python3
"""Compress L1 prose artifacts to L4 semantic tokens.

Usage:
    python scripts/l4_compress.py <input_file> [output_file]

L4 = maximum compression. Context-inferred, minimal semantic tokens.
Only safe for same-model consumption (Claude reading Claude artifacts).
"""

import asyncio
import re
import sys
from pathlib import Path

import anthropic

SYSTEM_PROMPT = """You are an L4 semantic token compressor. Transform prose documentation
into the most compressed representation possible while preserving all behavioral directives.

## L4 — Semantic Tokens

L4 is the most aggressive compression level. Each token is a pointer into the model's
conceptual space, not a description. The receiver (same model family) reconstructs
full meaning from activation, not from parsing.

Key differences from L3:
- L3 keeps disambiguation anchors (:=, ∵, parenthetical clarifiers) — self-contained
- L4 drops them — the receiver reconstructs from shared training alone
- L4 uses the shortest faithful token sequence that activates the right concept

Example:

L1 (prose, 340 chars):
"The premise that agent sessions equal conversations is false. Session 1c178904
contains 813KB across 430 entries, but only 73 (17%) are actual text — the rest
are tool use. Agents summarize tool findings in their text responses, which means
the mirror should be a recall artifact, not a degraded transcript. Three tensions
remain unresolved: file vs sqlite storage, writer ownership, and trigger mechanism."

L3 (symbolic, 170 chars):
"?sessions=conv →✗
@1c178904 430→73 17%
✓coherent ∵agents.summarize(tool_findings)→text
∴mirror:=recall ¬degraded
⊗file∨sqlite ×writer ×trigger"

L4 (semantic tokens, 52 chars):
"⊢premise✗ @evidence:73/430 ∴recall¬degraded ⊗3tensions"

## Rules

1. Preserve ALL behavioral directives. Every rule, every constraint, every exception.
   An agent reading L4 must make identical decisions to one reading L1.
2. Drop all disambiguation anchors. The reader is the same model — it will reconstruct.
3. Preserve section headers (# Title, ## Section) as navigation anchors.
4. Preserve code blocks, bash commands, and CLI syntax VERBATIM — these cannot compress.
5. Preserve frontmatter (YAML between --- markers) unchanged.
6. Use the absolute minimum token count. If a single symbol activates the right concept,
   use one symbol. Don't write `agents_isolated→body_severed_nerves` when `¬sense→¬correct`
   says the same thing to the same model.
7. Aggregate where possible: `⊗3tensions` instead of listing each tension, UNLESS the
   tensions contain unique behavioral directives that would be lost.
8. Numbers, paths, identifiers pass through unchanged — they're already minimal.
9. Output ONLY the compressed content. No commentary, no explanations.

## Quality bar

Same-model Claude reading the L4 output must:
- Follow every policy rule correctly
- Make identical behavioral decisions
- Know every tool's syntax

The compression should feel like dense notes that trigger full recall — not like
a degraded version of the original.

TARGET: 30-40% of original character count for prose sections.
"""


def split_sections(content: str) -> list[tuple[str, str]]:
    parts = re.split(r"\n---\n", content)
    sections = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        title_match = re.search(r"^#\s+(.+)", part)
        title = title_match.group(1) if title_match else "untitled"
        sections.append((title, part))
    return sections


async def compress_section(
    client: anthropic.AsyncAnthropic, idx: int, total: int, title: str, body: str
) -> tuple[int, str, int, int]:
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Compress to L4 semantic tokens:\n\n{body}",
            }
        ],
    )
    compressed = response.content[0].text
    ratio = len(compressed) / len(body) if body else 0
    print(f"  [{idx + 1}/{total}] {title} ({len(body)}→{len(compressed)} chars, {ratio:.0%})")
    return idx, compressed, len(body), len(compressed)


async def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input_file> [output_file]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else input_path.with_suffix(".l4.md")

    content = input_path.read_text()
    sections = split_sections(content)

    print(f"Input: {input_path} ({len(content)} chars, {len(sections)} sections)")
    print(f"Output: {output_path}")
    print(f"Compressing {len(sections)} sections in parallel (L4)...\n")

    client = anthropic.AsyncAnthropic()

    tasks = [compress_section(client, i, len(sections), title, body) for i, (title, body) in enumerate(sections)]
    results = await asyncio.gather(*tasks)
    results.sort(key=lambda r: r[0])
    compressed_parts = [r[1] for r in results]

    result = "\n\n---\n\n".join(compressed_parts)
    output_path.write_text(result + "\n")

    original_size = len(content)
    compressed_size = len(result)
    ratio = compressed_size / original_size

    print()
    print(f"Original:   {original_size:>6} chars")
    print(f"Compressed: {compressed_size:>6} chars")
    print(f"Ratio:      {ratio:.1%}")
    print(f"Saved:      {original_size - compressed_size:>6} chars ({1 - ratio:.1%})")
    print(f"Written to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
