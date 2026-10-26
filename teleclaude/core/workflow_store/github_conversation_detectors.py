"""The detection libraries behind the conversation's protection step, with the engines they run on.

Importing detect-secrets, Presidio and spaCy costs seconds, and the daemon needs them only when a turn is first
protected, so this module is loaded on that first use and not when the daemon starts
(`teleclaude.core.workflow_store.github_conversation_protection`).

detect-secrets keeps its settings in process-global state and Presidio builds its engines once; one lock
serialises both so concurrent protection never sees another call's configuration.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Final

from detect_secrets.core.potential_secret import PotentialSecret
from detect_secrets.core.scan import scan_line
from detect_secrets.plugins.high_entropy_strings import Base64HighEntropyString
from detect_secrets.settings import get_settings, transient_settings
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import EmailRecognizer
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import RecognizerResult as AnonymizerFinding
from tldextract import TLDExtract

from teleclaude.config.secret_masking import mask_secret_values

_CREDENTIAL_LABEL: Final = "[credential]"
_VERIFICATION_FILTER: Final = "detect_secrets.filters.common.is_ignored_due_to_verification_policies"
_ENTITIES: Final = (
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "LOCATION",
    "NRP",
    "CREDIT_CARD",
    "IBAN_CODE",
    "CRYPTO",
    "IP_ADDRESS",
    "MAC_ADDRESS",
    "MEDICAL_LICENSE",
)
_LANGUAGE: Final = "en"
_MODEL_NAME: Final = "en_core_web_sm"
_NLP_ENGINE_NAME: Final = "spacy"
_NLP_CONFIGURATION: Final = {
    "nlp_engine_name": _NLP_ENGINE_NAME,
    "models": [{"lang_code": _LANGUAGE, "model_name": _MODEL_NAME}],
}
_CHUNK_CHARACTERS: Final = 50_000

# Every detect-secrets plugin that recognises a credential by its shape or its name, except the hexadecimal
# high-entropy plugin and the public-address plugin (Presidio owns addresses). The base64 high-entropy plugin keeps
# its default limit.
_DETECT_SECRETS_PLUGINS: Final = (
    "ArtifactoryDetector",
    "AWSKeyDetector",
    "AzureStorageKeyDetector",
    "Base64HighEntropyString",
    "BasicAuthDetector",
    "CloudantDetector",
    "DiscordBotTokenDetector",
    "GitHubTokenDetector",
    "GitLabTokenDetector",
    "IbmCloudIamDetector",
    "IbmCosHmacDetector",
    "JwtTokenDetector",
    "KeywordDetector",
    "MailchimpDetector",
    "NpmDetector",
    "OpenAIDetector",
    "PrivateKeyDetector",
    "PypiTokenDetector",
    "SendGridDetector",
    "SlackDetector",
    "SoftlayerDetector",
    "SquareOAuthDetector",
    "StripeDetector",
    "TelegramBotTokenDetector",
    "TwilioKeyDetector",
)
# Heuristics that spare identifiers, templates and references. The inline allowlist filter is absent on purpose:
# a conversation must not be able to switch detection off for itself with a comment.
_DETECT_SECRETS_FILTERS: Final = (
    "detect_secrets.filters.heuristic.is_sequential_string",
    "detect_secrets.filters.heuristic.is_potential_uuid",
    "detect_secrets.filters.heuristic.is_likely_id_string",
    "detect_secrets.filters.heuristic.is_templated_secret",
    "detect_secrets.filters.heuristic.is_prefixed_with_dollar_sign",
    "detect_secrets.filters.heuristic.is_indirect_reference",
    "detect_secrets.filters.heuristic.is_not_alphanumeric_string",
)
_ENTROPY_LIMIT: Final = 4.5
_ENTROPY_PLUGIN: Final = Base64HighEntropyString(limit=_ENTROPY_LIMIT)
_DETECT_SECRETS_CONFIGURATION: Final = {
    "plugins_used": [{"name": name} for name in _DETECT_SECRETS_PLUGINS],
    "filters_used": [{"path": path} for path in _DETECT_SECRETS_FILTERS],
}


# Presidio validates an email's domain with tldextract, whose default extractor fetches the public suffix list over
# the network and keeps it in a lock-guarded disk cache. Protection must neither wait on the network nor on that
# lock, so email validation uses the suffix list bundled with the library and no disk cache.
_OFFLINE_DOMAIN_EXTRACTOR: Final = TLDExtract(suffix_list_urls=(), cache_dir=None)


class _OfflineEmailRecognizer(EmailRecognizer):
    """Presidio's email recognizer, validating the domain against the bundled suffix list only."""

    def validate_result(self, pattern_text: str) -> bool:
        return _OFFLINE_DOMAIN_EXTRACTOR(pattern_text).fqdn != ""


_engines_lock = threading.Lock()
_analyzer: AnalyzerEngine | None = None
_anonymizer: AnonymizerEngine | None = None


def protect_text(text: str, secrets: frozenset[str]) -> str:
    """Mask the platform's secrets, then replace credentials and personal data; raises when detection cannot run."""
    with _engines_lock:
        analyzer, anonymizer = _engines()
        return _protect_one(text, secrets, analyzer, anonymizer)


def _engines() -> tuple[AnalyzerEngine, AnonymizerEngine]:
    """Build the Presidio engines once; the caller holds the lock."""
    global _analyzer, _anonymizer
    if _analyzer is None or _anonymizer is None:
        nlp_engine = NlpEngineProvider(nlp_configuration=_NLP_CONFIGURATION).create_engine()
        _analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=[_LANGUAGE])
        _analyzer.registry.remove_recognizer(EmailRecognizer.__name__)
        _analyzer.registry.add_recognizer(_OfflineEmailRecognizer(name=EmailRecognizer.__name__))
        _anonymizer = AnonymizerEngine()  # type: ignore[no-untyped-call]  # presidio-anonymizer ships no annotations
    return _analyzer, _anonymizer


def _protect_one(text: str, secrets: frozenset[str], analyzer: AnalyzerEngine, anonymizer: AnonymizerEngine) -> str:
    masked = mask_secret_values(text, secrets)
    without_credentials = _replace_credentials(masked)
    return "".join(_replace_personal_data(chunk, analyzer, anonymizer) for chunk in _chunks(without_credentials))


def _replace_credentials(text: str) -> str:
    """Replace every credential-like string detect-secrets recognises, line by line, with verification off."""
    with transient_settings(_DETECT_SECRETS_CONFIGURATION):
        if _VERIFICATION_FILTER in get_settings().filters:
            raise RuntimeError(_VERIFICATION_FILTER)
        return "".join(_replace_credentials_in_line(line) for line in text.splitlines(keepends=True))


def _is_credential(secret: PotentialSecret) -> bool:
    """Whether a candidate is a credential: ad hoc scanning reports every high-entropy candidate, so apply the limit."""
    value = secret.secret_value
    if not value:
        return False
    if secret.type != _ENTROPY_PLUGIN.secret_type:
        return True
    return _ENTROPY_PLUGIN.calculate_shannon_entropy(value) > _ENTROPY_LIMIT


def _replace_credentials_in_line(line: str) -> str:
    found = {
        secret.secret_value for secret in scan_line(line.rstrip()) if _is_credential(secret) and secret.secret_value
    }
    for value in sorted(found, key=len, reverse=True):
        line = line.replace(value, _CREDENTIAL_LABEL)
    return line


def _replace_personal_data(text: str, analyzer: AnalyzerEngine, anonymizer: AnonymizerEngine) -> str:
    if not text.strip():
        return text
    findings = analyzer.analyze(text=text, language=_LANGUAGE, entities=list(_ENTITIES))
    if not findings:
        return text
    replacements = [AnonymizerFinding(f.entity_type, f.start, f.end, f.score) for f in findings]
    return anonymizer.anonymize(text=text, analyzer_results=replacements).text


def _chunks(text: str) -> Iterator[str]:
    """Cut text into pieces the language model analyses comfortably, preferring line ends."""
    start = 0
    while start < len(text):
        end = min(start + _CHUNK_CHARACTERS, len(text))
        if end < len(text):
            line_end = text.rfind("\n", start, end)
            end = line_end + 1 if line_end > start else end
        yield text[start:end]
        start = end
