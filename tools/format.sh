#!/usr/bin/env sh
# Thin wrapper — all formatting logic lives in teleclaude.quality.format
exec telec code format "$@"
