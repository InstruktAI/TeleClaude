import Darwin
import Foundation

/// TmuxLauncher - A wrapper that launches tmux while preserving wrapper identity.
///
/// Important: we must NOT `exec` tmux directly because that replaces this process and
/// loses wrapper attribution for macOS privacy checks (TCC). Instead we spawn tmux as a
/// child, forward key signals, and return tmux's exact exit code.

private var childPid: pid_t = 0

private func isExecutable(_ path: String) -> Bool {
    access(path, X_OK) == 0
}

private func resolveTmuxPath() -> String? {
    let env = ProcessInfo.processInfo.environment

    for key in ["TMUX_LAUNCHER_TARGET", "TMUX_BINARY"] {
        if let override = env[key], !override.isEmpty, isExecutable(override) {
            return override
        }
    }

    let fixedCandidates = [
        "/opt/homebrew/bin/tmux",
        "/usr/local/bin/tmux",
        "/usr/bin/tmux",
    ]
    for candidate in fixedCandidates where isExecutable(candidate) {
        return candidate
    }

    if let pathEnv = env["PATH"] {
        for dir in pathEnv.split(separator: ":") {
            let candidate = String(dir) + "/tmux"
            if isExecutable(candidate) {
                return candidate
            }
        }
    }

    return nil
}

private func forwardSignal(_ signal: Int32) {
    if childPid > 0 {
        _ = kill(childPid, signal)
    }
}

private func registerSignalForwarding() {
    _ = Darwin.signal(SIGINT, forwardSignal)
    _ = Darwin.signal(SIGTERM, forwardSignal)
    _ = Darwin.signal(SIGHUP, forwardSignal)
    _ = Darwin.signal(SIGQUIT, forwardSignal)
    _ = Darwin.signal(SIGWINCH, forwardSignal)
    _ = Darwin.signal(SIGUSR1, forwardSignal)
    _ = Darwin.signal(SIGUSR2, forwardSignal)
}

private func exitedNormally(_ status: Int32) -> Bool {
    (status & 0x7f) == 0
}

private func exitCode(_ status: Int32) -> Int32 {
    (status >> 8) & 0xff
}

private func terminatedBySignal(_ status: Int32) -> Bool {
    let signalBits = status & 0x7f
    return signalBits != 0 && signalBits != 0x7f
}

private func terminatingSignal(_ status: Int32) -> Int32 {
    status & 0x7f
}

guard let tmuxPath = resolveTmuxPath() else {
    fputs("tmux-launcher: could not find executable tmux binary\n", stderr)
    exit(127)
}

var args = [tmuxPath] + Array(CommandLine.arguments.dropFirst())
var cArgs = args.map { strdup($0) } + [nil]
defer {
    for pointer in cArgs where pointer != nil {
        free(pointer)
    }
}

let spawnResult = posix_spawn(&childPid, tmuxPath, nil, nil, &cArgs, environ)
if spawnResult != 0 {
    fputs("tmux-launcher: posix_spawn failed (\(spawnResult)): \(String(cString: strerror(spawnResult)))\n", stderr)
    exit(1)
}

registerSignalForwarding()

var status: Int32 = 0
while waitpid(childPid, &status, 0) == -1 {
    if errno == EINTR {
        continue
    }
    fputs("tmux-launcher: waitpid failed: \(String(cString: strerror(errno)))\n", stderr)
    exit(1)
}

if exitedNormally(status) {
    exit(exitCode(status))
}
if terminatedBySignal(status) {
    exit(128 + terminatingSignal(status))
}
exit(1)
