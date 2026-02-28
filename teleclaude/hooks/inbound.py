"""Inbound webhook endpoint framework for external platforms."""

from __future__ import annotations

import hashlib
import hmac
import inspect
import json
from typing import Awaitable, Callable, cast

from fastapi import FastAPI, HTTPException, Request, Response
from instrukt_ai_logging import get_logger

from teleclaude.hooks.webhook_models import HookEvent

logger = get_logger(__name__)

# guard: loose-dict - Inbound payload is dynamic JSON.
NormalizerResult = HookEvent | list[HookEvent]
Normalizer = Callable[
    [dict[str, object], dict[str, str]],  # guard: loose-dict - Inbound payload JSON is platform-defined.
    NormalizerResult,
]


class NormalizerRegistry:
    """Registry for inbound payload normalizers."""

    def __init__(self) -> None:
        self._normalizers: dict[str, Normalizer] = {}

    def register(self, key: str, normalizer: Normalizer) -> None:
        self._normalizers[key] = normalizer
        logger.debug("Registered normalizer: %s", key)

    def get(self, key: str) -> Normalizer | None:
        return self._normalizers.get(key)


class InboundEndpointRegistry:
    """Manages dynamic inbound webhook routes on a FastAPI app."""

    def __init__(
        self,
        app: FastAPI,
        normalizer_registry: NormalizerRegistry,
        dispatch: Callable[[HookEvent], Awaitable[None]],
    ) -> None:
        self._app = app
        self._normalizers = normalizer_registry
        self._dispatch = dispatch
        self._registered_paths: set[str] = set()

    def register(
        self,
        path: str,
        normalizer_key: str,
        verify_config: dict[str, object] | None = None,  # guard: loose-dict - Verify config is dynamic JSON
    ) -> None:
        """Register an inbound webhook endpoint.

        Args:
            path: URL path (e.g., "/hooks/whatsapp")
            normalizer_key: Key in NormalizerRegistry
            verify_config: Optional verification config (verify_token, secret, etc.)
        """
        if path in self._registered_paths:
            logger.warning("Inbound path already registered: %s", path)
            return

        config = verify_config or {}

        async def handle_get(request: Request) -> Response:
            """Handle verification challenges (e.g., WhatsApp)."""
            verify_token = config.get("verify_token")
            if not verify_token:
                raise HTTPException(status_code=405, detail="GET not supported for this endpoint")

            params = request.query_params
            mode = params.get("hub.mode")
            token = params.get("hub.verify_token")
            challenge = params.get("hub.challenge")

            if mode == "subscribe" and token == verify_token and challenge:
                logger.info("Verification challenge accepted: %s", path)
                return Response(content=challenge, media_type="text/plain")

            raise HTTPException(status_code=403, detail="Verification failed")

        async def handle_post(request: Request) -> dict[str, str]:
            """Handle incoming webhook payload."""
            body = await request.body()
            headers = {name.lower(): value for name, value in request.headers.items()}

            # Verify signature if configured
            secret = config.get("secret")
            if isinstance(secret, str):
                signature = request.headers.get("X-Hub-Signature-256") or request.headers.get("X-Hook-Signature")
                if not signature:
                    raise HTTPException(status_code=401, detail="Missing signature")
                expected = f"sha256={hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}"
                if not hmac.compare_digest(signature, expected):
                    raise HTTPException(status_code=401, detail="Invalid signature")
            elif secret is not None:
                logger.warning("Ignoring non-string secret config for inbound webhook: %s", normalizer_key)
                raise HTTPException(status_code=500, detail="Invalid webhook secret config")

            try:
                payload = json.loads(body)
            except Exception as exc:
                logger.error("Invalid JSON payload for inbound webhook: %s", path, exc_info=True)
                raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

            normalizer = self._normalizers.get(normalizer_key)
            if not normalizer:
                logger.error("Normalizer not found: %s", normalizer_key)
                raise HTTPException(status_code=500, detail="Normalizer not configured")

            try:
                normalized = self._invoke_normalizer(normalizer, payload, headers)
            except Exception as exc:
                logger.error("Normalization failed: %s error=%s", normalizer_key, exc, exc_info=True)
                raise HTTPException(status_code=400, detail="Failed to normalize payload") from exc

            events: list[HookEvent]
            if isinstance(normalized, list):
                events = normalized
            else:
                events = [normalized]

            try:
                for event in events:
                    await self._dispatch(event)
            except Exception as exc:
                logger.error("Dispatch failed for inbound %s: %s", path, exc, exc_info=True)
                # Return 502 so platforms (WhatsApp, etc.) can retry the delivery.
                raise HTTPException(status_code=502, detail="dispatch error") from exc

            return {"status": "accepted"}

        # Register routes
        self._app.add_api_route(path, handle_get, methods=["GET"], tags=["hooks-inbound"])
        self._app.add_api_route(path, handle_post, methods=["POST"], tags=["hooks-inbound"])
        self._registered_paths.add(path)
        logger.info("Registered inbound endpoint: %s (normalizer=%s)", path, normalizer_key)

    @staticmethod
    # guard: loose-dict-func - Inbound payload structure is dynamic.
    def _invoke_normalizer(
        normalizer: Normalizer,
        payload: dict[str, object],  # guard: loose-dict - Inbound payload is dynamic JSON.
        headers: dict[str, str],
    ) -> NormalizerResult:
        """Invoke normalizer, supporting both old and new signatures."""
        try:
            signature = inspect.signature(normalizer)
        except (TypeError, ValueError):
            normalizer_dynamic = cast(Callable[..., NormalizerResult], normalizer)
            return normalizer_dynamic(payload, headers)

        positional_parameters = [
            param
            for param in signature.parameters.values()
            if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        supports_headers = (
            any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in signature.parameters.values())
            or len(positional_parameters) >= 2
        )

        normalizer_dynamic = cast(Callable[..., NormalizerResult], normalizer)

        if supports_headers:
            return normalizer_dynamic(payload, headers)
        return normalizer_dynamic(payload)
