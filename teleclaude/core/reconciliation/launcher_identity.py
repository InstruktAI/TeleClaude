"""Decision owner for machine-local launcher signing and installation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

_REMEDY_STORE = "Restore the dedicated launcher signing store, then rerun install."
_REMEDY_STORE_REGISTRATION = "Restore access to the user keychain search list, then rerun launcher signing."
_REMEDY_SECRET = "Restore the machine-local unlock secret with its private permissions, then rerun install."
_REMEDY_AUTHORIZATION = "Authorize the signing key for unattended codesign use, then rerun install."
_REMEDY_EXPIRED = "Renew the launcher authority deliberately; its Full Disk Access grants must be reissued."
_REMEDY_KEY = "Restore the private key for the existing authority or renew it deliberately."
_REMEDY_TIMEOUT = "Resolve the blocked signing step and rerun install."
_REMEDY_BUILD = "Resolve the launcher build failure and rerun install."
_REMEDY_VERIFY = "Resolve the launcher signature mismatch and rerun install."
_REMEDY_SIGN = "Resolve the signing tool failure or key access, then rerun install."
_REMEDY_PUBLISH = "Resolve the destination filesystem failure, then rerun install."
_REMEDY_GENERAL = "Resolve the reported launcher signing cause and rerun install."
_INVALID_RECORD = "The stored launcher build record is invalid."


class LauncherIdentityIntent(StrEnum):
    """Supported entry intents for the launcher identity operation."""

    CONVERGE = "converge"
    BUILD = "build"
    RENEW = "renew"


class LauncherBuildDisposition(StrEnum):
    """Resulting launcher build action."""

    REBUILT = "rebuilt"
    NOTHING_TO_DO = "nothing_to_do"


class LauncherIdentityFailureCause(StrEnum):
    """Closed reasons that stop a launcher identity convergence run."""

    STORE_UNOPENABLE = "store_unopenable"
    SECRET_UNAVAILABLE = "secret_unavailable"
    STORE_REGISTRATION_FAILED = "store_registration_failed"
    KEY_NOT_AUTHORIZED = "key_not_authorized"
    EXPIRED = "expired"
    NO_KEY = "no_key"
    TIMEOUT = "timeout"
    COMPILE_FAILED = "compile_failed"
    SIGN_FAILED = "sign_failed"
    PUBLISH_FAILED = "publish_failed"
    VERIFICATION_FAILED = "verification_failed"
    AUTHORITY_FAILED = "authority_failed"
    RECORD_INVALID = "record_invalid"


@dataclass(frozen=True)
class LauncherBundleSignature:
    """Verified signature identity of one installed or staged launcher."""

    bundle_name: str
    path: Path
    fingerprint: str
    identifier: str
    code_directory_hash: str


@dataclass(frozen=True)
class LauncherBuildRecord:
    """Persisted correspondence between launcher inputs and installed bundles."""

    input_digest: str
    authority_fingerprint: str
    bundle_hashes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class LauncherAuthorityReadiness:
    """Observed readiness of the opened machine signing authority."""

    fingerprint: str
    expired: bool
    has_private_key: bool
    key_authorized: bool


@dataclass(frozen=True)
class LauncherIdentityResult:
    """Published outcome of one launcher identity operation."""

    disposition: LauncherBuildDisposition | None
    authority_fingerprint: str | None
    authority_created: bool
    failure_cause: LauncherIdentityFailureCause | None
    remedy: str
    regrant_bundle_names: tuple[str, ...]


class LauncherIdentityEffects(Protocol):
    """Typed operating-system and filesystem effects required by the decision owner."""

    def signing_store_exists(self) -> bool: ...

    def current_input_digest(self) -> str: ...

    def read_build_record(self) -> LauncherBuildRecord | None: ...

    def write_build_record(self, record: LauncherBuildRecord) -> None: ...

    def delete_build_record(self) -> None: ...

    def required_bundle_names(self) -> tuple[str, ...]: ...

    def installed_bundle_signature(self, bundle_name: str) -> LauncherBundleSignature | None: ...

    def ensure_signing_store(self) -> str: ...

    def register_signing_store(self) -> None: ...

    def authority_readiness(self, secret: str) -> LauncherAuthorityReadiness: ...

    def create_authority(self, secret: str) -> str: ...

    def renew_authority(self, secret: str, fingerprint: str) -> str: ...

    def current_authority_fingerprint(self) -> str | None: ...

    def build_verified_set(self, fingerprint: str) -> tuple[LauncherBundleSignature, ...]: ...

    def installed_bundle_signatures(self) -> tuple[LauncherBundleSignature, ...]: ...

    def install_verified_set(self, bundles: tuple[LauncherBundleSignature, ...]) -> None: ...

    def publish_build_set(self, bundles: tuple[LauncherBundleSignature, ...]) -> None: ...

    def cleanup_staging(self) -> None: ...


def converge_launcher_identity(
    intent: LauncherIdentityIntent,
    effects: LauncherIdentityEffects,
) -> LauncherIdentityResult:
    """Converge launcher code identity through one decision path."""
    if intent is LauncherIdentityIntent.CONVERGE:
        try:
            record = effects.read_build_record()
            current = record is not None and _installed_set_is_current(effects, record)
        except LauncherIdentityError as error:
            return _failed(error.cause)
        if current and record is not None:
            return LauncherIdentityResult(
                LauncherBuildDisposition.NOTHING_TO_DO,
                record.authority_fingerprint,
                False,
                None,
                _EMPTY,
                (),
            )

    try:
        secret = effects.ensure_signing_store()
    except LauncherIdentityError as error:
        return _failed(error.cause)

    try:
        current_fingerprint = effects.current_authority_fingerprint()
        created = current_fingerprint is None or intent is LauncherIdentityIntent.RENEW
        if intent is LauncherIdentityIntent.RENEW and current_fingerprint is not None:
            effects.delete_build_record()
            fingerprint = effects.renew_authority(secret, current_fingerprint)
        elif current_fingerprint is None:
            effects.delete_build_record()
            fingerprint = effects.create_authority(secret)
        else:
            fingerprint = current_fingerprint
        effects.register_signing_store()
        readiness = effects.authority_readiness(secret)
    except LauncherIdentityError as error:
        return _failed(error.cause)

    if readiness.expired:
        return _failed(LauncherIdentityFailureCause.EXPIRED, fingerprint)
    if not readiness.has_private_key:
        return _failed(LauncherIdentityFailureCause.NO_KEY, fingerprint)
    if not readiness.key_authorized:
        return _failed(LauncherIdentityFailureCause.KEY_NOT_AUTHORIZED, fingerprint)
    fingerprint = readiness.fingerprint

    try:
        bundles = effects.build_verified_set(fingerprint)
    except LauncherIdentityError as error:
        effects.cleanup_staging()
        return _failed(error.cause, fingerprint, created)

    if intent is LauncherIdentityIntent.BUILD:
        try:
            effects.publish_build_set(bundles)
        except LauncherIdentityError as error:
            effects.cleanup_staging()
            return _failed(error.cause, fingerprint, created)
        effects.cleanup_staging()
        return LauncherIdentityResult(LauncherBuildDisposition.REBUILT, fingerprint, created, None, _EMPTY, ())

    try:
        prior_signatures = effects.installed_bundle_signatures()
        regrant_names = tuple(
            sorted(signature.bundle_name for signature in prior_signatures if signature.fingerprint != fingerprint)
        )
        effects.install_verified_set(bundles)
        input_digest = effects.current_input_digest()
        installed = effects.installed_bundle_signatures()
        if {signature.bundle_name for signature in installed} != set(effects.required_bundle_names()):
            raise LauncherIdentityError(LauncherIdentityFailureCause.VERIFICATION_FAILED)
        record = LauncherBuildRecord(
            input_digest,
            fingerprint,
            tuple(sorted((signature.bundle_name, signature.code_directory_hash) for signature in installed)),
        )
        effects.write_build_record(record)
    except LauncherIdentityError as error:
        effects.cleanup_staging()
        return _failed(error.cause, fingerprint, created)
    effects.cleanup_staging()
    return LauncherIdentityResult(LauncherBuildDisposition.REBUILT, fingerprint, created, None, _EMPTY, regrant_names)


def _installed_set_is_current(effects: LauncherIdentityEffects, record: LauncherBuildRecord) -> bool:
    if not effects.signing_store_exists():
        return False
    if record.input_digest != effects.current_input_digest():
        return False
    hashes = dict(record.bundle_hashes)
    names = effects.required_bundle_names()
    if set(hashes) != set(names):
        return False
    for bundle_name in names:
        try:
            signature = effects.installed_bundle_signature(bundle_name)
        except LauncherIdentityError:
            return False
        if signature is None:
            return False
        if signature.fingerprint != record.authority_fingerprint:
            return False
        if signature.code_directory_hash != hashes[bundle_name]:
            return False
    return True


class LauncherIdentityError(RuntimeError):
    """A typed failure reported by one of the signing effects."""

    def __init__(self, cause: LauncherIdentityFailureCause) -> None:
        super().__init__(cause.value)
        self.cause = cause


def _failed(
    cause: LauncherIdentityFailureCause,
    fingerprint: str | None = None,
    created: bool = False,
) -> LauncherIdentityResult:
    remedies = {
        LauncherIdentityFailureCause.STORE_UNOPENABLE: _REMEDY_STORE,
        LauncherIdentityFailureCause.STORE_REGISTRATION_FAILED: _REMEDY_STORE_REGISTRATION,
        LauncherIdentityFailureCause.SECRET_UNAVAILABLE: _REMEDY_SECRET,
        LauncherIdentityFailureCause.KEY_NOT_AUTHORIZED: _REMEDY_AUTHORIZATION,
        LauncherIdentityFailureCause.EXPIRED: _REMEDY_EXPIRED,
        LauncherIdentityFailureCause.NO_KEY: _REMEDY_KEY,
        LauncherIdentityFailureCause.TIMEOUT: _REMEDY_TIMEOUT,
        LauncherIdentityFailureCause.COMPILE_FAILED: _REMEDY_BUILD,
        LauncherIdentityFailureCause.SIGN_FAILED: _REMEDY_SIGN,
        LauncherIdentityFailureCause.PUBLISH_FAILED: _REMEDY_PUBLISH,
        LauncherIdentityFailureCause.VERIFICATION_FAILED: _REMEDY_VERIFY,
        LauncherIdentityFailureCause.AUTHORITY_FAILED: _REMEDY_GENERAL,
        LauncherIdentityFailureCause.RECORD_INVALID: _INVALID_RECORD,
    }
    return LauncherIdentityResult(None, fingerprint, created, cause, remedies[cause], ())


_EMPTY = ""
