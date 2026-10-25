# Upgrading

This guide holds the steps a running installation cannot take through its forward migrations alone — a new
required setting or credential, an outside system to prepare, a data conversion that needs a backup first. An
installation that follows stable never installs a release beyond its compatibility series on its own: its
installation inspector reads the sections of every version between the active release and the held release,
oldest first, performs their steps in order, then installs the release. A version that needs no such step has no
section.

Each section is headed `## <version>` for the release that ships the change, and its steps are an ordered list
written in the order they must run.
