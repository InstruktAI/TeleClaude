---
description: py7zr — pure-Python 7-Zip (.7z) archive library. Extraction usage, supported methods, and the BCJ2 filter it cannot decode.
---

# py7zr — Third-Party

## What it is

`py7zr` is a pure-Python library for 7-Zip (`.7z`) archive compression and
decompression. Being pure-Python, it requires no system `7z` / `p7zip` binary and
installs as an ordinary Python dependency. It supports the LZMA2, Brotli,
ZStandard, and PPMd methods used by 7-Zip archives.

## Extraction usage

Open the archive in read mode and extract all members into a target directory:

```python
import py7zr

with py7zr.SevenZipFile(archive_path, mode="r") as archive:
    archive.extractall(path=target_dir)
```

`extractall(path=...)` writes every archive member under `target_dir`; `path`
defaults to the current working directory when omitted. The `SevenZipFile`
context manager closes the archive on exit. `py7zr` also registers a
`shutil.unpack_archive` handler for `.7z`.

## Unsupported filters

- **BCJ2 is not supported.** The README lists BCJ2 among unsupported methods:
  Python's standard `lzma` module depends on liblzma, which provides no BCJ2
  filter. The plain BCJ branch filters (x86, ARM, ARMT, PPC, SPARC, IA64) and
  Delta are supported.
- Reading an archive that uses BCJ2 raises
  `py7zr.exceptions.UnsupportedCompressionMethodError` when extraction reaches the
  BCJ2-coded folder. Members from folders decoded before it have already been
  written to the target directory, so a failed `extractall` can leave partial
  output behind. Observed with py7zr 1.1.3 on the HVSC #84 archive
  (`HVSC_84-all-of-them.7z`), whose methods are LZMA, PPMd and BCJ2.
- `SevenZipFile.archiveinfo()` reports an archive's methods without extracting it,
  with BCJ2 shown as `BCJ2*`.

## Operational notes

- Decompressing a large archive is CPU- and IO-bound; run it off an event loop
  (a worker thread).
- `py7zr` extraction does not authenticate the source; verify integrity (for
  example a SHA-256 of the archive) before extracting.

## Sources

- https://github.com/miurahr/py7zr (official repository and README)
- https://github.com/miurahr/py7zr#compression-algorithms (supported and unsupported methods)
- https://py7zr.readthedocs.io/ (official documentation)
