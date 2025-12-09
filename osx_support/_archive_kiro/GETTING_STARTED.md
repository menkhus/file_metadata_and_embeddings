# Getting Started with macOS Native File Search

Quick start guide for building and using the native macOS implementation.

## 5-Minute Quick Start (Command Line Only)

```bash
# 1. Install Command Line Tools (if not already installed)
xcode-select --install

# 2. Build dependencies from source (one-time, ~15 min)
# See BUILD_FROM_SOURCE.md for details
cd ~/build_from_source
git clone https://github.com/facebookresearch/faiss.git
cd faiss
cmake -B build -DFAISS_ENABLE_PYTHON=OFF -DFAISS_ENABLE_GPU=OFF
cmake --build build -j$(sysctl -n hw.ncpu)
sudo cmake --install build

# 3. Build project (uses Makefiles, no Xcode IDE)
cd /path/to/file_metadata_and_embeddings/osx_support
./build_all.sh

# 4. Test locally (no installation needed)
cd sqlite_faiss_extension
make test

# Extension is ready: ./faiss_extension.dylib
# Indexer is ready: ../background_indexer/.build/release/FileIndexer
```

**No Xcode IDE required!** Just command-line tools.

## What You Get

✅ **Zero Python** - Pure C++/Swift implementation  
✅ **SQLite Extension** - Native semantic search via SQL  
✅ **Background Indexer** - Non-intrusive file monitoring  
✅ **Xcode Ready** - Full workspace with build configs  
✅ **Production Ready** - Code signing, launchd integration  

## Architecture

```
┌─────────────────────────────────────┐
│   Xcode Workspace                   │
│   FileSearchWorkspace.xcworkspace   │
└────────────┬────────────────────────┘
             │
             ├─→ SQLiteFAISS.xcodeproj (C++)
             │   • faiss_extension.dylib
             │   • SQL functions for semantic search
             │
             └─→ FileIndexer (Swift Package)
                 • Background daemon
                 • FSEvents monitoring
                 • launchd integration
```

## Prerequisites

### Required

- **macOS 13.0+** (Ventura or later)
- **Command Line Tools** (clang, make, git, cmake)

### Install Command Line Tools

```bash
# This installs clang, make, git, and other build tools
# No Xcode IDE needed!
xcode-select --install

# Verify
clang --version
make --version
git --version
```

**Note:** You do NOT need the full Xcode IDE. Command Line Tools are sufficient.

### Build Dependencies from Source

**Recommended approach** - Full control, no package managers:

See [BUILD_FROM_SOURCE.md](./BUILD_FROM_SOURCE.md) for complete step-by-step instructions.

**Quick summary:**
```bash
# Create build directory
mkdir -p ~/build_from_source && cd ~/build_from_source

# Build FAISS (pure C++, no Python)
git clone https://github.com/facebookresearch/faiss.git
cd faiss
cmake -B build \
  -DFAISS_ENABLE_PYTHON=OFF \
  -DFAISS_ENABLE_GPU=OFF \
  -DCMAKE_INSTALL_PREFIX=/usr/local
cmake --build build -j$(sysctl -n hw.ncpu)
sudo cmake --install build

# Verify
ls /usr/local/lib/libfaiss.dylib
ls /usr/local/include/faiss/
```

**Alternative (quick but less control):**
```bash
brew install faiss
```

See [BUILD_FROM_SOURCE.md](./BUILD_FROM_SOURCE.md) for OpenBLAS, SQLite, and ONNX Runtime.

## Building (Command Line)

### Recommended: Use Makefiles

```bash
cd osx_support

# Build all components
./build_all.sh

# Or use top-level Makefile
make all      # Build everything
make test     # Run tests
make clean    # Clean build artifacts
```

### Build Components Individually

**C++ Extension:**
```bash
cd sqlite_faiss_extension
make          # Build
make test     # Test
make clean    # Clean
```

**Swift Indexer:**
```bash
cd background_indexer
swift build -c release    # Build
swift test                # Test
swift package clean       # Clean
```

### What Gets Built

```
sqlite_faiss_extension/
└── faiss_extension.dylib     # SQLite extension

background_indexer/
└── .build/release/
    └── FileIndexer           # Indexer executable
```

**No Xcode IDE needed!** Everything builds with standard Unix tools.

## Testing

### Test SQLite Extension

```bash
cd osx_support/sqlite_faiss_extension
./test_extension.sh
```

**Expected output:**
```
Testing SQLite FAISS Extension...
==================================
Test 1: Build Index
{"status":"success","vectors_loaded":3,"dimension":384}
Test 2: Index Stats
{"vectors":3,"dimension":384,"index_type":"IndexFlatL2","memory_mb":0.00}
✓ All tests passed!
```

### Test Background Indexer

```bash
cd osx_support/background_indexer
swift test
# Or run manually:
swift run FileIndexer --once --verbose
```

## Using Locally (No Installation)

### Test SQLite Extension

```bash
cd osx_support/sqlite_faiss_extension

# Build and test
make test

# Use directly from build directory
sqlite3 test.db
sqlite> .load ./faiss_extension.dylib
sqlite> SELECT faiss_index_stats();
```

### Run Background Indexer

```bash
cd osx_support/background_indexer

# Build
swift build

# Run locally (no daemon installation)
.build/debug/FileIndexer --once --verbose \
  --database ~/test.db \
  --watch-paths "$HOME/Documents"
```

## Distribution (Optional)

For production deployment, see [DISTRIBUTION.md](./DISTRIBUTION.md) for:
- Code signing
- Notarization
- Package creation
- App bundle

**For development: Just use the built binaries directly from the build directories!**

## Usage Examples

### Example 1: Build Index and Search

```bash
# Open database
sqlite3 ~/Library/Application\ Support/FileSearch/file_metadata.db

# Load extension
.load /usr/local/lib/sqlite3/faiss_extension.dylib

# Build index from existing embeddings
SELECT faiss_build_index();
-- Returns: {"status":"success","vectors_loaded":1500,"dimension":384}

# Semantic search
SELECT * FROM faiss_search('error handling in python', 5);
-- Returns: JSON array of top 5 matches

# Get index statistics
SELECT faiss_index_stats();
-- Returns: {"vectors":1500,"dimension":384,"memory_mb":2.2}
```

### Example 2: Control Background Indexer

```bash
# Start daemon
launchctl start com.fileindexer

# Stop daemon
launchctl stop com.fileindexer

# Check status
launchctl list | grep fileindexer

# View logs
tail -f /tmp/fileindexer.log

# Run once manually
FileIndexer --once --verbose --database ~/test.db
```

### Example 3: Configure Watch Directories

```bash
# Edit launchd plist
nano ~/Library/LaunchAgents/com.fileindexer.plist

# Or use defaults
defaults write com.fileindexer watchPaths -array \
  "$HOME/Documents" \
  "$HOME/src" \
  "$HOME/Projects"

# Reload daemon
launchctl unload ~/Library/LaunchAgents/com.fileindexer.plist
launchctl load ~/Library/LaunchAgents/com.fileindexer.plist
```

## Development Workflow

### 1. Edit Code

Use any editor (vim, VS Code, Sublime, etc.):
- `sqlite_faiss_extension/Sources/faiss_extension.cpp`
- `background_indexer/Sources/FileIndexer.swift`

### 2. Build

```bash
cd osx_support
./build_all.sh
```

### 3. Test

```bash
cd sqlite_faiss_extension && make test
cd ../background_indexer && swift test
```

### 4. Debug

**SQLite Extension:**
```bash
lldb sqlite3
(lldb) run test.db
sqlite> .load ./faiss_extension.dylib
sqlite> SELECT faiss_build_index();
```

**Background Indexer:**
```bash
lldb .build/debug/FileIndexer
(lldb) run --once --verbose
```

### 5. Use Locally

```bash
# No installation needed!
sqlite3 test.db ".load ./sqlite_faiss_extension/faiss_extension.dylib"
./background_indexer/.build/release/FileIndexer --once --verbose
```

## Project Structure

```
osx_support/
├── FileSearchWorkspace.xcworkspace/   # Xcode workspace
│   └── contents.xcworkspacedata
│
├── sqlite_faiss_extension/            # C++ SQLite extension
│   ├── SQLiteFAISS.xcodeproj/        # Xcode project
│   ├── Sources/
│   │   ├── faiss_extension.cpp       # Main extension
│   │   ├── onnx_encoder.cpp          # Text encoding
│   │   └── onnx_encoder.h
│   ├── Makefile                       # Build system
│   └── test_extension.sh              # Tests
│
├── background_indexer/                # Swift daemon
│   ├── Sources/
│   │   └── FileIndexer.swift         # Main daemon
│   ├── Package.swift                  # Swift package
│   ├── com.fileindexer.plist         # launchd config
│   └── install.sh                     # Installer
│
├── IMPLEMENTATION_PLAN.md             # Complete architecture
├── README.md                          # Component docs
├── GETTING_STARTED.md                 # This file
├── Makefile                           # Top-level build
└── build_all.sh                       # Build script
```

## Troubleshooting

### Build Errors

**"faiss/IndexFlat.h: No such file or directory"**

```bash
# Install FAISS
brew install faiss

# Check installation
ls /opt/homebrew/include/faiss/
```

**"Undefined symbols for architecture arm64"**

```bash
# Check library paths in Xcode:
# Build Settings → Header Search Paths: /opt/homebrew/include
# Build Settings → Library Search Paths: /opt/homebrew/lib
```

### Runtime Errors

**"dyld: Library not loaded: libfaiss.dylib"**

```bash
# Fix library path
install_name_tool -change libfaiss.dylib \
  /opt/homebrew/lib/libfaiss.dylib \
  faiss_extension.dylib
```

**"Extension not found"**

```bash
# Check installation
ls -la /usr/local/lib/sqlite3/faiss_extension.dylib

# Reinstall
cd sqlite_faiss_extension && sudo make install
```

### Daemon Issues

**"Daemon not starting"**

```bash
# Check logs
tail -f /tmp/fileindexer.error.log

# Check permissions
ls -la /usr/local/bin/FileIndexer

# Reinstall
cd background_indexer && ./install.sh
```

**"No files being indexed"**

```bash
# Run manually to see output
FileIndexer --once --verbose

# Check watch paths
defaults read com.fileindexer watchPaths
```

## Next Steps

1. ✅ **Build and test** - Follow this guide
2. ⏳ **Generate embeddings** - Use Python tools or wait for indexer
3. ⏳ **Add Apple Intents** - Phase 3 (coming soon)
4. ⏳ **Build GUI app** - Phase 4 (coming soon)
5. ⏳ **Code sign & distribute** - Phase 5 (coming soon)

## Resources

- [Implementation Plan](./IMPLEMENTATION_PLAN.md) - Complete architecture
- [Component README](./README.md) - Detailed documentation
- [FAISS Documentation](https://github.com/facebookresearch/faiss/wiki)
- [SQLite Extensions](https://www.sqlite.org/loadext.html)
- [Swift Package Manager](https://swift.org/package-manager/)
- [launchd](https://www.launchd.info/)

## Support

For issues or questions:
1. Check [Troubleshooting](#troubleshooting) section
2. Review [Implementation Plan](./IMPLEMENTATION_PLAN.md)
3. Check build logs in Xcode or terminal

## License

See [LICENSE.txt](../LICENSE.txt) in project root.
