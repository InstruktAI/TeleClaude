---
description: libarchive-c — Python ctypes binding to the system libarchive. Library discovery, reading archive entries, and extracting them to disk with rewritten paths and safety flags.
---

# libarchive-c — Third-Party

## What it is

`libarchive-c` (import name `libarchive`) is a Python interface to the C
libarchive library, built on `ctypes`. It is a pure-Python package (one
`py3-none-any` wheel) and ships no copy of libarchive: it loads the shared
library already installed on the machine. Its reading and extraction support is
whatever that libarchive build supports.

## Locating the shared library

At import, `libarchive.ffi` loads the library named by the `LIBARCHIVE`
environment variable, otherwise `ctypes.util.find_library('archive')`.

- macOS includes libarchive in the base system; on macOS 27.2, `find_library`
  returns `/usr/lib/libarchive.dylib` (libarchive 3.7.4,
  `libarchive.ffi.version_number()` = `3007004`).
- On Debian the library package is `libarchive13t64` in trixie (`libarchive13`
  before the 64-bit `time_t` transition). `libarchive-tools`, which provides
  `bsdtar`, depends on it, so installing `libarchive-tools` installs the
  library under either name.

## Reading entries

`libarchive.file_reader(path)` is a context manager yielding the archive; iterating
it yields `ArchiveEntry` objects in archive order. Each entry exposes
`pathname`, `isdir`, `isfile`, `issym`, `islnk`, `size` and similar properties.
`pathname` (like `linkpath`, `mode`, `mtime` and others) has a setter, so the
path an entry is written to can be changed before extraction. `fd_reader` and
`memory_reader` read from a file descriptor or bytes.

## Extracting to disk

- `libarchive.extract_file(path, flags=None)`, `extract_fd` and `extract_memory`
  extract **into the process's current working directory**. Entry paths are
  relative to it, so extracting elsewhere with these functions means changing
  the directory of the whole process.
- `libarchive.extract.extract_entries(entries, flags=None)` writes any iterable
  of entries through libarchive's disk writer, to each entry's `pathname` as it
  is when written. Combined with the `pathname` setter, it writes entries to
  chosen absolute paths without changing the working directory.
- Flags are the `EXTRACT_*` constants in `libarchive.extract`, for example
  `EXTRACT_SECURE_NODOTDOT` (refuse paths containing `..`),
  `EXTRACT_SECURE_SYMLINKS` (refuse writing through a symlink) and
  `EXTRACT_SECURE_NOABSOLUTEPATHS` (refuse absolute paths). `PREVENT_ESCAPE`
  combines those three. When `flags` is `None`, `extract_entries` uses
  `PREVENT_ESCAPE`, or `0` if the working directory is `/`. Entries rewritten
  to absolute paths need a flag set without `EXTRACT_SECURE_NOABSOLUTEPATHS`.
- Failures raise `libarchive.exception.ArchiveError`.

## 7-Zip archives with BCJ2

Through the macOS system libarchive 3.7.4, `libarchive-c` 5.3 extracted the HVSC
#84 archive (`HVSC_84-all-of-them.7z`, methods LZMA, PPMd and BCJ2) completely:
60,737 files, all under the single top-level directory `C64Music`, with no link
entries. The libarchive-formats(5) manual does not enumerate which 7-Zip filters
libarchive decodes. That observation is the evidence for BCJ2 on that build.

## Sources

- https://github.com/Changaco/python-libarchive-c (official repository and usage)
- https://pypi.org/project/libarchive-c/ (package and wheels)
- https://packages.debian.org/trixie/libarchive-tools (Debian dependency on the library)
- https://man.freebsd.org/cgi/man.cgi?query=libarchive-formats&sektion=5 (libarchive formats)
