#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SOURCE_FILE="$SCRIPT_DIR/main.swift"
AUTHORITY="InstruktAI Dev"

if ! command -v swiftc >/dev/null 2>&1; then
    echo "make launchers: swiftc is required; install the Xcode Command Line Tools with: xcode-select --install" >&2
    exit 1
fi

n=$(security find-certificate -a -c "$AUTHORITY" 2>/dev/null | grep -c '^keychain:' || true)
if [ "$n" -eq 0 ]; then
    echo "make launchers: signing authority '$AUTHORITY' is missing. Create one self-signed Code Signing certificate named '$AUTHORITY' in Keychain Access (macos-stable-code-signing Step 1), then rerun make launchers." >&2
    exit 1
fi
if [ "$n" -gt 1 ]; then
    echo "make launchers: signing authority '$AUTHORITY' is ambiguous ($n certificates). Resolve it by fingerprint before rerunning." >&2
    exit 1
fi

temporary_directory="$(mktemp -d)"
trap 'rm -rf "$temporary_directory"' EXIT

write_config() {
    local target="$1"
    local config_path="$2"
    local target_executable
    local override_keys
    local fixed_candidates
    local override_strict
    local strict_exit_code
    local argv_policy

    case "$target" in
        tmux)
            target_executable="tmux"
            override_keys='"TMUX_LAUNCHER_TARGET", "TMUX_BINARY"'
            fixed_candidates='"/opt/homebrew/bin/tmux", "/usr/local/bin/tmux", "/usr/bin/tmux"'
            override_strict="false"
            strict_exit_code="127"
            argv_policy=".tmuxServer"
            ;;
        claude)
            target_executable="claude"
            override_keys='"CLAUDE_PATH"'
            fixed_candidates=""
            override_strict="true"
            strict_exit_code="1"
            argv_policy=".passthrough"
            ;;
        codex)
            target_executable="codex"
            override_keys='"CODEX_PATH"'
            fixed_candidates=""
            override_strict="false"
            strict_exit_code="127"
            argv_policy=".passthrough"
            ;;
        gemini)
            target_executable="agy"
            override_keys='"GEMINI_PATH"'
            fixed_candidates=""
            override_strict="false"
            strict_exit_code="127"
            argv_policy=".passthrough"
            ;;
        deepseek)
            target_executable="dsh"
            override_keys='"DSH_PATH"'
            # The daemon pane PATH is a best-effort capture of the user shell
            # with a fallback to the launchd daemon environment (which lacks
            # npm's global bin), so dsh resolution cannot depend on PATH alone.
            # Bake the machine's actual npm global bin at build time, plus the
            # standard prefixes, mirroring the tmux target's fixed candidates.
            if command -v npm >/dev/null 2>&1; then
                dsh_npm_bin="$(npm prefix -g 2>/dev/null)/bin/dsh"
            else
                dsh_npm_bin=""
            fi
            fixed_candidates="\"$dsh_npm_bin\", \"/opt/homebrew/bin/dsh\", \"/usr/local/bin/dsh\""
            override_strict="false"
            strict_exit_code="127"
            argv_policy=".passthrough"
            ;;
        *)
            echo "make launchers: unknown launcher target: $target" >&2
            exit 1
            ;;
    esac

    cat > "$config_path" <<EOF
let launcherConfig = LauncherConfig(
    targetExecutable: "$target_executable",
    overrideKeys: [$override_keys],
    fixedCandidates: [$fixed_candidates],
    overrideStrict: $override_strict,
    strictExitCode: $strict_exit_code,
    argvPolicy: $argv_policy
)
EOF
}

write_info_plist() {
    local app_directory="$1"
    local display_name="$2"
    local identifier="$3"
    local executable="$4"
    local version="$5"

    cat > "$app_directory/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$display_name</string>
  <key>CFBundleIdentifier</key><string>$identifier</string>
  <key>CFBundleVersion</key><string>$version</string>
  <key>CFBundleShortVersionString</key><string>$version</string>
  <key>CFBundleExecutable</key><string>$executable</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
EOF
}

build_launcher() {
    local target="$1"
    local display_name="$2"
    local executable="$3"
    local version="$4"
    local app_directory="$REPO_ROOT/bin/${display_name}.app"
    local macos_directory="$app_directory/Contents/MacOS"
    local config_path="$temporary_directory/${target}.generated.swift"
    local identifier="ai.instrukt.${target}launcher"

    write_config "$target" "$config_path"
    rm -rf "$app_directory"
    mkdir -p "$macos_directory"
    swiftc -O -o "$macos_directory/$executable" "$SOURCE_FILE" "$config_path"
    chmod +x "$macos_directory/$executable"
    write_info_plist "$app_directory" "$display_name" "$identifier" "$executable" "$version"
    codesign --force --options runtime --timestamp=none --identifier "$identifier" --sign "$AUTHORITY" "$app_directory"
    codesign --verify --strict "$app_directory"
    echo "make launchers: built and signed $app_directory"
}

build_launcher tmux TmuxLauncher tmux-launcher 1.2
build_launcher claude ClaudeLauncher claude-launcher 1.0
build_launcher codex CodexLauncher codex-launcher 1.0
build_launcher gemini GeminiLauncher gemini-launcher 1.0
build_launcher deepseek DeepSeekLauncher deepseek-launcher 1.0
