# Upgrading

This guide holds the steps a running installation cannot take through its forward migrations alone — a new
required setting or credential, an outside system to prepare, a data conversion that needs a backup first. An
installation that follows stable never installs a release beyond its compatibility series on its own: its
installation inspector reads the sections of every version between the active release and the held release,
oldest first, performs their steps in order, then installs the release. A version that needs no such step has no
section.

Each section is headed `## <version>` for the release that ships the change, and its steps are an ordered list
written in the order they must run.

## 0.10.0

1. On Linux hosts, install the libarchive shared library before installing this release, or re-run the full installer (`bin/install.sh`), which now installs it: `libarchive-tools` on Debian/Ubuntu, `libarchive` on Fedora and Arch. The chiptunes corpus extraction decodes the pinned HVSC archive through it. macOS ships the library and needs nothing.
2. For every project on the GitHub workflow store, give the GitHub App mapped to the `builder` role the repository's Contents read permission on that repository: grant it in the App's settings and accept it on the App's installation, before installing this release. The store now reads whether an item's branch is on GitHub before it opens that item's pull request. Without the permission, those pull requests stay owed with the refused credential as their cause and are not opened. An App that already holds Contents read or write needs nothing.
3. On every computer, before installing this release, run a local Redis for the computer's own events under the operating system's service manager. It listens only on a Unix socket and requires its own ACL user; any other Redis use of `localhost:6379` on the computer ends.
   - macOS: `brew install redis`. Create `~/.teleclaude/redis/` with mode 0700 and append to `$(brew --prefix)/etc/redis.conf`: `port 0`, `unixsocket <that directory>/redis.sock`, `unixsocketperm 700`, `user default off` and `user teleclaude on ><generated password> ~* &* +@all`. Then `brew services restart redis`.
   - Linux: install the `redis-server` package and append the same lines to `/etc/redis/redis.conf`, with `unixsocket /run/redis/redis-server.sock` and `unixsocketperm 770`; add the TeleClaude user to the `redis` group, then restart `redis-server`.
4. In each computer's TeleClaude `.env`, add `REDIS_LOCAL_URL=unix://<that directory>/redis.sock`, `REDIS_LOCAL_USERNAME` and `REDIS_LOCAL_PASSWORD` for that computer's local Redis, and `REDIS_CLUSTER_URL` and `REDIS_CLUSTER_PASSWORD` with the current `REDIS_URL` and `REDIS_PASSWORD` values. The release's configuration migration moves the `redis` block under `redis.cluster` and adds `redis.local`, both reading these variables; `REDIS_URL` and `REDIS_PASSWORD` can be removed once the release runs.
