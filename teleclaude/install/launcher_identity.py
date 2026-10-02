"""Compose and present machine-local launcher identity reconciliation."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from teleclaude.core.reconciliation.launcher_identity import (
    LauncherAuthorityReadiness,
    LauncherBuildDisposition,
    LauncherBuildRecord,
    LauncherBundleSignature,
    LauncherIdentityError,
    LauncherIdentityFailureCause,
    LauncherIdentityIntent,
    LauncherIdentityResult,
    converge_launcher_identity,
)
from teleclaude.paths import LAUNCHER_SIGNING_RECORD_PATH
from teleclaude.project_setup import launcher_signing as effects
from teleclaude.project_setup.macos_setup import install_verified_launchers, is_macos

_ARGUMENT_INTENT = "--intent"
_ARGUMENT_PROJECT_ROOT = "--project-root"
_DEFAULT_PROJECT_ROOT = Path.cwd()
_STAGING_PREFIX = ".launcher-signing-"
_JSON_ENCODING = "utf-8"
_JSON_SEPARATOR = (",", ":")
_JSON_FIELD_INPUT_DIGEST = "input_digest"
_JSON_FIELD_AUTHORITY = "authority_fingerprint"
_JSON_FIELD_BUNDLE_HASHES = "bundle_hashes"
_RESULT_CREATED_TEMPLATE = "Created signing authority {fingerprint}."
_RESULT_REUSED_TEMPLATE = "Reused signing authority {fingerprint}."
_RESULT_REBUILT_TEMPLATE = "Rebuilt and installed launchers with authority {fingerprint}."
_RESULT_NOOP_TEMPLATE = "Launcher inputs and installed identities are current; signed with authority {fingerprint}."
_RESULT_BUILD_TEMPLATE = "Built and signed launcher bundles with authority {fingerprint}."
_RESULT_FAILURE_TEMPLATE = "Launcher signing failed ({cause}): {remedy}"
_REGRANT_NOTICE = "Full Disk Access grants for these launchers must be granted again:"
_REGRANT_GUIDANCE = (
    "Remove each stale launcher entry in System Settings > Privacy & Security > Full Disk Access, "
    "then add the launcher again."
)
_SUCCESS_EXIT = 0
_FAILURE_EXIT = 1
_NON_MACOS_EXIT = 0
_WRITE_MODE = "w"
_READ_MODE = "r"
_CREATE_TEMPORARY = "w"
_TEMPORARY_SUFFIX = ".tmp"
_ARGUMENT_DESCRIPTION = "Converge or build the machine's launcher signing identity."
_NON_MACOS_MESSAGE = "No macOS launchers are installed on this platform."


class _LauncherEffects:
    """Bridge reconciliation decisions to local storage, Keychain and codesign effects."""

    def __init__(
        self,
        project_root: Path,
        *,
        record_path: Path | None = None,
        signing_directory: Path | None = None,
        applications_directory: Path | None = None,
        staging_directory: Path | None = None,
        build_output_directory: Path | None = None,
    ) -> None:
        self.project_root = project_root
        self.record_path = record_path or LAUNCHER_SIGNING_RECORD_PATH
        self.signing_directory = signing_directory
        self.applications_directory = applications_directory
        self.staging_directory = staging_directory
        self.build_output_directory = build_output_directory or project_root / _BIN_DIRECTORY
        self._staging_context: tempfile.TemporaryDirectory[str] | None = None
        if self.staging_directory is not None:
            self.staging_directory.mkdir(parents=True, exist_ok=True)

    def signing_store_exists(self) -> bool:
        return effects.signing_keychain_exists(keychain=effects.launcher_keychain_path(self.signing_directory))

    def current_input_digest(self) -> str:
        try:
            return effects.launcher_input_digest(self.project_root)
        except effects.SigningCommandError as error:
            cause = (
                LauncherIdentityFailureCause.TIMEOUT
                if error.kind is effects.SigningCommandKind.TIMEOUT
                else LauncherIdentityFailureCause.COMPILE_FAILED
            )
            raise _identity_error(error, cause) from error
        except OSError as error:
            raise LauncherIdentityError(LauncherIdentityFailureCause.COMPILE_FAILED) from error

    def read_build_record(self) -> LauncherBuildRecord | None:
        if not self.record_path.is_file():
            return None
        try:
            with self.record_path.open(_READ_MODE, encoding=_JSON_ENCODING) as handle:
                payload: Any = json.load(handle)
            input_digest = payload[_JSON_FIELD_INPUT_DIGEST]
            fingerprint = payload[_JSON_FIELD_AUTHORITY]
            hashes = payload[_JSON_FIELD_BUNDLE_HASHES]
            if not isinstance(input_digest, str) or not isinstance(fingerprint, str) or not isinstance(hashes, dict):
                raise ValueError
            if not all(isinstance(name, str) and isinstance(value, str) for name, value in hashes.items()):
                raise ValueError
            return LauncherBuildRecord(input_digest, fingerprint, tuple(sorted(hashes.items())))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise LauncherIdentityError(LauncherIdentityFailureCause.RECORD_INVALID) from error

    def write_build_record(self, record: LauncherBuildRecord) -> None:
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        record_payload = {
            _JSON_FIELD_INPUT_DIGEST: record.input_digest,
            _JSON_FIELD_AUTHORITY: record.authority_fingerprint,
            _JSON_FIELD_BUNDLE_HASHES: dict(record.bundle_hashes),
        }
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode=_WRITE_MODE,
                encoding=_JSON_ENCODING,
                delete=False,
                dir=self.record_path.parent,
                suffix=_TEMPORARY_SUFFIX,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(record_payload, handle, separators=_JSON_SEPARATOR, sort_keys=True)
                handle.write(_JSON_NEWLINE)
            temporary_path.chmod(_RECORD_MODE)
            temporary_path.replace(self.record_path)
        except OSError as error:
            raise LauncherIdentityError(LauncherIdentityFailureCause.RECORD_INVALID) from error
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def delete_build_record(self) -> None:
        self.record_path.unlink(missing_ok=True)

    def required_bundle_names(self) -> tuple[str, ...]:
        return effects.launcher_bundle_names()

    def installed_bundle_signature(self, bundle_name: str) -> LauncherBundleSignature | None:
        applications_directory = self.applications_directory or _APPLICATIONS_DIRECTORY
        bundle = applications_directory / bundle_name
        if not bundle.is_dir():
            return None
        try:
            signature = effects.verify_bundle(bundle)
        except effects.SigningCommandError as error:
            cause = (
                LauncherIdentityFailureCause.TIMEOUT
                if error.kind is effects.SigningCommandKind.TIMEOUT
                else LauncherIdentityFailureCause.VERIFICATION_FAILED
            )
            raise _identity_error(error, cause) from error
        return LauncherBundleSignature(
            bundle_name,
            bundle,
            signature.fingerprint,
            signature.identifier,
            signature.code_directory_hash,
        )

    def ensure_signing_store(self) -> str:
        try:
            return effects.ensure_signing_store(directory=self.signing_directory)
        except effects.SigningCommandError as error:
            if error.kind is effects.SigningCommandKind.TIMEOUT:
                cause = LauncherIdentityFailureCause.TIMEOUT
            elif effects.signing_keychain_exists(keychain=effects.launcher_keychain_path(self.signing_directory)):
                cause = LauncherIdentityFailureCause.SECRET_UNAVAILABLE
            else:
                cause = LauncherIdentityFailureCause.STORE_UNOPENABLE
            raise _identity_error(error, cause) from error

    def register_signing_store(self) -> None:
        try:
            effects.register_signing_store(keychain=effects.launcher_keychain_path(self.signing_directory))
        except effects.SigningCommandError as error:
            cause = (
                LauncherIdentityFailureCause.TIMEOUT
                if error.kind is effects.SigningCommandKind.TIMEOUT
                else LauncherIdentityFailureCause.STORE_REGISTRATION_FAILED
            )
            raise _identity_error(error, cause) from error

    def authority_readiness(self, secret: str) -> LauncherAuthorityReadiness:
        try:
            fingerprint, unexpired, has_private_key, authorized = effects.authority_ready(
                secret,
                keychain=effects.launcher_keychain_path(self.signing_directory),
            )
        except effects.SigningCommandError as error:
            cause = (
                LauncherIdentityFailureCause.TIMEOUT
                if error.kind is effects.SigningCommandKind.TIMEOUT
                else LauncherIdentityFailureCause.AUTHORITY_FAILED
            )
            raise _identity_error(error, cause) from error
        return LauncherAuthorityReadiness(fingerprint, not unexpired, has_private_key, authorized)

    def create_authority(self, secret: str) -> str:
        try:
            return effects.create_signing_authority(
                secret,
                keychain=effects.launcher_keychain_path(self.signing_directory),
                temporary_root=self.staging_directory,
            )
        except effects.SigningCommandError as error:
            cause = (
                LauncherIdentityFailureCause.TIMEOUT
                if error.kind is effects.SigningCommandKind.TIMEOUT
                else LauncherIdentityFailureCause.AUTHORITY_FAILED
            )
            raise _identity_error(error, cause) from error

    def renew_authority(self, secret: str, fingerprint: str) -> str:
        try:
            keychain = effects.launcher_keychain_path(self.signing_directory)
            effects.delete_signing_authority(fingerprint, secret, keychain=keychain)
            return effects.create_signing_authority(secret, keychain=keychain, temporary_root=self.staging_directory)
        except effects.SigningCommandError as error:
            cause = (
                LauncherIdentityFailureCause.TIMEOUT
                if error.kind is effects.SigningCommandKind.TIMEOUT
                else LauncherIdentityFailureCause.AUTHORITY_FAILED
            )
            raise _identity_error(error, cause) from error

    def current_authority_fingerprint(self) -> str | None:
        try:
            return effects.authority_fingerprint(effects.launcher_keychain_path(self.signing_directory))
        except effects.SigningCommandError as error:
            cause = (
                LauncherIdentityFailureCause.TIMEOUT
                if error.kind is effects.SigningCommandKind.TIMEOUT
                else LauncherIdentityFailureCause.AUTHORITY_FAILED
            )
            raise _identity_error(error, cause) from error

    def build_verified_set(self, fingerprint: str) -> tuple[LauncherBundleSignature, ...]:
        binary_directory = self.staging_directory or self.build_output_directory
        binary_directory.mkdir(parents=True, exist_ok=True)
        self._staging_context = tempfile.TemporaryDirectory(prefix=_STAGING_PREFIX, dir=binary_directory)
        staging = Path(self._staging_context.name)
        try:
            applications = effects.compile_launcher_set(self.project_root, staging)
            verified: list[LauncherBundleSignature] = []
            for bundle in applications:
                try:
                    effects.sign_bundle(
                        bundle,
                        fingerprint,
                        keychain=effects.launcher_keychain_path(self.signing_directory),
                    )
                except effects.SigningCommandError as error:
                    cause = (
                        LauncherIdentityFailureCause.TIMEOUT
                        if error.kind is effects.SigningCommandKind.TIMEOUT
                        else LauncherIdentityFailureCause.SIGN_FAILED
                    )
                    raise _identity_error(error, cause) from error
                try:
                    signature = effects.verify_bundle(bundle, fingerprint)
                except effects.SigningCommandError as error:
                    cause = (
                        LauncherIdentityFailureCause.TIMEOUT
                        if error.kind is effects.SigningCommandKind.TIMEOUT
                        else LauncherIdentityFailureCause.VERIFICATION_FAILED
                    )
                    raise _identity_error(error, cause) from error
                verified.append(
                    LauncherBundleSignature(
                        bundle.name,
                        bundle,
                        signature.fingerprint,
                        signature.identifier,
                        signature.code_directory_hash,
                    )
                )
            if tuple(bundle.bundle_name for bundle in verified) != self.required_bundle_names():
                raise LauncherIdentityError(LauncherIdentityFailureCause.COMPILE_FAILED)
            return tuple(verified)
        except effects.SigningCommandError as error:
            cause = (
                LauncherIdentityFailureCause.TIMEOUT
                if error.kind is effects.SigningCommandKind.TIMEOUT
                else LauncherIdentityFailureCause.VERIFICATION_FAILED
            )
            if error.args and error.args[0] == _EFFECT_COMPILE_FAILURE:
                cause = LauncherIdentityFailureCause.COMPILE_FAILED
            raise _identity_error(error, cause) from error
        except OSError as error:
            self.cleanup_staging()
            raise LauncherIdentityError(LauncherIdentityFailureCause.COMPILE_FAILED) from error
        except LauncherIdentityError:
            self.cleanup_staging()
            raise

    def installed_bundle_signatures(self) -> tuple[LauncherBundleSignature, ...]:
        signatures: list[LauncherBundleSignature] = []
        for name in self.required_bundle_names():
            signature = self.installed_bundle_signature(name)
            if signature is not None:
                signatures.append(signature)
        return tuple(signatures)

    def install_verified_set(self, bundles: tuple[LauncherBundleSignature, ...]) -> None:
        try:
            install_verified_launchers(bundles, applications_directory=self.applications_directory)
        except OSError as error:
            raise LauncherIdentityError(LauncherIdentityFailureCause.PUBLISH_FAILED) from error

    def publish_build_set(self, bundles: tuple[LauncherBundleSignature, ...]) -> None:
        try:
            for bundle in bundles:
                target = self.build_output_directory / bundle.bundle_name
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(bundle.path, target, symlinks=True)
        except OSError as error:
            raise LauncherIdentityError(LauncherIdentityFailureCause.PUBLISH_FAILED) from error

    def cleanup_staging(self) -> None:
        if self._staging_context is not None:
            self._staging_context.cleanup()
            self._staging_context = None


def run_launcher_identity(intent: LauncherIdentityIntent, project_root: Path | None = None) -> LauncherIdentityResult:
    """Run launcher signing convergence with project-local build inputs."""
    if not is_macos():
        return LauncherIdentityResult(LauncherBuildDisposition.NOTHING_TO_DO, None, False, None, _EMPTY, ())
    root = (project_root or _DEFAULT_PROJECT_ROOT).resolve()
    return converge_launcher_identity(intent, _LauncherEffects(root))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=_ARGUMENT_DESCRIPTION)
    parser.add_argument(
        _ARGUMENT_INTENT, choices=tuple(intent.value for intent in LauncherIdentityIntent), required=True
    )
    parser.add_argument(_ARGUMENT_PROJECT_ROOT, type=Path, default=_DEFAULT_PROJECT_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run and present one launcher identity operation."""
    if not is_macos():
        print(_NON_MACOS_MESSAGE)
        return _NON_MACOS_EXIT
    parser = _build_parser()
    args = parser.parse_args(argv)
    intent = LauncherIdentityIntent(args.intent)
    result = run_and_present_launcher_identity(intent, args.project_root)
    return _FAILURE_EXIT if result.failure_cause is not None else _SUCCESS_EXIT


def run_and_present_launcher_identity(
    intent: LauncherIdentityIntent,
    project_root: Path | None = None,
) -> LauncherIdentityResult:
    """Run one launcher identity operation and print its operator-facing result."""
    result = run_launcher_identity(intent, project_root)
    _present_result(intent, result)
    return result


def _present_result(intent: LauncherIdentityIntent, result: LauncherIdentityResult) -> None:
    if result.failure_cause is not None:
        print(_RESULT_FAILURE_TEMPLATE.format(cause=result.failure_cause.value, remedy=result.remedy))
        return
    fingerprint = result.authority_fingerprint or _EMPTY
    if result.disposition is LauncherBuildDisposition.NOTHING_TO_DO:
        print(_RESULT_NOOP_TEMPLATE.format(fingerprint=fingerprint))
        return
    if result.authority_created:
        print(_RESULT_CREATED_TEMPLATE.format(fingerprint=fingerprint))
    else:
        print(_RESULT_REUSED_TEMPLATE.format(fingerprint=fingerprint))
    if intent is LauncherIdentityIntent.BUILD:
        print(_RESULT_BUILD_TEMPLATE.format(fingerprint=fingerprint))
    else:
        print(_RESULT_REBUILT_TEMPLATE.format(fingerprint=fingerprint))
    if result.regrant_bundle_names:
        print(_REGRANT_NOTICE)
        for bundle_name in result.regrant_bundle_names:
            print(bundle_name)
        print(_REGRANT_GUIDANCE)


def _identity_error(error: effects.SigningCommandError, cause: LauncherIdentityFailureCause) -> LauncherIdentityError:
    return LauncherIdentityError(cause)


_APPLICATIONS_DIRECTORY = Path.home() / "Applications"
_BIN_DIRECTORY = "bin"
_EMPTY = ""
_JSON_NEWLINE = "\n"
_RECORD_MODE = 0o600
_EFFECT_COMPILE_FAILURE = "launcher compilation failed"


if __name__ == "__main__":
    raise SystemExit(main())
