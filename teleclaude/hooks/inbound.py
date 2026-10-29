"""The ingress's inbound endpoints: verify an external request, translate it, relay it onto the event stream.

Three fixed route groups serve every home. The path names the declaring home, and
the home's own configuration, read when the request arrives, opens or closes the
endpoint. A request is verified under that home's secret over the raw body before
it is parsed, translated into one or more ``<domain>.<name>`` events, and emitted
on the platform event stream with the ingress as origin, the declared inbound source
as subject and the declaring home as home. Delivery to this computer's handlers and to every other computer's is the
stream consumers' work (``teleclaude.hooks.relay_delivery``); the request path
dispatches nothing itself.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from http import HTTPMethod
from typing import Final, cast
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request, Response
from instrukt_ai_logging import get_logger

from teleclaude.config.inbound_sources import (
    InboundDeclarationError,
    declared_inbound_sources,
    declared_whatsapp_source,
)
from teleclaude.config.schema import ProjectInboundSources, WhatsAppInboundSource
from teleclaude.config_subjects import ConfigSubjectKind
from teleclaude.core.models import JsonDict
from teleclaude.events.envelope import (
    EventHome,
    EventHomeKind,
    EventHomeMarker,
    EventHomeRef,
    EventLevel,
    EventVisibility,
)
from teleclaude.events.producer import EventProducer, RelayedEvent
from teleclaude.events.references import InboundSourceRef
from teleclaude.events.wire import LegacyFacts
from teleclaude.hooks.normalizers.github import github_event_type
from teleclaude.hooks.normalizers.whatsapp import whatsapp_message_type, whatsapp_messages
from teleclaude.hooks.relay_delivery import RelayProtocol, relayed_hook_event

logger = get_logger(__name__)

INBOUND_PATH_PREFIX: Final = "/hooks/inbound"

_INBOUND_WEBHOOK_EVENT_ACCEPTED = "inbound_webhook_event_accepted"
_INBOUND_WEBHOOK_REFUSED = "inbound_webhook_refused"
_INBOUND_WEBHOOK_RELAY_FAILED = "inbound_webhook_relay_failed"
# Longer than a provider's redelivery window, so a redelivered request is still recognised (ADR-0148).
_CLAIM_TTL_S: Final = 3 * 24 * 3600
_INBOUND_DECLARATION_UNREADABLE = "inbound_declaration_unreadable"
_SECRET_FIELD = "secret"
_VERIFY_TOKEN_FIELD = "verify_token"
_ROUTE_TAG = "hooks-inbound"
_HOME_DESCRIPTION = "{kind}/{slug}"
_SOURCE_IDENTITY = "{protocol}:{home}"
_GLOBAL_SOURCE_HOME = "global"
_NO_HOME = "-"
_WHATSAPP_ROUTE = INBOUND_PATH_PREFIX + "/whatsapp"
_GITHUB_ROUTE = INBOUND_PATH_PREFIX + "/github/project/{slug}"
_NATIVE_ROUTE = INBOUND_PATH_PREFIX + "/{kind}/{slug}"

_NATIVE_SIGNATURE_HEADER = "X-Hook-Signature"
_HUB_SIGNATURE_HEADER = "X-Hub-Signature-256"
_HANDSHAKE_MODE = "subscribe"
_HANDSHAKE_MODE_PARAM = "hub.mode"
_HANDSHAKE_TOKEN_PARAM = "hub.verify_token"
_HANDSHAKE_CHALLENGE_PARAM = "hub.challenge"
_PLAIN_TEXT = "text/plain"
_CONTENT_TYPE_HEADER = "content-type"
_MEDIA_TYPE_PARAMETER_SEPARATOR = ";"
_FORM_MEDIA_TYPE: Final = "application/x-www-form-urlencoded"
_FORM_ENCODING = "utf-8"
_FORM_DECODE_ERRORS = "strict"
_GITHUB_FORM_FIELD = "payload"
_ACCEPTED_BODY: Final = {"status": "accepted"}

_NATIVE_SEGMENT = re.compile(r"^[a-z][a-z0-9_]*$")
_NAME_SEPARATOR = "."
_WHATSAPP_DOMAIN = RelayProtocol.WHATSAPP.value
_GITHUB_DOMAIN = RelayProtocol.GITHUB.value

_DETAIL_NOT_FOUND = "No such endpoint"
_DETAIL_DECLARATION_UNREADABLE = "Inbound declaration unreadable"
_DETAIL_MISSING_SIGNATURE = "Missing signature"
_DETAIL_INVALID_SIGNATURE = "Invalid signature"
_DETAIL_INVALID_PAYLOAD = "Invalid payload"
_DETAIL_VERIFICATION_FAILED = "Verification failed"
_DETAIL_RELAY_ERROR = "Relay error"

_STATUS_NOT_FOUND = 404
_STATUS_UNAUTHORIZED = 401
_STATUS_FORBIDDEN = 403
_STATUS_BAD_REQUEST = 400
_STATUS_SERVER_ERROR = 500
_STATUS_BAD_GATEWAY = 502


class _Refusal(StrEnum):
    """Why an inbound request was refused."""

    NO_ENDPOINT = "no_endpoint"
    DECLARATION_UNREADABLE = "declaration_unreadable"
    MISSING_SIGNATURE = "missing_signature"
    INVALID_SIGNATURE = "invalid_signature"
    INVALID_BODY = "invalid_body"
    VERIFICATION_FAILED = "verification_failed"


_REFUSAL_RESPONSES: Final[Mapping[_Refusal, tuple[int, str]]] = {
    _Refusal.NO_ENDPOINT: (_STATUS_NOT_FOUND, _DETAIL_NOT_FOUND),
    _Refusal.DECLARATION_UNREADABLE: (_STATUS_SERVER_ERROR, _DETAIL_DECLARATION_UNREADABLE),
    _Refusal.MISSING_SIGNATURE: (_STATUS_UNAUTHORIZED, _DETAIL_MISSING_SIGNATURE),
    _Refusal.INVALID_SIGNATURE: (_STATUS_UNAUTHORIZED, _DETAIL_INVALID_SIGNATURE),
    _Refusal.INVALID_BODY: (_STATUS_BAD_REQUEST, _DETAIL_INVALID_PAYLOAD),
    _Refusal.VERIFICATION_FAILED: (_STATUS_FORBIDDEN, _DETAIL_VERIFICATION_FAILED),
}


class _InvalidBody(Exception):
    """A verified request whose body does not fit its protocol."""


@dataclass(frozen=True)
class _Endpoint:
    """One resolved endpoint: who declared it, how its requests are signed, and the home its events belong to."""

    protocol: RelayProtocol
    home: str
    secret: str
    signature_header: str
    declaring_home: EventHome


@dataclass(frozen=True)
class _RelayedEvent:
    """One event a verified request translates into."""

    domain: str
    name: str
    payload: dict[str, object]  # guard: loose-dict - Producer or provider payload is relayed uninterpreted.


def _refuse(refusal: _Refusal, protocol: RelayProtocol, home: str) -> HTTPException:
    """Log a refusal and return the response that carries it. Neither the log nor the response holds a secret."""
    logger.warning(_INBOUND_WEBHOOK_REFUSED, reason=refusal.value, protocol=protocol.value, home=home)
    status, detail = _REFUSAL_RESPONSES[refusal]
    return HTTPException(status_code=status, detail=detail)


def compute_signature(body: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature for webhook payload."""
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def _verify_signature(body: bytes, presented: str | None, endpoint: _Endpoint) -> None:
    """Check the signature over the raw body in constant time, before any parsing."""
    if not presented:
        raise _refuse(_Refusal.MISSING_SIGNATURE, endpoint.protocol, endpoint.home)
    if not hmac.compare_digest(presented, compute_signature(body, endpoint.secret)):
        raise _refuse(_Refusal.INVALID_SIGNATURE, endpoint.protocol, endpoint.home)


class _NativeField(StrEnum):
    """The three members of a native request body."""

    DOMAIN = "domain"
    NAME = "name"
    PAYLOAD = "payload"


def _native_event_name(domain: object, name: object) -> tuple[str, str]:
    """Return the domain and the ``<domain>.<name>`` event name, refusing any malformed segment."""
    if not isinstance(domain, str) or not isinstance(name, str):
        raise _InvalidBody
    segments = (domain, *name.split(_NAME_SEPARATOR))
    if not all(_NATIVE_SEGMENT.match(segment) for segment in segments):
        raise _InvalidBody
    return domain, _NAME_SEPARATOR.join(segments)


# guard: loose-dict-func - A request body document is third-party JSON, relayed uninterpreted.
def _json_object(raw: str | bytes) -> dict[str, object]:
    """Parse a JSON document that must be an object."""
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise _InvalidBody
    return document


# guard: loose-dict-func - A request body document is third-party JSON, relayed uninterpreted.
def _read_json_body(_headers: Mapping[str, str], body: bytes) -> dict[str, object]:
    """Read a body that is the JSON document itself."""
    return _json_object(body)


# guard: loose-dict-func - A request body document is third-party JSON, relayed uninterpreted.
def _read_github_body(headers: Mapping[str, str], body: bytes) -> dict[str, object]:
    """Read a GitHub delivery body: the JSON document itself, or GitHub's form encoding of it.

    A form-encoded delivery (``application/x-www-form-urlencoded``, GitHub's default webhook content type)
    carries the document as the single form field ``payload``.
    """
    media_type = headers.get(_CONTENT_TYPE_HEADER)
    if (
        media_type is None
        or media_type.split(_MEDIA_TYPE_PARAMETER_SEPARATOR, 1)[0].strip().lower() != _FORM_MEDIA_TYPE
    ):
        return _json_object(body)
    try:
        fields = parse_qs(
            body.decode(_FORM_ENCODING), keep_blank_values=True, strict_parsing=True, errors=_FORM_DECODE_ERRORS
        )
    except ValueError as error:  # malformed form, or bytes that are not UTF-8 (UnicodeDecodeError is a ValueError)
        raise _InvalidBody from error
    payloads = fields.get(_GITHUB_FORM_FIELD, [])
    if len(fields) != 1 or len(payloads) != 1:
        raise _InvalidBody
    return _json_object(payloads[0])


# guard: loose-dict - Body readers receive the request headers and raw body and return third-party request JSON.
_BODY_READERS: Final[Mapping[RelayProtocol, Callable[[Mapping[str, str], bytes], dict[str, object]]]] = {
    RelayProtocol.NATIVE: _read_json_body,
    RelayProtocol.GITHUB: _read_github_body,
    RelayProtocol.WHATSAPP: _read_json_body,
}


# guard: loose-dict-func - The native request body is third-party JSON, relayed uninterpreted.
def _translate_native(body: dict[str, object], _headers: Mapping[str, str]) -> list[_RelayedEvent]:
    """Translate a native request: exactly a domain, a name and an opaque payload object."""
    payload = body.get(_NativeField.PAYLOAD)
    if set(body) != set(_NativeField) or not isinstance(payload, dict):
        raise _InvalidBody
    domain, event_name = _native_event_name(body[_NativeField.DOMAIN], body[_NativeField.NAME])
    return [_RelayedEvent(domain=domain, name=event_name, payload=payload)]


# guard: loose-dict-func - GitHub webhook payload is third-party JSON.
def _translate_github(body: dict[str, object], headers: Mapping[str, str]) -> list[_RelayedEvent]:
    """Translate a GitHub delivery into ``github.<event>`` carrying the delivery body."""
    event_type = github_event_type(dict(headers))
    return [_RelayedEvent(domain=_GITHUB_DOMAIN, name=_NAME_SEPARATOR.join((_GITHUB_DOMAIN, event_type)), payload=body)]


# guard: loose-dict-func - WhatsApp webhook payload is third-party JSON.
def _translate_whatsapp(body: dict[str, object], _headers: Mapping[str, str]) -> list[_RelayedEvent]:
    """Translate a WhatsApp webhook into one ``whatsapp.message.<type>`` event per message, in order."""
    return [
        _RelayedEvent(
            domain=_WHATSAPP_DOMAIN,
            name=_NAME_SEPARATOR.join((_WHATSAPP_DOMAIN, whatsapp_message_type(message))),
            payload=message,
        )
        for message in whatsapp_messages(body)
    ]


# guard: loose-dict - Translators receive third-party request JSON and relay it uninterpreted.
_TRANSLATORS: Final[Mapping[RelayProtocol, Callable[[dict[str, object], Mapping[str, str]], list[_RelayedEvent]]]] = {
    RelayProtocol.NATIVE: _translate_native,
    RelayProtocol.GITHUB: _translate_github,
    RelayProtocol.WHATSAPP: _translate_whatsapp,
}


def _declaration_failure(home: str, protocol: RelayProtocol, error: InboundDeclarationError) -> HTTPException:
    """Log an unreadable declaration at error with the home and the cause, and return the server error."""
    logger.error(_INBOUND_DECLARATION_UNREADABLE, home=home, protocol=protocol.value, cause=str(error.cause))
    return _refuse(_Refusal.DECLARATION_UNREADABLE, protocol, home)


def _present_secret(value: str | None, field: str, protocol: RelayProtocol, home: str) -> str:
    """Return a declared source's secret; one with no value on the ingress leaves the declaration unreadable.

    Validation on the ingress already refuses such a declaration, so this only narrows the type.
    """
    if value is None:
        logger.error(_INBOUND_DECLARATION_UNREADABLE, home=home, protocol=protocol.value, cause=field)
        raise _refuse(_Refusal.DECLARATION_UNREADABLE, protocol, home)
    return value


def _home_kind(kind: str) -> EventHomeKind | None:
    try:
        return EventHomeKind(kind)
    except ValueError:
        return None


async def _resolve_native(kind: str, slug: str) -> _Endpoint:
    home = _HOME_DESCRIPTION.format(kind=kind, slug=slug)
    home_kind = _home_kind(kind)
    if home_kind is None:
        raise _refuse(_Refusal.NO_ENDPOINT, RelayProtocol.NATIVE, home)
    try:
        sources = await asyncio.to_thread(declared_inbound_sources, ConfigSubjectKind(home_kind.value), slug)
    except InboundDeclarationError as error:
        raise _declaration_failure(home, RelayProtocol.NATIVE, error) from error
    if sources is None or sources.native is None:
        raise _refuse(_Refusal.NO_ENDPOINT, RelayProtocol.NATIVE, home)
    return _Endpoint(
        protocol=RelayProtocol.NATIVE,
        home=home,
        secret=_present_secret(sources.native.secret, _SECRET_FIELD, RelayProtocol.NATIVE, home),
        signature_header=_NATIVE_SIGNATURE_HEADER,
        declaring_home=EventHomeRef(home_kind, slug),
    )


async def _resolve_github(slug: str) -> _Endpoint:
    home = _HOME_DESCRIPTION.format(kind=EventHomeKind.PROJECT.value, slug=slug)
    try:
        sources = await asyncio.to_thread(declared_inbound_sources, ConfigSubjectKind.PROJECT, slug)
    except InboundDeclarationError as error:
        raise _declaration_failure(home, RelayProtocol.GITHUB, error) from error
    if not isinstance(sources, ProjectInboundSources) or sources.github is None:
        raise _refuse(_Refusal.NO_ENDPOINT, RelayProtocol.GITHUB, home)
    return _Endpoint(
        protocol=RelayProtocol.GITHUB,
        home=home,
        secret=_present_secret(sources.github.secret, _SECRET_FIELD, RelayProtocol.GITHUB, home),
        signature_header=_HUB_SIGNATURE_HEADER,
        declaring_home=EventHomeRef(EventHomeKind.PROJECT, slug),
    )


async def _load_whatsapp_source() -> WhatsAppInboundSource:
    try:
        source = await asyncio.to_thread(declared_whatsapp_source)
    except InboundDeclarationError as error:
        raise _declaration_failure(_NO_HOME, RelayProtocol.WHATSAPP, error) from error
    if source is None:
        raise _refuse(_Refusal.NO_ENDPOINT, RelayProtocol.WHATSAPP, _NO_HOME)
    return source


async def _resolve_whatsapp() -> _Endpoint:
    source = await _load_whatsapp_source()
    return _Endpoint(
        protocol=RelayProtocol.WHATSAPP,
        home=_NO_HOME,
        secret=_present_secret(source.secret, _SECRET_FIELD, RelayProtocol.WHATSAPP, _NO_HOME),
        signature_header=_HUB_SIGNATURE_HEADER,
        declaring_home=EventHomeMarker.NONE,
    )


def _claim_identity(endpoint: _Endpoint, headers: Mapping[str, str], body: bytes) -> str:
    """The identity a delivery is claimed under, within its authenticated source.

    The source (protocol and declaring home) leads it, so two sources never share a claim. GitHub's own
    delivery id identifies a GitHub delivery, and a digest of the verified body identifies every other one.
    The delivery id header is not signed. Within its source, a request that replays a body the source signed
    can present any id: it can relay that body again, or claim an id the source will deliver later, which a
    GitHub event shares across Apps, so the id can be known in advance.
    """
    delivery_id = headers.get("x-github-delivery") if endpoint.protocol is RelayProtocol.GITHUB else None
    delivery = delivery_id or hashlib.sha256(body).hexdigest()
    return f"{endpoint.protocol.value}:{endpoint.home}:{delivery}"


class InboundRelay:
    """Verify, translate and relay inbound requests for one ingress computer."""

    def __init__(self, producer: EventProducer) -> None:
        self._producer = producer

    async def relay(self, request: Request, endpoint: _Endpoint) -> dict[str, str]:
        """Handle one signed POST: verify the raw body, read its document per protocol, translate it, emit each event."""
        body = await request.body()
        _verify_signature(body, request.headers.get(endpoint.signature_header), endpoint)
        headers = {k.lower(): v for k, v in request.headers.items()}
        try:
            document = _BODY_READERS[endpoint.protocol](headers, body)
            relayed = _TRANSLATORS[endpoint.protocol](document, headers)
        except (json.JSONDecodeError, _InvalidBody) as error:
            raise _refuse(_Refusal.INVALID_BODY, endpoint.protocol, endpoint.home) from error
        delivery = _claim_identity(endpoint, headers, body)
        for index, event in enumerate(relayed):
            await self._emit(endpoint, event, claim=f"{delivery}:{index}")
        return dict(_ACCEPTED_BODY)

    async def _emit(self, endpoint: _Endpoint, event: _RelayedEvent, *, claim: str) -> None:
        relayed = RelayedEvent(
            type=event.name,
            subject=InboundSourceRef(
                _SOURCE_IDENTITY.format(
                    protocol=endpoint.protocol.value,
                    home=_GLOBAL_SOURCE_HOME if endpoint.home == _NO_HOME else endpoint.home,
                )
            ),
            home=endpoint.declaring_home,
            data=cast(JsonDict, event.payload),
            time=datetime.now(UTC),
        )
        legacy = LegacyFacts(
            producer=endpoint.protocol.value,
            level=EventLevel.BUSINESS,
            domain=event.domain,
            visibility=EventVisibility.CLUSTER,
        )
        hook_event = relayed_hook_event(self._producer.stage(relayed, legacy))
        try:
            entry_id = await self._producer.emit_once(relayed, legacy, claim=claim, ttl_s=_CLAIM_TTL_S)
        except Exception as error:
            logger.error(
                _INBOUND_WEBHOOK_RELAY_FAILED,
                event=event.name,
                protocol=endpoint.protocol.value,
                home=endpoint.home,
                exc_info=True,
            )
            # A transient failure so the sender retries the delivery.
            raise HTTPException(status_code=_STATUS_BAD_GATEWAY, detail=_DETAIL_RELAY_ERROR) from error
        if entry_id is None:
            # Another receipt of this delivery relayed it; this one is accepted and relays nothing.
            logger.info(
                "inbound_webhook_duplicate_dropped", event=event.name, protocol=endpoint.protocol.value, claim=claim
            )
            return
        logger.info(
            _INBOUND_WEBHOOK_EVENT_ACCEPTED,
            source=hook_event.source,
            type=hook_event.type,
            event_ts=hook_event.timestamp,
            event=event.name,
            protocol=endpoint.protocol.value,
            subject=endpoint.home,
        )


def install_inbound_routes(app: FastAPI, producer: EventProducer) -> None:
    """Mount the three fixed inbound route groups on the API app."""
    relay = InboundRelay(producer)

    async def whatsapp_handshake(request: Request) -> Response:
        """Answer Meta's subscription handshake against the declared verify token."""
        source = await _load_whatsapp_source()
        verify_token = _present_secret(source.verify_token, _VERIFY_TOKEN_FIELD, RelayProtocol.WHATSAPP, _NO_HOME)
        params = request.query_params
        token = params.get(_HANDSHAKE_TOKEN_PARAM)
        challenge = params.get(_HANDSHAKE_CHALLENGE_PARAM)
        if (
            params.get(_HANDSHAKE_MODE_PARAM) != _HANDSHAKE_MODE
            or token is None
            or not hmac.compare_digest(token, verify_token)
            or not challenge
        ):
            raise _refuse(_Refusal.VERIFICATION_FAILED, RelayProtocol.WHATSAPP, _NO_HOME)
        return Response(content=challenge, media_type=_PLAIN_TEXT)

    async def whatsapp_post(request: Request) -> dict[str, str]:
        """Relay a WhatsApp webhook."""
        return await relay.relay(request, await _resolve_whatsapp())

    async def github_post(slug: str, request: Request) -> dict[str, str]:
        """Relay a GitHub delivery for a project."""
        return await relay.relay(request, await _resolve_github(slug))

    async def native_post(kind: str, slug: str, request: Request) -> dict[str, str]:
        """Relay a native event for a company, person or project."""
        return await relay.relay(request, await _resolve_native(kind, slug))

    app.add_api_route(_WHATSAPP_ROUTE, whatsapp_handshake, methods=[HTTPMethod.GET], tags=[_ROUTE_TAG])
    app.add_api_route(_WHATSAPP_ROUTE, whatsapp_post, methods=[HTTPMethod.POST], tags=[_ROUTE_TAG])
    app.add_api_route(_GITHUB_ROUTE, github_post, methods=[HTTPMethod.POST], tags=[_ROUTE_TAG])
    app.add_api_route(_NATIVE_ROUTE, native_post, methods=[HTTPMethod.POST], tags=[_ROUTE_TAG])
