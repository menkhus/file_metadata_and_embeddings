# Building from Source - Pure C++ Approach

Complete guide to building all dependencies from source without Homebrew.

## Philosophy

- **No Homebrew dependencies** - Build everything from official sources
- **Full control** - Know exactly what you're installing
- **Static linking** - Self-contained binaries
- **Reproducible** - Same build on any macOS system

## Prerequisites

Only Apple's tools (already on macOS):
- Xcode Command Line Tools: `xcode-select --install`
- That's it!

## Directory Structure

```bash
# Create build directory
mkdir -p ~/build_from_source
cd ~/build_from_source
```

We'll install everything to `/usr/local` (standard location).

## 1. Build OpenBLAS (FAISS dependency)

OpenBLAS provides optimized linear algebra operations.

```bash
# Clone source
git clone https://github.com/xianyi/OpenBLAS.git
cd OpenBLAS

# Build (uses Apple's clang)
make -j$(sysctl -n hw.ncpu)

# Install
sudo make PREFIX=/usr/local install

# Verify
ls -la /usr/local/lib/libopenblas.a
ls -la /usr/local/include/cblas.h

cd ..
```

**What this installs:**
- `/usr/local/lib/libopenblas.a` - Static library (pure C/Fortran)
- `/usr/local/include/` - Headers

## 2. Build FAISS (Core library)

FAISS is Facebook's similarity search library - pure C++.

```bash
# Clone source
git clone https://github.com/facebookresearch/faiss.git
cd faiss

# Configure with CMake (disable Python bindings)
cmake -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DFAISS_ENABLE_GPU=OFF \
  -DFAISS_ENABLE_PYTHON=OFF \
  -DBUILD_TESTING=OFF \
  -DBUILD_SHARED_LIBS=ON \
  -DCMAKE_INSTALL_PREFIX=/usr/local \
  -DCMAKE_OSX_ARCHITECTURES="arm64;x86_64"  # Universal binary

# Build
cmake --build build -j$(sysctl -n hw.ncpu)

# Install
sudo cmake --install build

# Verify
ls -la /usr/local/lib/libfaiss.dylib
ls -la /usr/local/include/faiss/

cd ..
```

**What this installs:**
- `/usr/local/lib/libfaiss.dylib` - Dynamic library (pure C++)
- `/usr/local/lib/libfaiss.a` - Static library (optional)
- `/usr/local/include/faiss/` - C++ headers

**No Python involved!**

## 3. SQLite (Already on macOS)

macOS includes SQLite, but if you want the latest:

```bash
# Download latest
curl -O https://www.sqlite.org/2024/sqlite-autoconf-3450000.tar.gz
tar xzf sqlite-autoconf-3450000.tar.gz
cd sqlite-autoconf-3450000

# Configure
./configure --prefix=/usr/local \
  --enable-json1 \
  --enable-fts5

# Build
make -j$(sysctl -n hw.ncpu)

# Install
sudo make install

# Verify
/usr/local/bin/sqlite3 --version

cd ..
```

**What this installs:**
- `/usr/local/lib/libsqlite3.a` - Static library (pure C)
- `/usr/local/include/sqlite3.h` - C header
- `/usr/local/bin/sqlite3` - CLI tool

## 4. ONNX Runtime (Optional - for text encoding)

ONNX Runtime enables ML model inference - pure C++.

```bash
# Clone source
git clone --recursive https://github.com/microsoft/onnxruntime.git
cd onnxruntime

# Build (minimal config, no Python)
./build.sh \
  --config Release \
  --build_shared_lib \
  --parallel $(sysctl -n hw.ncpu) \
  --skip_tests \
  --cmake_extra_defines \
    CMAKE_INSTALL_PREFIX=/usr/local \
    CMAKE_OSX_ARCHITECTURES="arm64;x86_64"

# Install
sudo cmake --install build/MacOS/Release

# Verify
ls -la /usr/local/lib/libonnxruntime.dylib
ls -la /usr/local/include/onnxruntime/

cd ..
```

**What this installs:**
- `/usr/local/lib/libonnxruntime.dylib` - Dynamic library (pure C++)
- `/usr/local/include/onnxruntime/` - C++ headers

## 5. Verify Installation

```bash
# Check all libraries
ls -la /usr/local/lib/libopenblas.a
ls -la /usr/local/lib/libfaiss.dylib
ls -la /usr/local/lib/libsqlite3.a
ls -la /usr/local/lib/libonnxruntime.dylib  # if installed

# Check headers
ls -la /usr/local/include/faiss/
ls -la /usr/local/include/sqlite3.h
ls -la /usr/local/include/onnxruntime/  # if installed

# Check library dependencies (should be minimal)
otool -L /usr/local/lib/libfaiss.dylib
```

Expected output for FAISS:
```
/usr/local/lib/libfaiss.dylib:
    /usr/local/lib/libfaiss.dylib
    /usr/local/lib/libopenblas.dylib
    /usr/lib/libc++.1.dylib
    /usr/lib/libSystem.B.dylib
```

**No Python dependencies!**

## 6. Build Your Project

Now build the SQLite extension:

```bash
cd /path/to/file_metadata_and_embeddings/osx_support/sqlite_faiss_extension

# Build with source-built libraries
make clean
make

# Test
./test_extension.sh

# Install
sudo make install
```

## Static Linking (Optional)

For a completely self-contained binary with no external dependencies:

### Update Makefile

Edit `osx_support/sqlite_faiss_extension/Makefile`:

```makefile
# Static linking configuration
LDFLAGS = -shared
LIBS = /usr/local/lib/libfaiss.a \
       /usr/local/lib/libopenblas.a \
       -lsqlite3 \
       -lc++

# This creates a self-contained .dylib with no external dependencies
```

### Build

```bash
make clean
make

# Verify no external dependencies (except system libs)
otool -L faiss_extension.dylib
```

Expected output:
```
faiss_extension.dylib:
    /usr/lib/libc++.1.dylib
    /usr/lib/libSystem.B.dylib
```

**Completely self-contained!**

## Troubleshooting

### "cmake: command not found"

CMake is needed for building. Get it from source:

```bash
curl -LO https://github.com/Kitware/CMake/releases/download/v3.28.1/cmake-3.28.1-macos-universal.tar.gz
tar xzf cmake-3.28.1-macos-universal.tar.gz
sudo cp -R cmake-3.28.1-macos-universal/CMake.app/Contents/ /Applications/CMake.app/Contents/
sudo ln -s /Applications/CMake.app/Contents/bin/cmake /usr/local/bin/cmake
```

Or use Xcode's cmake: `/Applications/Xcode.app/Contents/Developer/usr/bin/cmake`

### "Architecture mismatch"

Ensure you're building for your Mac's architecture:

```bash
# Check your architecture
uname -m
# arm64 = Apple Silicon (M1/M2/M3)
# x86_64 = Intel

# Build for your architecture only
cmake -DCMAKE_OSX_ARCHITECTURES="$(uname -m)" ...
```

### "Library not found"

Make sure `/usr/local/lib` is in your library path:

```bash
# Add to ~/.zshrc or ~/.bash_profile
export DYLD_LIBRARY_PATH=/usr/local/lib:$DYLD_LIBRARY_PATH
export LIBRARY_PATH=/usr/local/lib:$LIBRARY_PATH
export CPATH=/usr/local/include:$CPATH
```

## Build Times

On M1 MacBook Pro (8 cores):
- OpenBLAS: ~5 minutes
- FAISS: ~10 minutes
- SQLite: ~2 minutes
- ONNX Runtime: ~30 minutes (optional)

**Total: ~15-45 minutes** (one-time setup)

## Advantages of Building from Source

✅ **No Homebrew** - No package manager dependencies  
✅ **Full control** - Know exactly what's installed  
✅ **Latest versions** - Build from git main/master  
✅ **Optimized** - Built for your specific CPU  
✅ **Static linking** - Self-contained binaries  
✅ **Reproducible** - Same build anywhere  
✅ **No Python** - Pure C++ stack  

## Alternative: Vendored Dependencies

For even more control, vendor the dependencies in your project:

```bash
cd osx_support
mkdir -p vendor/{faiss,openblas,sqlite}

# Copy built libraries
cp /usr/local/lib/libfaiss.a vendor/faiss/
cp /usr/local/lib/libopenblas.a vendor/openblas/
cp -r /usr/local/include/faiss vendor/faiss/include

# Update Makefile to use vendored libs
INCLUDES = -I./vendor/faiss/include
LIBS = ./vendor/faiss/libfaiss.a ./vendor/openblas/libopenblas.a
```

Now your project is completely self-contained!

## Uninstall

To remove everything:

```bash
# Remove libraries
sudo rm -rf /usr/local/lib/libfaiss*
sudo rm -rf /usr/local/lib/libopenblas*
sudo rm -rf /usr/local/lib/libonnxruntime*

# Remove headers
sudo rm -rf /usr/local/include/faiss
sudo rm -rf /usr/local/include/onnxruntime

# Remove build directory
rm -rf ~/build_from_source
```

## Summary

You now have a **pure C++ stack** with:
- ✅ No Homebrew
- ✅ No Python
- ✅ Full source control
- ✅ Optimized for your Mac
- ✅ Self-contained binaries

Build your SQLite extension with confidence knowing exactly what's in your dependencies!

## See Also

- [FAISS Build Instructions](https://github.com/facebookresearch/faiss/blob/main/INSTALL.md)
- [OpenBLAS Build Guide](https://github.com/xianyi/OpenBLAS/wiki/Installation-Guide)
- [SQLite Compilation](https://www.sqlite.org/howtocompile.html)
- [ONNX Runtime Build](https://onnxruntime.ai/docs/build/)
