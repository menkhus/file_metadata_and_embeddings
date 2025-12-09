# Distribution Guide

How to package and distribute the macOS File Search system.

## Development vs Distribution

### Development (Local Testing)
- ✅ Build in place
- ✅ Test from build directories
- ✅ No system installation
- ✅ Easy to clean up

### Distribution (End Users)
- Package as app bundle
- Code sign for security
- Notarize for Gatekeeper
- Create installer

## Development Workflow (Recommended)

### 1. Build Locally

```bash
cd osx_support
./build_all.sh
```

Products:
- `sqlite_faiss_extension/faiss_extension.dylib`
- `background_indexer/.build/release/FileIndexer`

### 2. Test Locally

```bash
# Test extension
cd sqlite_faiss_extension
./test_extension.sh

# Test indexer
cd ../background_indexer
.build/debug/FileIndexer --once --verbose
```

### 3. Use Locally

```bash
# Use extension from build directory
sqlite3 ~/my_database.db
sqlite> .load /path/to/osx_support/sqlite_faiss_extension/faiss_extension.dylib

# Run indexer from build directory
.build/release/FileIndexer --database ~/my_database.db
```

**No installation needed for development!**

## Distribution Options

### Option 1: App Bundle (Recommended)

Package everything as a macOS app:

```
FileSearch.app/
├── Contents/
│   ├── MacOS/
│   │   ├── FileSearch (GUI app)
│   │   └── FileIndexer (daemon)
│   ├── Resources/
│   │   └── faiss_extension.dylib
│   ├── Info.plist
│   └── _CodeSignature/
```

**Advantages:**
- Single .app to distribute
- Code signing built-in
- Easy to install (drag to Applications)
- Easy to uninstall (delete .app)

### Option 2: Installer Package

Create a .pkg installer:

```bash
pkgbuild --root /tmp/install \
  --identifier com.filesearch.pkg \
  --version 1.0 \
  --install-location /Applications \
  FileSearch.pkg
```

**Advantages:**
- Professional installation
- Can run scripts
- Uninstaller support

### Option 3: DMG Image

Distribute as disk image:

```bash
hdiutil create -volname "FileSearch" \
  -srcfolder FileSearch.app \
  -ov -format UDZO \
  FileSearch.dmg
```

**Advantages:**
- Standard macOS distribution
- Can include README, license
- Drag-and-drop installation

## Code Signing

Required for distribution outside App Store:

### 1. Get Developer Certificate

```bash
# Check existing certificates
security find-identity -v -p codesigning

# You need: "Developer ID Application: Your Name (TEAMID)"
```

Get from: https://developer.apple.com/account/

### 2. Sign Extension

```bash
codesign --sign "Developer ID Application" \
  --timestamp \
  --options runtime \
  faiss_extension.dylib
```

### 3. Sign Executable

```bash
codesign --sign "Developer ID Application" \
  --timestamp \
  --options runtime \
  --entitlements FileIndexer.entitlements \
  FileIndexer
```

### 4. Sign App Bundle

```bash
codesign --sign "Developer ID Application" \
  --timestamp \
  --options runtime \
  --deep \
  FileSearch.app
```

### 5. Verify

```bash
codesign -vvv --deep --strict FileSearch.app
spctl -a -vvv FileSearch.app
```

## Notarization

Required for Gatekeeper approval:

### 1. Create Archive

```bash
ditto -c -k --keepParent FileSearch.app FileSearch.zip
```

### 2. Submit for Notarization

```bash
xcrun notarytool submit FileSearch.zip \
  --apple-id "your@email.com" \
  --team-id "TEAMID" \
  --password "app-specific-password" \
  --wait
```

### 3. Staple Ticket

```bash
xcrun stapler staple FileSearch.app
```

### 4. Verify

```bash
spctl -a -vvv FileSearch.app
# Should say: "accepted"
```

## Creating App Bundle

### Structure

```bash
mkdir -p FileSearch.app/Contents/{MacOS,Resources}

# Copy binaries
cp background_indexer/.build/release/FileIndexer \
   FileSearch.app/Contents/MacOS/

cp sqlite_faiss_extension/faiss_extension.dylib \
   FileSearch.app/Contents/Resources/

# Copy GUI app (when built)
cp gui_app/.build/release/FileSearchApp \
   FileSearch.app/Contents/MacOS/FileSearch
```

### Info.plist

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>FileSearch</string>
    <key>CFBundleIdentifier</key>
    <string>com.yourcompany.filesearch</string>
    <key>CFBundleName</key>
    <string>FileSearch</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>NSHumanReadableCopyright</key>
    <string>Copyright © 2024</string>
</dict>
</plist>
```

## Entitlements

For hardened runtime:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
    <key>com.apple.security.files.user-selected.read-write</key>
    <true/>
</dict>
</plist>
```

## Automated Build Script

```bash
#!/bin/bash
# build_release.sh - Build and package for distribution

set -e

VERSION="1.0.0"
BUNDLE_ID="com.yourcompany.filesearch"
SIGN_ID="Developer ID Application: Your Name (TEAMID)"

echo "Building FileSearch v${VERSION}..."

# Clean
rm -rf FileSearch.app FileSearch.dmg

# Build components
cd osx_support
./build_all.sh

# Create app bundle
mkdir -p FileSearch.app/Contents/{MacOS,Resources}

# Copy binaries
cp background_indexer/.build/release/FileIndexer \
   FileSearch.app/Contents/MacOS/
cp sqlite_faiss_extension/faiss_extension.dylib \
   FileSearch.app/Contents/Resources/

# Create Info.plist
cat > FileSearch.app/Contents/Info.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>${BUNDLE_ID}</string>
    <key>CFBundleVersion</key>
    <string>${VERSION}</string>
</dict>
</plist>
EOF

# Code sign
codesign --sign "${SIGN_ID}" --timestamp --options runtime \
  FileSearch.app/Contents/Resources/faiss_extension.dylib
codesign --sign "${SIGN_ID}" --timestamp --options runtime \
  FileSearch.app/Contents/MacOS/FileIndexer
codesign --sign "${SIGN_ID}" --timestamp --options runtime --deep \
  FileSearch.app

# Create DMG
hdiutil create -volname "FileSearch" \
  -srcfolder FileSearch.app \
  -ov -format UDZO \
  FileSearch.dmg

# Notarize
xcrun notarytool submit FileSearch.dmg \
  --apple-id "your@email.com" \
  --team-id "TEAMID" \
  --password "app-specific-password" \
  --wait

# Staple
xcrun stapler staple FileSearch.dmg

echo "✓ Release build complete: FileSearch.dmg"
```

## For Development: Skip All This!

**Just build and test locally:**

```bash
cd osx_support
./build_all.sh
cd sqlite_faiss_extension
./test_extension.sh
```

Use the binaries directly from build directories. No installation, no signing, no notarization needed for development!

## Summary

**Development:**
- Build locally
- Test from build directories
- No system installation

**Distribution:**
- Create app bundle
- Code sign
- Notarize
- Package as DMG or PKG

Choose the right approach for your use case!
