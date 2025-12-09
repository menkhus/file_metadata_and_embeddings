# macOS Native File Search - Documentation Index

Complete native macOS implementation with zero Python dependencies.

## 📚 Documentation Structure

### For Users (Future)
- **[MACOS_FIRST_CLASS_DESIGN.md](./MACOS_FIRST_CLASS_DESIGN.md)** - Vision for proper Mac app
  - What the final product will look like
  - User experience design
  - Proper macOS architecture

### For Developers (Current)

**Start Here:**
1. **[GETTING_STARTED.md](./GETTING_STARTED.md)** - Quick start guide
   - Prerequisites
   - Building from source
   - Local testing (no installation)

**Build Dependencies:**
2. **[BUILD_FROM_SOURCE.md](./BUILD_FROM_SOURCE.md)** - Build FAISS & dependencies
   - Pure C++ approach (no Homebrew)
   - OpenBLAS, FAISS, SQLite, ONNX Runtime
   - Static linking options

**Architecture & Planning:**
3. **[IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)** - Complete 5-phase plan
   - Current: Phase 1 & 2 (C++ extension + Swift indexer)
   - Next: Phase 3-5 (Intents, GUI, Distribution)

4. **[PROJECT_SUMMARY.md](./PROJECT_SUMMARY.md)** - What we've built
   - Component overview
   - File structure
   - Status & next steps

**Distribution (Future):**
5. **[DISTRIBUTION.md](./DISTRIBUTION.md)** - Packaging & deployment
   - Code signing
   - Notarization
   - App bundle creation
   - DMG/PKG creation

## 🎯 Current Status

**Phase 1 & 2 Complete:**
- ✅ SQLite FAISS extension (C++)
- ✅ Background indexer (Swift)
- ✅ Xcode workspace
- ✅ Build system
- ✅ Local testing

**Phase 3-5 In Progress:**
- ⏳ Apple Intents integration
- ⏳ SwiftUI menu bar app
- ⏳ Proper app bundle
- ⏳ Distribution

## 🚀 Quick Start

```bash
# 1. Build dependencies (one-time)
# See BUILD_FROM_SOURCE.md for details
git clone https://github.com/facebookresearch/faiss.git
cd faiss && cmake -B build -DFAISS_ENABLE_PYTHON=OFF
cmake --build build && sudo cmake --install build

# 2. Build project
cd /path/to/file_metadata_and_embeddings/osx_support
./build_all.sh

# 3. Test locally (no installation)
cd sqlite_faiss_extension
make test

# 4. Use from build directory
sqlite3 test.db
sqlite> .load ./faiss_extension.dylib
sqlite> SELECT faiss_index_stats();
```

## 📁 Project Structure

```
osx_support/
├── Documentation/
│   ├── GETTING_STARTED.md           # Start here
│   ├── BUILD_FROM_SOURCE.md         # Build dependencies
│   ├── IMPLEMENTATION_PLAN.md       # Architecture
│   ├── MACOS_FIRST_CLASS_DESIGN.md  # Future vision
│   ├── PROJECT_SUMMARY.md           # Current status
│   └── DISTRIBUTION.md              # Packaging
│
├── sqlite_faiss_extension/          # C++ extension
│   ├── SQLiteFAISS.xcodeproj/
│   ├── Sources/
│   ├── Makefile
│   └── test_extension.sh
│
├── background_indexer/              # Swift daemon
│   ├── Sources/
│   ├── Package.swift
│   └── install.sh
│
├── FileSearchWorkspace.xcworkspace/ # Main workspace
├── build_all.sh                     # Build script
└── Makefile                         # Top-level build
```

## 🎨 Design Philosophy

### Current (Development)
- **Local testing** - No system installation
- **Build from source** - Full control over dependencies
- **Xcode native** - Proper macOS development
- **Zero Python** - Pure C++/Swift stack

### Future (Production)
- **Single .app bundle** - Drag-and-drop install
- **Menu bar app** - Native Mac experience
- **Embedded dependencies** - Self-contained
- **Sandboxed** - Proper security
- **App Store ready** - Professional quality

## 🔧 Development Workflow

```bash
# Open in Xcode
open FileSearchWorkspace.xcworkspace

# Or build from command line
./build_all.sh

# Test
cd sqlite_faiss_extension && make test

# Use locally (no installation)
sqlite3 test.db ".load ./faiss_extension.dylib"
```

## 📖 Key Concepts

### SQLite Extension
- Pure C++ library
- Loads from app bundle (no system install)
- Provides SQL functions: `faiss_search()`, `faiss_build_index()`
- Embeds FAISS for vector similarity

### Background Indexer
- Swift daemon
- FSEvents monitoring
- Low-priority, battery-aware
- XPC service (future)

### App Intents
- Siri integration
- Shortcuts support
- System-wide search

## 🎯 Goals

**Short-term (Current):**
- ✅ Prove C++ extension works
- ✅ Prove Swift indexer works
- ✅ Build system functional
- ⏳ Local testing complete

**Long-term (Future):**
- ⏳ Proper Mac app bundle
- ⏳ Menu bar interface
- ⏳ Siri integration
- ⏳ App Store distribution

## 🤝 Contributing

This is a learning project focused on:
- Native macOS development
- C++/Swift integration
- Proper app architecture
- Professional distribution

See individual documentation files for specific areas.

## 📝 License

See [LICENSE.txt](../LICENSE.txt) in project root.

---

**Start with:** [GETTING_STARTED.md](./GETTING_STARTED.md)  
**Questions?** Check [PROJECT_SUMMARY.md](./PROJECT_SUMMARY.md)  
**Vision?** Read [MACOS_FIRST_CLASS_DESIGN.md](./MACOS_FIRST_CLASS_DESIGN.md)
