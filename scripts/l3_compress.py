#!/usr/bin/env python3
# ruff: noqa: RUF001
"""Compress L1 prose artifacts to L3 symbolic shorthand.

Usage:
    python scripts/l3_compress.py <input_file> [output_file]

If output_file is omitted, writes to <input_file>.l3.md

Uses the Agent Shorthand L3 spec:
- Symbolic compressed, self-disambiguating
- Structural anchors (:=, ∵, parenthetical clarifiers) preserved
- Recoverable from the message itself without shared context
- Cross-model safe (L3 ceiling for different model families)
"""

import asyncio
import re
import sys
from pathlib import Path

import anthropic

# Symbol vocabulary reference embedded in the compression prompt
L3_SPEC = """
## L3 — Symbolic Compressed (target output format)

Core operators:
| Symbol | Meaning                          | Example                  |
| ------ | -------------------------------- | ------------------------ |
| →      | leads to, produces, implies      | 430→73 (430 yields 73)   |
| ✗      | false, rejected, failed          | ?premise →✗              |
| ✓      | true, confirmed, passed          | ✓coherent                |
| ¬      | not, negation                    | ¬degraded                |
| ∴      | therefore, conclusion            | ∴mirror:=recall          |
| ∵      | because, evidence                | ∵agents.summarize()      |
| ⊗      | tension, unresolved              | ⊗file∨sqlite             |  # noqa: RUF001
| ⊢      | assertion, claim                 | ⊢premise✗                |
| ∨      | or, alternative                  | file∨sqlite              |  # noqa: RUF001
| ×      | and (in tension lists)           | ×writer ×trigger         |  # noqa: RUF001
| @      | reference, evidence pointer      | @1c178904                |
| ?      | question, premise under test     | ?sessions=conv           |
| :=     | defined as, equals by definition | mirror:=recall           |

Phase markers:
| Marker      | Meaning                                    |
| ----------- | ------------------------------------------ |
| [inhale]    | Diverging — adding options, not converging |
| [hold]      | Tension identified — sitting with it       |
| [exhale]    | Converging — curating conclusions          |
| [✓exhale]   | Final exhale — ready to write artifacts    |

Example L1 → L3 transformation:

L1 (prose):
"The premise that agent sessions equal conversations is false. Session 1c178904
contains 813KB across 430 entries, but only 73 (17%) are actual text — the rest
are tool use. Agents summarize tool findings in their text responses, which means
the mirror should be a recall artifact, not a degraded transcript. Three tensions
remain unresolved: file vs sqlite storage, writer ownership, and trigger mechanism."

L3 (symbolic compressed):
"?sessions=conv →✗
@1c178904 430→73 17%
✓coherent ∵agents.summarize(tool_findings)→text
∴mirror:=recall ¬degraded
⊗file∨sqlite ×writer ×trigger"  # noqa: RUF001
"""

SYSTEM_PROMPT = f"""You are an L3 shorthand compressor. Your job is to transform L1 prose
documentation into L3 symbolic compressed format.

{L3_SPEC}

## Rules

1. Preserve ALL semantic content. Every rule, constraint, exception, and behavioral
   directive must survive compression. Loss of meaning is unacceptable.
2. Use structural anchors (:=, ∵, parenthetical clarifiers) so the output is
   self-disambiguating — recoverable without shared context.
3. Preserve section headers as-is (# Title, ## Section). These are navigation anchors.
4. Preserve code blocks and command examples verbatim — do not compress CLI syntax,
   code snippets, or bash commands. These are already minimal.
5. Preserve table structures but compress cell content to L3 where possible.
6. Do NOT add explanations, commentary, or metadata. Output only the compressed content.
7. Every assertion, policy rule, or behavioral directive must be individually identifiable
   in the output. Do not merge distinct rules into one symbol.
8. Frontmatter (YAML between --- markers) passes through unchanged.

## Quality bar

A Claude agent reading the L3 output must be able to:
- Follow every policy rule correctly
- Know every tool's syntax and usage
- Make the same behavioral decisions as if reading the L1 original

If in doubt about whether compression loses meaning, keep the L1 form for that fragment.
"""


def split_sections(content: str) -> list[tuple[str, str]]:
    """Split content by --- separators into (title, body) pairs."""
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
    """Compress a single section from L1 to L3. Returns (idx, compressed, original_len, compressed_len)."""
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Compress this section to L3 shorthand:\n\n{body}",
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
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else input_path.with_suffix(".l3.md")

    content = input_path.read_text()
    sections = split_sections(content)

    print(f"Input: {input_path} ({len(content)} chars, {len(sections)} sections)")
    print(f"Output: {output_path}")
    print(f"Compressing {len(sections)} sections in parallel...\n")

    client = anthropic.AsyncAnthropic()

    tasks = [compress_section(client, i, len(sections), title, body) for i, (title, body) in enumerate(sections)]
    results = await asyncio.gather(*tasks)

    # Sort by original index to maintain order
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
