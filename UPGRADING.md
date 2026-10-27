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
3. Each computer's install sets up its local Redis by itself: it installs Redis while the previous release serves and applies the configuration before the release's migrations (ADR-0140, ADR-0141), whether the edge or stable channel installs it or `telec app install` does. On a computer whose cluster Redis is on another computer, it installs the Redis package when missing and configures the operating system's Redis as the local Redis: a Unix socket only the TeleClaude user can open, the TCP port off, the default user off and an ACL user with a generated password, written to the machine `.env` as `REDIS_LOCAL_URL`, `REDIS_LOCAL_USERNAME` and `REDIS_LOCAL_PASSWORD`. On Linux (Debian and Ubuntu, Fedora, Arch) this needs sudo that works without a prompt when the install runs unattended. When the local Redis cannot be set up, for example without that sudo access or because another program uses the Redis, the install still completes, the computer keeps its local events on the cluster Redis, and the install log and every daemon start name the reason (ADR-0141). Grant the access, or run a dedicated Redis and set the three variables to reach it; the next install sets it up. The computer that hosts the cluster Redis gets no local Redis.
4. The cluster Redis variables are now `REDIS_CLUSTER_URL` and `REDIS_CLUSTER_PASSWORD`. Every install copies the values of `REDIS_URL` and `REDIS_PASSWORD` into them before the configuration migration points `redis.cluster` at them; `REDIS_URL` and `REDIS_PASSWORD` stay in `.env` unused and can be removed after the install.
