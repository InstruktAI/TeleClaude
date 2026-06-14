---
description: py7zr — pure-Python 7-Zip (.7z) archive library. Used for verified on-demand extraction of the HVSC chiptune corpus into the configured music directory.
---

# py7zr — Third-Party

## What it is

`py7zr` is a pure-Python library for 7-Zip (`.7z`) archive compression and
decompression. Being pure-Python, it requires no system `7z` / `p7zip` binary and
installs as an ordinary Python dependency. It supports the LZMA2, Brotli,
ZStandard, and PPMd methods used by 7-Zip archives.

## Extraction usage (the pinned pattern)

Open the archive in read mode and extract all members into a target directory:

```python
import py7zr

with py7zr.SevenZipFile(archive_path, mode="r") as archive:
    archive.extractall(path=target_dir)
```

`extractall(path=...)` writes every archive member under `target_dir`; `path`
defaults to the current working directory when omitted. The `SevenZipFile`
context manager closes the archive on exit. `py7zr` also registers a
`shutil.unpack_archive` handler for `.7z`, but the explicit `SevenZipFile` form
above is the one this project uses so the call site is self-evident.

## Operational notes

- Pure-Python: no system 7z binary required. Install it in the default dependency
  set so extraction is available wherever the daemon runs (an optional/extra group
  would leave a normally-installed daemon unable to provision).
- Decompressing a large archive (HVSC ~80 MB compressed → ~452 MB on disk) is
  CPU- and IO-bound; run it off the event loop (a worker thread) so the daemon is
  never blocked.
- Verify archive integrity (sha256) BEFORE extracting; `py7zr` extraction does not
  by itself authenticate the source.

## Sources

- https://github.com/miurahr/py7zr (official repository and README)
- https://py7zr.readthedocs.io/ (official documentation)
