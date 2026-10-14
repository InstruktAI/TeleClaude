---
description: ffprobe stream inspection — selecting audio streams, printing only their codec type, and the exit status for input that is not recognized as media.
---

# ffprobe Stream Inspection — Third-Party

## What it is

`ffprobe` is the FFmpeg project's multimedia stream analyzer. It reads a file
or URL and prints information about its container and streams. It is installed
with FFmpeg: the Homebrew `ffmpeg` formula and the Debian `ffmpeg` package both
ship the `ffprobe` binary beside `ffmpeg`.

## Inspecting a file's audio streams

```
ffprobe -v error -select_streams a -show_entries stream=codec_type -of csv=p=0 <input>
```

- `-v error` (alias of `-loglevel`) shows only errors.
- `-select_streams a` selects only the streams matching the stream specifier;
  `a` is the audio stream type.
- `-show_entries stream=codec_type` prints only the `codec_type` entry of the
  `stream` section.
- `-of csv=p=0` (`-of` is short for `-output_format`) uses the CSV writer with
  `print_section` disabled, so each selected stream prints as a bare line.

A file with at least one audio stream prints one `audio` line per audio stream;
a file that is media but has no audio stream prints nothing.

## Exit status

If the input cannot be opened or recognized as a multimedia file, `ffprobe`
returns a positive exit code. The documentation names no specific code.

## Sources

- https://ffmpeg.org/ffprobe.html
- https://packages.debian.org/bookworm/amd64/ffmpeg/filelist
- https://formulae.brew.sh/formula/ffmpeg
