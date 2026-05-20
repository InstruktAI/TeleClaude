//! `LogfmtFormatter` — `tracing-subscriber` event formatter producing the
//! `instrukt_ai_logging` logfmt schema.
//!
//! Output per event:
//!
//! ```text
//! {ts} level={LEVEL} logger={target} msg="..." key1=value1 key2=value2
//! ```
//!
//! Field ordering, quoting rules, and the millisecond-precision UTC timestamp
//! match the Python `LogfmtFormatter` in `instrukt_ai_logging/logging.py`.

use std::collections::BTreeMap;
use std::fmt;
use std::sync::OnceLock;

use chrono::{SecondsFormat, Utc};
use regex::Regex;
use tracing::field::{Field, Visit};
use tracing::{Event, Subscriber};
use tracing_subscriber::fmt::format::Writer;
use tracing_subscriber::fmt::{FmtContext, FormatEvent, FormatFields};
use tracing_subscriber::registry::LookupSpan;

/// The reserved field tracing uses for the event's primary message.
const MESSAGE_FIELD: &str = "message";

/// Per-value character cap default. Acts as a **safety net for runaway
/// values** (accidentally-logged HTTP bodies, base64 blobs, huge serialized
/// structures) — not a quality gate. Discipline ("DEBUG one-liners, TRACE
/// can be larger") is the developer's responsibility; the cap exists so an
/// accident doesn't blow out disk/aggregators/grep.
///
/// 10000 chars matches Splunk's per-event default: generous enough that
/// TRACE-level stack traces and small payload dumps survive, tight enough
/// to catch genuinely runaway 100K+ blobs. Override per deployment via the
/// `INSTRUKT_AI_LOG_MAX_VALUE_CHARS` env var (e.g. bump to 50000 for a
/// TRACE-heavy debugging session, drop to 2000 on a constrained host).
///
/// Per-value, not per-line: a giant runaway value gets truncated
/// independently, leaving its sibling fields intact. The truncation marker
/// (`…(truncated)`) matches the Python `LogfmtFormatter` exactly so log
/// aggregators that grep for it work across both languages.
const DEFAULT_MAX_VALUE_CHARS: usize = 10_000;

const MAX_VALUE_CHARS_ENV: &str = "INSTRUKT_AI_LOG_MAX_VALUE_CHARS";

fn max_value_chars() -> usize {
    static CACHED: OnceLock<usize> = OnceLock::new();
    *CACHED.get_or_init(|| {
        std::env::var(MAX_VALUE_CHARS_ENV)
            .ok()
            .and_then(|raw| raw.parse::<usize>().ok())
            .filter(|n| *n > 0)
            .unwrap_or(DEFAULT_MAX_VALUE_CHARS)
    })
}

pub(crate) struct LogfmtFormatter;

impl<S, N> FormatEvent<S, N> for LogfmtFormatter
where
    S: Subscriber + for<'a> LookupSpan<'a>,
    N: for<'a> FormatFields<'a> + 'static,
{
    fn format_event(
        &self,
        _ctx: &FmtContext<'_, S, N>,
        mut writer: Writer<'_>,
        event: &Event<'_>,
    ) -> fmt::Result {
        let metadata = event.metadata();
        let timestamp = format_timestamp_utc_millis(Utc::now());
        let level = level_name(*metadata.level());
        let logger = metadata.target();

        let mut visitor = FieldVisitor::default();
        event.record(&mut visitor);

        let message = visitor.message.unwrap_or_default();

        write!(
            writer,
            "{ts} level={lvl} logger={logger} msg={msg}",
            ts = timestamp,
            lvl = format_bare_structural(level),
            logger = format_bare_structural(logger),
            msg = format_string_quoted(&message),
        )?;

        for (key, value) in visitor.fields {
            // Python's LogfmtFormatter sorts kv keys (BTreeMap gives us that
            // for free), skips the reserved `msg` key, and skips keys that
            // don't match the safe-key pattern.
            if key == "msg" {
                continue;
            }
            if !is_safe_key(&key) {
                continue;
            }
            write!(
                writer,
                " {key}={val}",
                key = key,
                val = format_bare_value(&value)
            )?;
        }

        writeln!(writer)
    }
}

/// Format an instant as `YYYY-MM-DDTHH:MM:SS.mmmZ` (ms precision, UTC).
fn format_timestamp_utc_millis(ts: chrono::DateTime<Utc>) -> String {
    ts.to_rfc3339_opts(SecondsFormat::Millis, true)
}

fn level_name(level: tracing::Level) -> &'static str {
    // Python's `record.levelname` for the warning level is `WARNING`, not
    // `WARN`. Match that string so v1 and v2 lines look identical.
    match level {
        tracing::Level::TRACE => "TRACE",
        tracing::Level::DEBUG => "DEBUG",
        tracing::Level::INFO => "INFO",
        tracing::Level::WARN => "WARNING",
        tracing::Level::ERROR => "ERROR",
    }
}

/// Per-value sanitization pipeline applied before logfmt rendering. Mirrors
/// the Python `LogfmtFormatter` order: **redact secrets first, then truncate**.
/// Doing truncation last means a `…(truncated)` marker can never leak a
/// pre-redaction substring at the boundary.
fn sanitize_value(text: &str) -> String {
    let redacted = redact_secrets(text);
    truncate(&redacted, max_value_chars())
}

/// Replace known secret patterns with `<REDACTED>` markers. Patterns mirror
/// the Python `_REDACTION_PATTERNS`:
///
/// 1. Telegram bot tokens in API URLs: `api.telegram.org/bot<token>/…`
/// 2. Generic `Bearer <token>` headers
/// 3. OpenAI-style `sk-…` keys (10+ alnum chars after the prefix)
///
/// Patterns are compiled once and cached. Adding a pattern is a one-line
/// edit but should pair with a corresponding Python change so both languages
/// redact identically — otherwise log aggregation queries see asymmetric
/// leakage across services.
fn redact_secrets(text: &str) -> String {
    static PATTERNS: OnceLock<Vec<(Regex, &'static str)>> = OnceLock::new();
    let patterns = PATTERNS.get_or_init(|| {
        vec![
            (
                Regex::new(r"(api\.telegram\.org/bot)([^/\s]+)").expect("telegram pattern compiles"),
                "${1}<REDACTED>",
            ),
            (
                Regex::new(r"\bBearer\s+\S+").expect("bearer pattern compiles"),
                "Bearer <REDACTED>",
            ),
            (
                Regex::new(r"\bsk-[A-Za-z0-9]{10,}\b").expect("openai key pattern compiles"),
                "sk-<REDACTED>",
            ),
        ]
    });

    let mut current: std::borrow::Cow<'_, str> = std::borrow::Cow::Borrowed(text);
    for (re, replacement) in patterns {
        let replaced = re.replace_all(&current, *replacement);
        if let std::borrow::Cow::Owned(s) = replaced {
            current = std::borrow::Cow::Owned(s);
        }
    }
    current.into_owned()
}

/// Truncate to `max` characters (not bytes — UTF-8 char-counted to match
/// Python's `len(text)` semantics on strings) and append the `…(truncated)`
/// suffix when the cut happens. A `max` of 0 disables truncation (matches
/// Python's `if max_chars > 0` guard).
fn truncate(text: &str, max: usize) -> String {
    if max == 0 {
        return text.to_string();
    }
    let char_count = text.chars().count();
    if char_count <= max {
        return text.to_string();
    }
    let head: String = text.chars().take(max).collect();
    format!("{head}…(truncated)")
}

/// Match Python's `_SAFE_BARE_VALUE = r"^[A-Za-z0-9._/:+-]+$"` — non-empty,
/// every byte from the safe set.
fn is_safe_bare(text: &str) -> bool {
    !text.is_empty()
        && text.bytes().all(|b| {
            b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'/' | b':' | b'+' | b'-')
        })
}

/// Match Python's `_SAFE_KEY = r"^[A-Za-z_][A-Za-z0-9_.-]*$"`.
fn is_safe_key(key: &str) -> bool {
    let mut bytes = key.bytes();
    let Some(first) = bytes.next() else {
        return false;
    };
    if !(first.is_ascii_alphabetic() || first == b'_') {
        return false;
    }
    bytes.all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b'-'))
}

fn escape_quotes(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for ch in value.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            _ => out.push(ch),
        }
    }
    out
}

/// Render a bare value: leave unquoted when the safe-bare pattern matches,
/// otherwise wrap in double quotes with escaping. Matches Python's
/// `_format_logfmt_value` for string inputs — including redaction and
/// truncation applied before the safe-bare check (a redacted value can
/// re-qualify as safe-bare).
fn format_bare_value(value: &str) -> String {
    let sanitized = sanitize_value(value);
    if is_safe_bare(&sanitized) {
        sanitized
    } else {
        format!("\"{}\"", escape_quotes(&sanitized))
    }
}

/// Render a bare value that's known to be structural (level name, logger
/// target, timestamp). These never need redaction or truncation — they come
/// from the tracing infrastructure, not user data. Skipping sanitize avoids
/// a regex-per-event cost on hot fields and prevents `<REDACTED>` from ever
/// appearing in a level or logger name (a pattern false-positive on a logger
/// like `auth.bearer_token_check` would otherwise mangle it).
fn format_bare_structural(value: &str) -> String {
    if is_safe_bare(value) {
        value.to_string()
    } else {
        format!("\"{}\"", escape_quotes(value))
    }
}

/// Always-quoted string, matching Python's `force_quote=True` used for `msg`.
/// Redaction and truncation apply — `msg` is caller-controlled text.
fn format_string_quoted(value: &str) -> String {
    let sanitized = sanitize_value(value);
    format!("\"{}\"", escape_quotes(&sanitized))
}

#[derive(Default)]
struct FieldVisitor {
    message: Option<String>,
    fields: BTreeMap<String, String>,
}

impl FieldVisitor {
    fn record_kv(&mut self, field: &Field, value: String) {
        let name = field.name();
        if name == MESSAGE_FIELD {
            self.message = Some(value);
        } else {
            self.fields.insert(name.to_string(), value);
        }
    }
}

impl Visit for FieldVisitor {
    fn record_str(&mut self, field: &Field, value: &str) {
        self.record_kv(field, value.to_string());
    }

    fn record_bool(&mut self, field: &Field, value: bool) {
        self.record_kv(field, if value { "true" } else { "false" }.to_string());
    }

    fn record_i64(&mut self, field: &Field, value: i64) {
        self.record_kv(field, value.to_string());
    }

    fn record_u64(&mut self, field: &Field, value: u64) {
        self.record_kv(field, value.to_string());
    }

    fn record_f64(&mut self, field: &Field, value: f64) {
        self.record_kv(field, value.to_string());
    }

    fn record_error(&mut self, field: &Field, value: &(dyn std::error::Error + 'static)) {
        self.record_kv(field, value.to_string());
    }

    fn record_debug(&mut self, field: &Field, value: &dyn fmt::Debug) {
        self.record_kv(field, format!("{value:?}"));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn timestamp_renders_millisecond_precision_with_zulu_suffix() {
        let ts = Utc.with_ymd_and_hms(2026, 5, 16, 12, 34, 56).unwrap()
            + chrono::Duration::milliseconds(789);
        assert_eq!(format_timestamp_utc_millis(ts), "2026-05-16T12:34:56.789Z");
    }

    #[test]
    fn warn_level_renders_as_warning_to_match_python() {
        assert_eq!(level_name(tracing::Level::WARN), "WARNING");
    }

    #[test]
    fn safe_bare_value_pattern_matches_python_regex() {
        assert!(is_safe_bare("INFO"));
        assert!(is_safe_bare("teleclaude.workflow"));
        assert!(is_safe_bare("/var/log/foo"));
        assert!(is_safe_bare("v1.2.3-rc1"));
        assert!(!is_safe_bare(""));
        assert!(!is_safe_bare("has space"));
        assert!(!is_safe_bare("has=equals"));
        assert!(!is_safe_bare("has\"quote"));
    }

    #[test]
    fn safe_key_pattern_rejects_keys_starting_with_digit_or_dash() {
        assert!(is_safe_key("slug"));
        assert!(is_safe_key("_private"));
        assert!(is_safe_key("a.b-c_d"));
        assert!(!is_safe_key(""));
        assert!(!is_safe_key("1leading"));
        assert!(!is_safe_key("-leading"));
        assert!(!is_safe_key(".leading"));
    }

    #[test]
    fn unsafe_value_gets_quoted_with_escapes() {
        assert_eq!(format_bare_value("hello"), "hello");
        assert_eq!(format_bare_value("hello world"), "\"hello world\"");
        assert_eq!(format_bare_value("a\"b"), "\"a\\\"b\"");
        assert_eq!(format_bare_value("a\nb"), "\"a\\nb\"");
    }

    #[test]
    fn force_quoted_string_always_wraps_even_safe_input() {
        assert_eq!(format_string_quoted("hello"), "\"hello\"");
        assert_eq!(format_string_quoted(""), "\"\"");
    }

    #[test]
    fn telegram_bot_token_is_redacted_in_api_url() {
        let input = "fetched https://api.telegram.org/bot1234:secret/sendMessage ok";
        let out = redact_secrets(input);
        assert!(out.contains("api.telegram.org/bot<REDACTED>"));
        assert!(!out.contains("1234:secret"));
    }

    #[test]
    fn bearer_token_is_redacted_with_marker_preserved() {
        let input = "Authorization: Bearer eyJhbGc.fake.token";
        let out = redact_secrets(input);
        assert!(out.contains("Bearer <REDACTED>"));
        assert!(!out.contains("eyJhbGc.fake.token"));
    }

    #[test]
    fn openai_sk_key_is_redacted_while_unrelated_sk_prefix_is_left_alone() {
        // Long enough alnum tail to trip the pattern (10+ chars).
        assert_eq!(
            redact_secrets("key=sk-abcdefghij1234567890"),
            "key=sk-<REDACTED>",
        );
        // Too short to match — left alone.
        assert_eq!(redact_secrets("status=sk-short"), "status=sk-short");
    }

    #[test]
    fn truncate_returns_input_unchanged_when_below_cap() {
        assert_eq!(truncate("hello", 100), "hello");
    }

    #[test]
    fn truncate_appends_marker_when_cap_exceeded() {
        // 5 chars in, cap=3 — keep first 3, append the marker.
        assert_eq!(truncate("hello", 3), "hel…(truncated)");
    }

    #[test]
    fn truncate_counts_chars_not_bytes_for_multibyte_input() {
        // 4 logical chars (3 ASCII + 1 multibyte), cap=3 — keep 3, append marker.
        assert_eq!(truncate("abcé", 3), "abc…(truncated)");
    }

    #[test]
    fn truncate_disabled_when_cap_is_zero() {
        assert_eq!(truncate("any length text", 0), "any length text");
    }

    #[test]
    fn sanitize_redacts_then_truncates_so_marker_cannot_leak_pre_redaction_substring() {
        // If we truncated FIRST, a cut mid-token could leave half a secret
        // visible before the marker. Redacting first guarantees the cut sees
        // only sanitized text.
        let secret = format!("prefix Bearer realsecret123 {}", "x".repeat(20_000));
        let sanitized = sanitize_value(&secret);
        assert!(sanitized.contains("Bearer <REDACTED>"));
        assert!(!sanitized.contains("realsecret123"));
        assert!(sanitized.ends_with("…(truncated)"));
    }
}
