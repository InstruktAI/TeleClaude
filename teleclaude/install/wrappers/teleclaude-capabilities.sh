# shellcheck shell=bash
# shellcheck disable=SC2034  # TC_DECL_* are this library's published output contract, read by callers after sourcing.
# TeleClaude capability declaration reader.
#
# Sourced by the git wrapper and the installed git hooks to read a project's
# capability toggles — and the declaration's tier — directly from the
# checkout's own teleclaude.yml, the same file the Python runtime resolves
# (teleclaude/capabilities.py:resolve_capabilities). teleclaude.yml is the
# only home of capability state (project/spec/feature/config/
# project-capability-manifest); there is no projected copy to fall back to.
#
# Usage:
#   teleclaude_read_declaration <path-to-teleclaude.yml>
#
# Sets, in the caller's shell:
#   TC_DECL_KIND    project | global | person | company | "" (unreadable)
#   TC_DECL_CODE    1 | 0 | "" (all three toggles 0 for a non-project kind)
#   TC_DECL_DOCS    1 | 0 | ""
#   TC_DECL_AGENTS  1 | 0 | ""
#   TC_DECL_ERROR   "" on success; one line naming the file and field otherwise
#
# Returns 0 on success, 1 when the declaration cannot be read. Pure bash —
# `while IFS= read -r`, `case`, `[[ =~ ]]` — no `$(...)` fork, no awk/sed, no
# associative arrays (bash 3.2 compatible), to keep the git wrapper's <5ms
# overhead budget: one cheap pass for `kind:` (which breaks on the first
# match — the field is conventionally the file's first line) and, only for a
# `project` declaration, one single pass resolving all three capability
# blocks together.

# Strips leading and trailing whitespace from $1 into $_TC_TRIMMED. A plain
# function call, not a command substitution, so it forks nothing.
_tc_trim() {
    local _s="$1"
    _s="${_s#"${_s%%[![:space:]]*}"}"
    _s="${_s%"${_s##*[![:space:]]}"}"
    _TC_TRIMMED="$_s"
}

# Validates a captured `enabled:` value against PyYAML's (YAML 1.1) implicit
# bool resolver — only these exact spellings. Sets _TC_BOOL_VALUE (1|0) and
# returns 0, or returns 1 for anything else (quoted, numeric, anchor, ...).
_tc_bool() {
    case "$1" in
        true | True | TRUE | yes | Yes | YES | on | On | ON)
            _TC_BOOL_VALUE=1
            return 0
            ;;
        false | False | FALSE | no | No | NO | off | Off | OFF)
            _TC_BOOL_VALUE=0
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

teleclaude_read_declaration() {
    local _tc_path="$1"
    TC_DECL_KIND=""
    TC_DECL_CODE=""
    TC_DECL_DOCS=""
    TC_DECL_AGENTS=""
    TC_DECL_ERROR=""

    if [ ! -f "$_tc_path" ]; then
        TC_DECL_ERROR="$_tc_path: not found"
        return 1
    fi

    local _tc_line _tc_kind=""
    while IFS= read -r _tc_line || [ -n "$_tc_line" ]; do
        _tc_line="${_tc_line%$'\r'}"
        if [[ "$_tc_line" =~ ^kind:[[:space:]]*(.*)$ ]]; then
            _tc_kind="${BASH_REMATCH[1]}"
            _tc_kind="${_tc_kind%%#*}"
            _tc_trim "$_tc_kind"
            _tc_kind="$_TC_TRIMMED"
            break
        fi
    done < "$_tc_path"

    case "$_tc_kind" in
        global | person | company)
            TC_DECL_KIND="$_tc_kind"
            TC_DECL_CODE=0
            TC_DECL_DOCS=0
            TC_DECL_AGENTS=0
            return 0
            ;;
        project)
            TC_DECL_KIND="project"
            ;;
        *)
            TC_DECL_ERROR="$_tc_path: no readable 'kind' declaration"
            return 1
            ;;
    esac

    # One pass resolves all three capability blocks together. Index: 0=code,
    # 1=docs, 2=agents. `_tc_final[i]` stays empty while capability i is still
    # undecided (its key not yet seen, or its block still being scanned) and
    # holds "0"/"1" once resolved; an unresolved capability at EOF defaults
    # to subscribed (the block was absent, or present with no enabled key).
    local _tc_names=(code docs agents)
    local _tc_final=("" "" "")
    local _tc_inblock=(0 0 0)
    local _tc_blockindent=(-1 -1 -1)
    local _tc_i _tc_lead _tc_stripped _tc_indent _tc_rest _tc_name

    while IFS= read -r _tc_line || [ -n "$_tc_line" ]; do
        _tc_line="${_tc_line%$'\r'}"

        if [[ "$_tc_line" =~ ^[[:space:]]*$ ]]; then
            continue
        fi

        for _tc_i in 0 1 2; do
            [ "${_tc_inblock[_tc_i]}" -eq 1 ] || continue
            # A line with no leading whitespace ends the block: it resolves
            # to subscribed (no enabled key was found among its children).
            if [[ ! "$_tc_line" =~ ^[[:space:]] ]]; then
                _tc_final[_tc_i]=1
                _tc_inblock[_tc_i]=0
                continue
            fi
            _tc_lead="${_tc_line%%[![:space:]]*}"
            _tc_indent=${#_tc_lead}
            _tc_stripped="${_tc_line#"$_tc_lead"}"
            # The first indented line after the block key fixes the indent;
            # deeper lines are nested, not the block's own keys.
            if [ "${_tc_blockindent[_tc_i]}" -eq -1 ]; then
                _tc_blockindent[_tc_i]=$_tc_indent
            fi
            [ "$_tc_indent" -ne "${_tc_blockindent[_tc_i]}" ] && continue
            if [[ "$_tc_stripped" =~ ^enabled:[[:space:]]*(.*)$ ]]; then
                _tc_rest="${BASH_REMATCH[1]}"
                _tc_rest="${_tc_rest%%#*}"
                _tc_trim "$_tc_rest"
                if _tc_bool "$_TC_TRIMMED"; then
                    _tc_final[_tc_i]=$_TC_BOOL_VALUE
                    _tc_inblock[_tc_i]=0
                else
                    _tc_name="${_tc_names[_tc_i]}"
                    TC_DECL_KIND=""
                    TC_DECL_ERROR="$_tc_path: capability block '$_tc_name' carries no boolean enabled value"
                    return 1
                fi
            fi
        done

        # A line with leading whitespace is a block's child, never a fresh
        # top-level key — already handled above.
        [[ "$_tc_line" =~ ^[[:space:]] ]] && continue

        for _tc_i in 0 1 2; do
            [ -n "${_tc_final[_tc_i]}" ] && continue
            [ "${_tc_inblock[_tc_i]}" -eq 1 ] && continue
            _tc_name="${_tc_names[_tc_i]}"
            if [[ "$_tc_line" =~ ^${_tc_name}:[[:space:]]*(.*)$ ]]; then
                _tc_rest="${BASH_REMATCH[1]}"
                _tc_rest="${_tc_rest%%#*}"
                _tc_trim "$_tc_rest"
                _tc_rest="$_TC_TRIMMED"

                # Block form: nothing after the key — children follow, indented.
                if [ -z "$_tc_rest" ]; then
                    _tc_inblock[_tc_i]=1
                    _tc_blockindent[_tc_i]=-1
                    break
                fi

                # Inline flow form: `name: { enabled: false, ... }`.
                if [[ "$_tc_rest" == \{* ]]; then
                    if [[ "$_tc_rest" != *\}* ]]; then
                        TC_DECL_KIND=""
                        TC_DECL_ERROR="$_tc_path: capability block '$_tc_name' carries no boolean enabled value"
                        return 1
                    fi
                    _tc_rest="${_tc_rest#*\{}"
                    _tc_rest="${_tc_rest%\}*}"
                    if [[ "$_tc_rest" =~ (^|,)[[:space:]]*enabled:[[:space:]]*([^,]*) ]]; then
                        _tc_trim "${BASH_REMATCH[2]}"
                        if _tc_bool "$_TC_TRIMMED"; then
                            _tc_final[_tc_i]=$_TC_BOOL_VALUE
                        else
                            TC_DECL_KIND=""
                            TC_DECL_ERROR="$_tc_path: capability block '$_tc_name' carries no boolean enabled value"
                            return 1
                        fi
                    else
                        # Inline block present with no enabled key → default subscribed.
                        _tc_final[_tc_i]=1
                    fi
                    break
                fi

                # A scalar sits in place of the block (e.g. `code: false`).
                TC_DECL_KIND=""
                TC_DECL_ERROR="$_tc_path: capability block '$_tc_name' carries no boolean enabled value"
                return 1
            fi
        done
    done < "$_tc_path"

    for _tc_i in 0 1 2; do
        [ -z "${_tc_final[_tc_i]}" ] && _tc_final[_tc_i]=1
    done

    TC_DECL_CODE="${_tc_final[0]}"
    TC_DECL_DOCS="${_tc_final[1]}"
    TC_DECL_AGENTS="${_tc_final[2]}"
    return 0
}
