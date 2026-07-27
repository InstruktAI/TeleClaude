import Darwin
import Foundation

/// A launcher preserves its own bundle identity for macOS privacy checks by spawning
/// its target as a child instead of replacing its own process image with `exec`.
enum ArgvPolicy {
    case tmuxServer
    case passthrough
}

struct LauncherConfig {
    let targetExecutable: String
    let overrideKeys: [String]
    let fixedCandidates: [String]
    let overrideStrict: Bool
    let strictExitCode: Int32
    let argvPolicy: ArgvPolicy
}

private var childPid: pid_t = 0

private func isExecutable(_ path: String) -> Bool {
    access(path, X_OK) == 0
}

private func resolveTargetPath() -> String? {
    let environment = ProcessInfo.processInfo.environment

    for key in launcherConfig.overrideKeys {
        guard let override = environment[key] else {
            continue
        }
        if !override.isEmpty && isExecutable(override) {
            return override
        }
        if launcherConfig.overrideStrict {
            return nil
        }
    }

    for candidate in launcherConfig.fixedCandidates where isExecutable(candidate) {
        return candidate
    }

    if let pathEnvironment = environment["PATH"] {
        for directory in pathEnvironment.split(separator: ":") {
            let candidate = String(directory) + "/" + launcherConfig.targetExecutable
            if isExecutable(candidate) {
                return candidate
            }
        }
    }

    return nil
}

private func hasUnusableStrictOverride() -> Bool {
    let environment = ProcessInfo.processInfo.environment
    guard launcherConfig.overrideStrict else {
        return false
    }
    return launcherConfig.overrideKeys.contains { key in
        guard let override = environment[key] else {
            return false
        }
        return override.isEmpty || !isExecutable(override)
    }
}

private func targetArguments(from launcherArguments: [String]) -> [String] {
    switch launcherConfig.argvPolicy {
    case .tmuxServer:
        if launcherArguments == ["--teleclaude-server"] {
            return ["-D"]
        }
        return ["-N"] + launcherArguments
    case .passthrough:
        return launcherArguments
    }
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

let launcherPath: String
if let resolvedPath = resolveTargetPath() {
    launcherPath = resolvedPath
} else if hasUnusableStrictOverride() {
    fputs("launcher: configured override for \(launcherConfig.targetExecutable) is not executable\n", stderr)
    exit(launcherConfig.strictExitCode)
} else {
    fputs("launcher: could not find executable \(launcherConfig.targetExecutable) binary\n", stderr)
    exit(127)
}

let arguments = [launcherPath] + targetArguments(from: Array(CommandLine.arguments.dropFirst()))
var cArguments = arguments.map { strdup($0) } + [nil]
defer {
    for pointer in cArguments where pointer != nil {
        free(pointer)
    }
}

let spawnResult = posix_spawn(&childPid, launcherPath, nil, nil, &cArguments, environ)
if spawnResult != 0 {
    fputs("launcher: posix_spawn failed (\(spawnResult)): \(String(cString: strerror(spawnResult)))\n", stderr)
    exit(1)
}

registerSignalForwarding()

var status: Int32 = 0
while waitpid(childPid, &status, 0) == -1 {
    if errno == EINTR {
        continue
    }
    fputs("launcher: waitpid failed: \(String(cString: strerror(errno)))\n", stderr)
    exit(1)
}

if exitedNormally(status) {
    exit(exitCode(status))
}
if terminatedBySignal(status) {
    exit(128 + terminatingSignal(status))
}
exit(1)
