#!/usr/bin/env bash
#
# Machine-local code-signing authority for the macOS launcher bundles.
#
# macOS binds Full Disk Access grants to the signing certificate itself, not to
# its name, so this authority is durable machine state: creating a replacement
# under the same name voids every grant the previous one earned. Creation is
# therefore automatic only when no authority exists; every path that would
# discard an existing one is gated behind an explicit `replace`.
set -euo pipefail

AUTHORITY="${LAUNCHER_SIGNING_AUTHORITY:-InstruktAI Dev}"
VALIDITY_DAYS=3650
RENEW_WINDOW_DAYS=180
BACKUP_DIR="${TELECLAUDE_HOME:-$HOME/.teleclaude}/signing"

authority_fingerprints() {
    security find-certificate -a -c "$AUTHORITY" -Z 2>/dev/null |
        awk '/^SHA-1 hash: / { print tolower($NF) }'
}

certificate_pem() {
    security find-certificate -c "$AUTHORITY" -p 2>/dev/null
}

has_private_key() {
    local upper
    upper="$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')"
    security find-identity -p codesigning 2>/dev/null | grep -qF "$upper"
}

# `openssl x509 -checkend` exits non-zero when the certificate falls inside the
# window, so both callers below invert it rather than parsing a date.
outlives_window() {
    certificate_pem | openssl x509 -noout -checkend "$(($1 * 86400))" > /dev/null 2>&1
}

default_user_keychain() {
    security default-keychain -d user | tr -d ' "'
}

# Emits `key=value` lines; `status` is the field callers branch on.
inspect_authority() {
    local fingerprints count fingerprint
    fingerprints="$(authority_fingerprints)"
    count="$(printf '%s' "$fingerprints" | grep -c . || true)"

    echo "authority=$AUTHORITY"
    echo "count=$count"

    if [ "$count" -eq 0 ]; then
        echo "status=missing"
        return 0
    fi
    if [ "$count" -gt 1 ]; then
        echo "status=ambiguous"
        printf '%s\n' "$fingerprints" | sed 's/^/fingerprint=/'
        return 0
    fi

    fingerprint="$fingerprints"
    echo "fingerprint=$fingerprint"
    echo "not_after=$(certificate_pem | openssl x509 -noout -enddate | cut -d= -f2)"

    if ! has_private_key "$fingerprint"; then
        echo "status=nokey"
    elif ! outlives_window 0; then
        echo "status=expired"
    elif ! outlives_window "$RENEW_WINDOW_DAYS"; then
        echo "status=expiring"
    else
        echo "status=ok"
    fi
}

status_of() {
    inspect_authority | sed -n 's/^status=//p'
}

fingerprint_of() {
    inspect_authority | sed -n 's/^fingerprint=//p' | head -1
}

create_authority() {
    local keychain workdir passphrase
    keychain="$(default_user_keychain)"
    workdir="$(mktemp -d)"
    # shellcheck disable=SC2064  # expand workdir now; the trap must not depend on later scope
    trap "rm -rf '$workdir'" RETURN
    passphrase="$(openssl rand -base64 24)"

    openssl req -x509 -newkey rsa:2048 -nodes -days "$VALIDITY_DAYS" \
        -keyout "$workdir/key.pem" -out "$workdir/cert.pem" \
        -subj "/CN=$AUTHORITY" \
        -addext "basicConstraints=critical,CA:false" \
        -addext "keyUsage=critical,digitalSignature" \
        -addext "extendedKeyUsage=critical,codeSigning" 2> /dev/null

    # These PBE algorithms are the ones both LibreSSL (the macOS system openssl)
    # and OpenSSL 3 emit and macOS imports; OpenSSL 3's own default needs the
    # legacy provider, which LibreSSL has no flag for.
    openssl pkcs12 -export \
        -certpbe PBE-SHA1-3DES -keypbe PBE-SHA1-3DES -macalg sha1 \
        -inkey "$workdir/key.pem" -in "$workdir/cert.pem" \
        -name "$AUTHORITY" -out "$workdir/authority.p12" \
        -passout "pass:$passphrase"

    security import "$workdir/authority.p12" -k "$keychain" -P "$passphrase" \
        -T /usr/bin/codesign -T /usr/bin/security > /dev/null

    echo "signing authority: created '$AUTHORITY' (valid $VALIDITY_DAYS days)"
    export_backup "$workdir/authority.p12" "$passphrase"

    authorize_codesign "$keychain"
}

# Lets codesign use the new key unattended. `security` asks for the login
# keychain password on the terminal itself, so this needs a TTY and the password
# never passes through this script or its argument vector. Scoped to one key by
# label: widening the partition list of every key in the login keychain would be
# a side effect far beyond this script's business. Skipping only costs a
# one-time macOS dialog later, so it never blocks the build.
# A backup is the only way to reissue this authority on a rebuilt machine or a
# second one; recreating it instead voids every grant it earned. An existing
# export therefore belongs to a certificate whose grants may still be live, so
# it is never overwritten.
export_backup() {
    local source_p12="$1"
    local passphrase="$2"
    local slug target

    slug="$(printf '%s' "$AUTHORITY" | tr ' ' '-')"
    target="$BACKUP_DIR/$slug.p12"

    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
    if [ -e "$target" ]; then
        target="$BACKUP_DIR/$slug.$(date +%Y%m%dT%H%M%S).p12"
        echo "signing authority: a previous export exists; writing beside it"
    fi

    cp "$source_p12" "$target"
    printf '%s\n' "$passphrase" > "$target.passphrase"
    chmod 600 "$target" "$target.passphrase"
    echo "signing authority: backup exported to $target"
    echo "signing authority: its passphrase is in $target.passphrase"
}

authorize_codesign() {
    local keychain="$1"

    if [ ! -t 0 ]; then
        echo "signing authority: no terminal available to authorize the key."
        echo "signing authority: macOS will ask once on the first signature —"
        echo "signing authority: choose 'Always Allow', or rerun 'make launchers'"
        echo "signing authority: from a terminal to be asked for your password instead."
        return 0
    fi

    echo "signing authority: macOS needs your LOGIN password to let codesign use"
    echo "signing authority: the new key without prompting on every rebuild."
    if security set-key-partition-list -S apple-tool:,apple:,codesign: \
        -s -l "$AUTHORITY" "$keychain" > /dev/null; then
        echo "signing authority: codesign authorized to use the key without prompting"
    else
        echo "signing authority: not authorized; macOS will ask on the first"
        echo "signing authority: signature instead — choose 'Always Allow'."
    fi
}

report_replacement_consequence() {
    cat <<EOF
signing authority: replacing '$AUTHORITY' issues a NEW certificate. macOS binds
signing authority: Full Disk Access to the certificate, so every launcher grant
signing authority: is voided and must be re-granted by hand afterwards.
signing authority: run 'make launchers-renew-authority' when you are ready.
EOF
}

ensure_authority() {
    case "$(status_of)" in
        ok)
            echo "signing authority: '$AUTHORITY' present and valid"
            ;;
        expiring)
            echo "signing authority: '$AUTHORITY' expires within $RENEW_WINDOW_DAYS days; signing still works"
            report_replacement_consequence
            ;;
        missing)
            echo "signing authority: '$AUTHORITY' not found; creating it"
            create_authority
            ;;
        expired)
            echo "signing authority: '$AUTHORITY' has expired; codesign cannot sign with it" >&2
            report_replacement_consequence >&2
            return 1
            ;;
        nokey)
            echo "signing authority: '$AUTHORITY' has no private key in the keychain; it cannot sign" >&2
            report_replacement_consequence >&2
            return 1
            ;;
        ambiguous)
            echo "signing authority: more than one certificate is named '$AUTHORITY'; signing is ambiguous." >&2
            echo "signing authority: delete the wrong one by fingerprint with" >&2
            echo "signing authority: 'security delete-identity -Z <sha1>', then rerun." >&2
            inspect_authority | sed -n 's/^fingerprint=/signing authority:   /p' >&2
            return 1
            ;;
    esac
}

replace_authority() {
    local fingerprint
    while IFS= read -r fingerprint; do
        [ -n "$fingerprint" ] || continue
        echo "signing authority: deleting identity $fingerprint"
        # delete-identity removes the certificate together with its private key;
        # delete-certificate would leave the key orphaned in the keychain.
        security delete-identity -Z "$(printf '%s' "$fingerprint" | tr '[:lower:]' '[:upper:]')" > /dev/null
    done < <(authority_fingerprints)
    create_authority
    echo "signing authority: every launcher must now be rebuilt and re-granted Full Disk Access."
}

bundle_leaf_hash() {
    codesign -d -r- "$1" 2>&1 |
        sed -n 's/.*certificate leaf = H"\([0-9a-f]*\)".*/\1/p' |
        head -1
}

# Compares each bundle's designated requirement against the live authority. A
# divergence is the moment Full Disk Access grants stopped matching, which is
# otherwise silent until an agent hits a permission error.
audit_bundles() {
    local fingerprint bundle leaf diverged=0
    fingerprint="$(fingerprint_of)"
    if [ -z "$fingerprint" ]; then
        return 0
    fi

    for bundle in "$@"; do
        [ -d "$bundle" ] || continue
        leaf="$(bundle_leaf_hash "$bundle")"
        if [ "$leaf" != "$fingerprint" ]; then
            if [ "$diverged" -eq 0 ]; then
                echo "launcher identity: these bundles are NOT signed by the current '$AUTHORITY':"
                diverged=1
            fi
            echo "launcher identity:   $bundle"
        fi
    done

    if [ "$diverged" -eq 1 ]; then
        cat <<'EOF'
launcher identity: their Full Disk Access grants no longer match and must be reissued.
launcher identity: open System Settings > Privacy & Security > Full Disk Access,
launcher identity: REMOVE each stale entry with the minus button, then add the
launcher identity: bundle again with plus. A row left in place commonly still
launcher identity: shows enabled while no longer granting access.
EOF
    fi
}

case "${1:-}" in
    inspect) inspect_authority ;;
    ensure) ensure_authority ;;
    replace) replace_authority ;;
    audit-bundles)
        shift
        audit_bundles "$@"
        ;;
    *)
        echo "usage: signing-authority.sh {inspect|ensure|replace|audit-bundles <bundle>...}" >&2
        exit 2
        ;;
esac
