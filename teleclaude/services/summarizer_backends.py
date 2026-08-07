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

# Summaries are capped at a few dozen words, so this is generous headroom; a model
# that blows through it is ignoring the prompt's word limit rather than needing more.
_MAX_OUTPUT_TOKENS = 200


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
            max_completion_tokens=_MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            response_format=response_format,
        )
        choice = cast(Any, response).choices[0]
        if choice.finish_reason == "length":
            raise ValueError(
                f"output truncated at the {_MAX_OUTPUT_TOKENS}-token budget before the model closed its JSON"
            )
        text = choice.message.content or ""
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
            max_tokens=_MAX_OUTPUT_TOKENS,
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
