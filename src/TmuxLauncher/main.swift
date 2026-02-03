import Foundation

/// TmuxLauncher - A wrapper that execs tmux with full signal forwarding.
///
/// This app bundle exists solely to give tmux macOS permissions (Full Disk Access, etc.)
/// by wrapping it in a signed .app bundle. It uses execv() to replace itself with tmux,
/// ensuring all signals (including SIGWINCH for terminal resize) are delivered directly
/// to tmux rather than being intercepted by this wrapper.

let tmuxPath = "/opt/homebrew/bin/tmux"

// Build argv for execv: [path, arg1, arg2, ...]
var args = [tmuxPath] + Array(CommandLine.arguments.dropFirst())

// Convert to C strings for execv
let cArgs = args.map { strdup($0) } + [nil]

// Replace this process with tmux - signals will go directly to tmux
execv(tmuxPath, cArgs)

// If execv returns, it failed
perror("execv failed")
exit(1)
