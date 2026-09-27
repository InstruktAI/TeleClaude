# shellcheck shell=bash
# shellcheck disable=SC2034  # TC_DECL_* are this library's published output contract.
# Runtime-backed declaration reader for the git wrapper and installed hooks.
# The runtime owns answers, dependencies and generation stamps. Hits are safe
# within a whole second and fork-free; misses run the checkout's Python entry
# point. `teleclaude/config/declaration_views.py` owns the entry format.
# This file stays bash 3.2 compatible for macOS's system shell.
#
# Usage: teleclaude_read_declaration <path-to-teleclaude.yml>
# Sets TC_DECL_KIND, TC_DECL_CODE, TC_DECL_DOCS, TC_DECL_AGENTS and TC_DECL_ERROR.

teleclaude_read_declaration() {
    local _tc_path="$1"
    local _tc_root="${_tc_path%/*}"
    local _tc_home="${TELECLAUDE_HOME:-$HOME/.teleclaude}"
    local _tc_encoded="${_tc_root//%/%25}"
    _tc_encoded="${_tc_encoded//\//%2F}"
    local _tc_entry="$_tc_home/state/declaration-views/$_tc_encoded"
    TC_DECL_KIND=""
    TC_DECL_CODE=""
    TC_DECL_DOCS=""
    TC_DECL_AGENTS=""
    TC_DECL_ERROR=""

    local _tc_hit=1 _tc_generation="" _tc_answer="" _tc_flags="" _tc_line=""
    local _tc_dependency _tc_stamp _tc_index=0
    if [ -f "$_tc_entry" ]; then
        {
            IFS= read -r _tc_generation || _tc_hit=0
            IFS= read -r _tc_answer || _tc_hit=0
            IFS= read -r _tc_flags || _tc_hit=0
            while IFS= read -r _tc_line || [ -n "$_tc_line" ]; do
                case "$_tc_line" in
                    +*)
                        _tc_dependency="${_tc_line:1}"
                        _tc_stamp="$_tc_entry.$_tc_generation.$_tc_index"
                        [ -f "$_tc_dependency" ] || _tc_hit=0
                        [ -f "$_tc_stamp" ] || _tc_hit=0
                        [[ ! "$_tc_dependency" -nt "$_tc_stamp" ]] || _tc_hit=0
                        ;;
                    -*)
                        _tc_dependency="${_tc_line:1}"
                        [ ! -e "$_tc_dependency" ] || _tc_hit=0
                        ;;
                    *)
                        _tc_hit=0
                        ;;
                esac
                _tc_index=$((_tc_index + 1))
            done
        } < "$_tc_entry"
    else
        _tc_hit=0
    fi

    if [ "$_tc_hit" -eq 1 ]; then
        case "$_tc_answer" in
            '!'*)
                TC_DECL_ERROR="$_tc_path: ${_tc_answer#!}"
                return 1
                ;;
            -) TC_DECL_KIND="" ;;
            *) TC_DECL_KIND="$_tc_answer" ;;
        esac
        IFS=' ' read -r TC_DECL_CODE TC_DECL_DOCS TC_DECL_AGENTS <<< "$_tc_flags"
        return 0
    fi

    local _tc_source="${BASH_SOURCE[0]}"
    while [ -L "$_tc_source" ]; do
        local _tc_dir _tc_target
        _tc_dir="$(cd "$(dirname "$_tc_source")" && pwd)"
        _tc_target="$(readlink "$_tc_source")"
        if [[ "$_tc_target" == /* ]]; then
            _tc_source="$_tc_target"
        else
            _tc_source="$_tc_dir/$_tc_target"
        fi
    done
    local _tc_install _tc_error_file
    _tc_install="$(cd "$(dirname "$_tc_source")/../../.." && pwd)"
    _tc_error_file="$(mktemp "${TMPDIR:-/tmp}/teleclaude-declaration-error.XXXXXX")"
    local _tc_output _tc_last_error=""
    if _tc_output=$(cd "$_tc_install" && "$_tc_install/.venv/bin/python" -m teleclaude.entrypoints.declaration_view resolve "$_tc_root" "$_tc_entry" 2>"$_tc_error_file"); then
        rm -f "$_tc_error_file"
        {
            IFS= read -r _tc_generation
            IFS= read -r _tc_answer
            IFS= read -r _tc_flags
        } <<< "$_tc_output"
        case "$_tc_answer" in
            '!'*)
                TC_DECL_ERROR="$_tc_path: ${_tc_answer#!}"
                return 1
                ;;
            -) TC_DECL_KIND="" ;;
            *) TC_DECL_KIND="$_tc_answer" ;;
        esac
        IFS=' ' read -r TC_DECL_CODE TC_DECL_DOCS TC_DECL_AGENTS <<< "$_tc_flags"
        return 0
    fi
    while IFS= read -r _tc_line || [ -n "$_tc_line" ]; do
        _tc_last_error="$_tc_line"
    done < "$_tc_error_file"
    rm -f "$_tc_error_file"
    TC_DECL_ERROR="$_tc_root: the TeleClaude runtime could not resolve the declaration: $_tc_last_error"
    return 1
}
