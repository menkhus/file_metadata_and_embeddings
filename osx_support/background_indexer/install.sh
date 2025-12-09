#!/bin/bash
# Install FileIndexer daemon (optional - for production use)

set -e

echo "⚠️  WARNING: This installs system-wide"
echo "For development, just run: .build/debug/FileIndexer --once --verbose"
echo ""
read -p "Continue with installation? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Installation cancelled."
    exit 0
fi

echo "Building FileIndexer..."
swift build -c release

echo "Installing binary..."
sudo cp .build/release/FileIndexer /usr/local/bin/

echo "Creating application support directory..."
mkdir -p ~/Library/Application\ Support/FileSearch

echo "Installing launchd plist..."
cp com.fileindexer.plist ~/Library/LaunchAgents/

echo "Loading daemon..."
launchctl load ~/Library/LaunchAgents/com.fileindexer.plist

echo ""
echo "✓ FileIndexer installed successfully!"
echo ""
echo "Control commands:"
echo "  launchctl start com.fileindexer"
echo "  launchctl stop com.fileindexer"
echo "  launchctl list | grep fileindexer"
echo ""
echo "Logs:"
echo "  tail -f /tmp/fileindexer.log"
echo "  tail -f /tmp/fileindexer.error.log"
echo ""
echo "To uninstall: ./uninstall.sh"
