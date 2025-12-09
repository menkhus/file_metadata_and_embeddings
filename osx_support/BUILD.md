# Build Instructions

Native macOS build using Xcode Command Line Tools and source-built dependencies.

**Philosophy:** "The Apple Way" - self-contained, statically linked, no runtime dependencies on Homebrew packages.

## Prerequisites

**Required:**
- macOS 13.0+ (Ventura or later)
- Xcode Command Line Tools
- ~2GB disk space for dependencies

**Install Command Line Tools:**
```bash
xcode-select --install
```

Verify:
```bash
clang --version
cmake --version
git --version
```

**Note:** You do NOT need the full Xcode IDE. Command Line Tools provide everything needed.

## Build Dependencies (One-Time Setup)

All dependencies are built from source and statically linked for self-contained distribution.

### 1. FAISS (Vector Similarity Search)

```bash
# Create build directory
mkdir -p ~/build_dependencies && cd ~/build_dependencies

# Clone FAISS
git clone https://github.com/facebookresearch/faiss.git
cd faiss

# Configure (no Python, no GPU)
cmake -B build \
  -DFAISS_ENABLE_PYTHON=OFF \
  -DFAISS_ENABLE_GPU=OFF \
  -DFAISS_ENABLE_C_API=ON \
  -DBUILD_SHARED_LIBS=OFF \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX=/usr/local

# Build (uses all CPU cores)
cmake --build build -j$(sysctl -n hw.ncpu)

# Install
sudo cmake --install build
```

**Result:** `/usr/local/lib/libfaiss.a` (static library)

### 2. Core ML Model (Embeddings)

Download and convert all-MiniLM-L6-v2 to Core ML format:

```bash
# Install Python tools (temporary, for conversion only)
pip3 install coremltools transformers torch

# Convert model
python3 << 'EOF'
import coremltools as ct
from transformers import AutoTokenizer, AutoModel
import torch

# Load model
model_name = "sentence-transformers/all-MiniLM-L6-v2"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModel.from_pretrained(model_name)

# Trace model
dummy_input = tokenizer("test", return_tensors="pt")
traced_model = torch.jit.trace(model, (dummy_input['input_ids'],))

# Convert to Core ML
mlmodel = ct.convert(
    traced_model,
    inputs=[ct.TensorType(shape=(1, ct.RangeDim(1, 512)), name="input_ids")]
)

# Save
mlmodel.save("MiniLM_L6_v2.mlmodel")
print("✓ Saved MiniLM_L6_v2.mlmodel")
EOF

# Move to project
mv MiniLM_L6_v2.mlmodel ~/src/osx_file_metadata_and_embeddings/models/
```

**Result:** `models/MiniLM_L6_v2.mlmodel` (Core ML model)

**Note:** Python only needed for one-time conversion. Runtime uses pure Core ML (Swift).

### 3. SQLite (Database)

SQLite is built into macOS. We only need to verify the version supports FTS5:

```bash
sqlite3 --version
# Should be 3.38+
```

If version is too old, build from source:

```bash
cd ~/build_dependencies
wget https://www.sqlite.org/2024/sqlite-autoconf-3450000.tar.gz
tar xzf sqlite-autoconf-3450000.tar.gz
cd sqlite-autoconf-3450000

./configure --prefix=/usr/local --enable-fts5
make -j$(sysctl -n hw.ncpu)
sudo make install
```

## Build Project

### Option 1: Command Line (Recommended for Development)

```bash
cd ~/src/osx_file_metadata_and_embeddings

# Build SQLite extension
cd sqlite_faiss_extension
make clean
make release

# Build background indexer
cd ../background_indexer
swift build -c release

# Verify builds
ls -lh ../sqlite_faiss_extension/faiss_extension.dylib
ls -lh .build/release/FileIndexer
```

### Option 2: Xcode (Recommended for GUI Development)

```bash
cd ~/src/osx_file_metadata_and_embeddings
open FileSearch.xcworkspace

# In Xcode:
# - Select scheme: "FileSearch" or component
# - Product > Build (⌘B)
# - Product > Run (⌘R) for testing
```

### Option 3: Build All

```bash
cd ~/src/osx_file_metadata_and_embeddings
./build_all.sh
```

Creates:
- `sqlite_faiss_extension/faiss_extension.dylib`
- `background_indexer/.build/release/FileIndexer`
- `FileSearch.app` (when GUI is implemented)

## Testing

### Test SQLite Extension

```bash
cd sqlite_faiss_extension
make test
```

Expected output:
```
✓ Extension loads
✓ faiss_build_index() works
✓ faiss_search() returns results
✓ Performance <100ms
```

### Test Background Indexer

```bash
cd background_indexer
swift test

# Or manual test
.build/release/FileIndexer \
  --database ~/test.db \
  --watch-paths "$HOME/Documents" \
  --once \
  --verbose
```

Expected output:
```
✓ Discovers files
✓ Generates embeddings
✓ Stores in database
✓ Memory usage <200MB
```

### Integration Test

```bash
# Index test files
cd background_indexer
.build/release/FileIndexer \
  --database ~/test.db \
  --watch-paths "$HOME/src/test_files" \
  --once

# Query with SQLite extension
cd ../sqlite_faiss_extension
sqlite3 ~/test.db << 'EOF'
.load ./faiss_extension.dylib
SELECT faiss_build_index();
SELECT * FROM faiss_search('authentication code', 5);
EOF
```

Expected: Ranked results for semantic query.

## Project Structure

```
osx_file_metadata_and_embeddings/
├── README.md
├── ARCHITECTURE.md
├── BUILD.md (this file)
├── REQUIREMENTS.md
├── STATUS.md
│
├── models/
│   └── MiniLM_L6_v2.mlmodel
│
├── sqlite_faiss_extension/
│   ├── Sources/
│   │   ├── faiss_extension.cpp
│   │   ├── onnx_encoder.cpp
│   │   └── onnx_encoder.h
│   ├── Makefile
│   └── test_extension.sh
│
├── background_indexer/
│   ├── Sources/
│   │   └── FileIndexer.swift
│   ├── Package.swift
│   └── install.sh
│
├── intents/
│   └── (not yet implemented)
│
├── FileSearch.xcworkspace/
└── build_all.sh
```

## Build Configuration

### Makefile (sqlite_faiss_extension/Makefile)

Key settings:
```make
# Static linking
LDFLAGS = -L/usr/local/lib -lfaiss -lblas -llapack

# Optimization
CXXFLAGS = -O3 -std=c++17

# Target
faiss_extension.dylib
```

### Swift Package (background_indexer/Package.swift)

```swift
// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "FileIndexer",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(url: "https://github.com/apple/swift-argument-parser", from: "1.2.0")
    ],
    targets: [
        .executableTarget(
            name: "FileIndexer",
            dependencies: [
                .product(name: "ArgumentParser", package: "swift-argument-parser")
            ]
        )
    ]
)
```

## Troubleshooting

### FAISS not found

**Error:** `ld: library not found for -lfaiss`

**Fix:**
```bash
# Verify FAISS installed
ls -la /usr/local/lib/libfaiss.a

# If missing, rebuild FAISS (see above)
# Update Makefile with correct path
```

### Core ML model not found

**Error:** `Model file not found: MiniLM_L6_v2.mlmodel`

**Fix:**
```bash
# Verify model exists
ls -la models/MiniLM_L6_v2.mlmodel

# If missing, reconvert (see above)
# Update code with correct path
```

### SQLite version too old

**Error:** `FTS5 extension not available`

**Fix:**
```bash
# Check version
sqlite3 --version

# If <3.38, build from source (see above)
```

### Xcode Command Line Tools not found

**Error:** `xcrun: error: invalid active developer path`

**Fix:**
```bash
sudo xcode-select --reset
xcode-select --install
```

## Advanced Build Options

### Static Linking

Force static linking of all dependencies:

```bash
cd sqlite_faiss_extension
make STATIC=1
```

### Debug Build

Build with debug symbols:

```bash
cd sqlite_faiss_extension
make debug

cd ../background_indexer
swift build -c debug
```

### Cross-Compilation

Build for different architectures:

```bash
# Apple Silicon only
cmake -B build -DCMAKE_OSX_ARCHITECTURES=arm64

# Intel only
cmake -B build -DCMAKE_OSX_ARCHITECTURES=x86_64

# Universal binary
cmake -B build -DCMAKE_OSX_ARCHITECTURES="arm64;x86_64"
```

## Distribution Build

For production .app bundle:

```bash
# Build release with code signing
xcodebuild -workspace FileSearch.xcworkspace \
  -scheme FileSearch \
  -configuration Release \
  CODE_SIGN_IDENTITY="Developer ID Application: Your Name" \
  clean build

# Create DMG
./scripts/create_dmg.sh
```

Result: `FileSearch.dmg` ready for distribution.

## Clean Build

Remove all build artifacts:

```bash
cd ~/src/osx_file_metadata_and_embeddings

# Clean SQLite extension
cd sqlite_faiss_extension
make clean

# Clean background indexer
cd ../background_indexer
swift package clean

# Clean Xcode build
rm -rf ~/Library/Developer/Xcode/DerivedData/FileSearch-*
```

## Continuous Integration

For automated builds:

```bash
# GitHub Actions / CI
./build_all.sh
./test_all.sh
```

Example `.github/workflows/build.yml`:
```yaml
name: Build
on: [push]
jobs:
  build:
    runs-on: macos-13
    steps:
      - uses: actions/checkout@v3
      - name: Install dependencies
        run: ./scripts/install_dependencies.sh
      - name: Build
        run: ./build_all.sh
      - name: Test
        run: ./test_all.sh
```

## Performance Tips

**Faster builds:**
```bash
# Use all CPU cores
make -j$(sysctl -n hw.ncpu)
swift build -c release -j$(sysctl -n hw.ncpu)
```

**Incremental builds:**
- Xcode automatically does incremental builds
- Command line: don't `make clean` unless necessary

**Cache dependencies:**
- FAISS build once, reuse
- Core ML model convert once

## Next Steps

After successful build:

1. **Test locally** - Verify all components work
2. **Index test files** - Run indexer on sample data
3. **Verify search** - Test semantic queries
4. **Implement Intents** - Add Apple Intents integration
5. **Package app** - Create .app bundle

See [STATUS.md](STATUS.md) for current implementation status.
