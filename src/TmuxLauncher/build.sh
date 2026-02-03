#!/bin/bash
# Build TmuxLauncher.app
#
# This creates a macOS app bundle that wraps tmux, allowing it to inherit
# permissions granted to the app (like Full Disk Access).

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_DIR="$REPO_ROOT/bin/TmuxLauncher.app"
MACOS_DIR="$APP_DIR/Contents/MacOS"

echo "Building TmuxLauncher..."

# Compile Swift source
swiftc -O -o "$SCRIPT_DIR/tmux-launcher" "$SCRIPT_DIR/main.swift"

# Ensure app bundle structure exists
mkdir -p "$MACOS_DIR"

# Copy binary
cp "$SCRIPT_DIR/tmux-launcher" "$MACOS_DIR/tmux-launcher"
chmod +x "$MACOS_DIR/tmux-launcher"

# Create/update Info.plist
cat > "$APP_DIR/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>TmuxLauncher</string>
  <key>CFBundleIdentifier</key><string>ai.instrukt.tmuxlauncher</string>
  <key>CFBundleVersion</key><string>1.1</string>
  <key>CFBundleShortVersionString</key><string>1.1</string>
  <key>CFBundleExecutable</key><string>tmux-launcher</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
EOF

# Sign the app (ad-hoc signing for local use)
codesign --force --sign - "$APP_DIR"

# Clean up intermediate file
rm -f "$SCRIPT_DIR/tmux-launcher"

echo "Done! Built: $APP_DIR"
echo ""
echo "To install to ~/Applications:"
echo "  cp -r '$APP_DIR' ~/Applications/"
echo ""
echo "Remember to grant Full Disk Access to TmuxLauncher.app in System Preferences"
