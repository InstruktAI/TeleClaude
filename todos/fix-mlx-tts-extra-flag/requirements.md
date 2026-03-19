<!-- from-main: inline work delivered under human supervision -->
# Requirements: fix-mlx-tts-extra-flag

Remove --extra mlx from uv run CLI fallback — mlx-audio is now a platform-conditional regular dep, not an optional extra
