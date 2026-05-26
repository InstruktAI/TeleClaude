"""Vendor-SDK summarizer backends.

Isolates provider SDK calls from core logic per the adapter-boundaries policy:
core orchestration (provider ordering, config, parsing) lives in
``teleclaude.core.summarizer`` and depends only on these narrow callables — it
never imports a vendor SDK directly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from openai.types.shared_params.response_format_json_schema import ResponseFormatJSONSchema


async def summarize_openai_compatible(
    prompt: str,
    schema: dict[str, object],  # guard: loose-dict - JSON schema shape is dynamic.
    parser: Callable[[str], Any],
    *,
    base_url: str | None,
    api_key: str,
    model: str,
) -> Any:
    """Call any OpenAI-compatible chat-completions endpoint (cloud OpenAI, LM Studio, Gemini)."""
    response_format: ResponseFormatJSONSchema = {
        "type": "json_schema",
        "json_schema": {"name": "summary", "schema": schema, "strict": True},
    }
    async with AsyncOpenAI(api_key=api_key, base_url=base_url) as client:
        response = await client.chat.completions.create(
            model=model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
            response_format=response_format,
        )
        text = cast(Any, response).choices[0].message.content or ""
    return parser(text)


async def summarize_anthropic(
    prompt: str,
    schema: dict[str, object],  # guard: loose-dict - JSON schema shape is dynamic.
    parser: Callable[[str], Any],
    *,
    api_key: str,
    model: str,
) -> Any:
    """Call Anthropic's structured-output messages API."""
    async with AsyncAnthropic(api_key=api_key) as client:
        response = await client.beta.messages.create(
            model=model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
            betas=["structured-outputs-2025-11-13"],
            output_format={
                "type": "json_schema",
                "schema": {
                    "type": schema["type"],
                    "properties": schema["properties"],
                    "required": schema["required"],
                    "additionalProperties": schema["additionalProperties"],
                },
            },
        )
        text = response.content[0].text  # type: ignore[union-attr]
    return parser(text)
