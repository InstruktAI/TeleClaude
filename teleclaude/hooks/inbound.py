"""Inbound webhook endpoint framework for external platforms."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from instrukt_ai_logging import get_logger

from teleclaude.hooks.webhook_models import HookEvent

logger = get_logger(__name__)

Normalizer = Callable[[dict[str, Any]], HookEvent]  # guard: loose-dict - Inbound payload is dynamic JSON


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
        verify_config: dict[str, Any] | None = None,  # guard: loose-dict - Verify config is dynamic JSON
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

            # Verify signature if configured
            secret = config.get("secret")
            if secret:
                signature = request.headers.get("X-Hub-Signature-256") or request.headers.get("X-Hook-Signature")
                if not signature:
                    raise HTTPException(status_code=401, detail="Missing signature")
                expected = f"sha256={hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}"
                if not hmac.compare_digest(signature, expected):
                    raise HTTPException(status_code=401, detail="Invalid signature")

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
                event = normalizer(payload)
            except Exception as exc:
                logger.error("Normalization failed: %s error=%s", normalizer_key, exc, exc_info=True)
                raise HTTPException(status_code=400, detail="Failed to normalize payload") from exc

            try:
                await self._dispatch(event)
            except Exception as exc:
                logger.error("Dispatch failed for inbound %s: %s", path, exc, exc_info=True)
                # Return 200 anyway to prevent platform retries
                return {"status": "accepted", "warning": "dispatch error"}

            return {"status": "accepted"}

        # Register routes
        self._app.add_api_route(path, handle_get, methods=["GET"], tags=["hooks-inbound"])
        self._app.add_api_route(path, handle_post, methods=["POST"], tags=["hooks-inbound"])
        self._registered_paths.add(path)
        logger.info("Registered inbound endpoint: %s (normalizer=%s)", path, normalizer_key)
