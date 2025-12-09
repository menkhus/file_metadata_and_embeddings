#!/bin/bash
# Uninstall FileIndexer daemon

set -e

echo "Uninstalling FileIndexer..."

# Stop and unload daemon
if launchctl list | grep -q com.fileindexer; then
    echo "Stopping daemon..."
    launchctl stop com.fileindexer 2>/dev/null || true
    launchctl unload ~/Library/LaunchAgents/com.fileindexer.plist 2>/dev/null || true
fi

# Remove launchd plist
if [ -f ~/Library/LaunchAgents/com.fileindexer.plist ]; then
    echo "Removing launchd plist..."
    rm ~/Library/LaunchAgents/com.fileindexer.plist
fi

# Remove binary
if [ -f /usr/local/bin/FileIndexer ]; then
    echo "Removing binary..."
    sudo rm /usr/local/bin/FileIndexer
fi

# Ask about data
echo ""
read -p "Remove database and logs? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf ~/Library/Application\ Support/FileSearch
    rm -f /tmp/fileindexer.log
    rm -f /tmp/fileindexer.error.log
    echo "✓ Data removed"
fi

echo ""
echo "✓ FileIndexer uninstalled"
