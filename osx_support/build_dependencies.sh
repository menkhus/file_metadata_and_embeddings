#!/bin/bash
# build_dependencies.sh - Build FAISS from source (no Homebrew)

set -e

PREFIX="/usr/local"
JOBS=$(sysctl -n hw.ncpu)

echo "========================================"
echo "Building FAISS from Source"
echo "========================================"
echo "Prefix: $PREFIX"
echo "Jobs: $JOBS"
echo "Using: Apple Accelerate framework"
echo ""

# Check for Xcode Command Line Tools
if ! xcode-select -p &>/dev/null; then
    echo "Error: Xcode Command Line Tools not found"
    echo "Install with: xcode-select --install"
    exit 1
fi

# Check for CMake
if ! command -v cmake &>/dev/null; then
    echo "Error: CMake not found"
    echo ""
    echo "Install options:"
    echo "  1. brew install cmake"
    echo "  2. Download from: https://cmake.org/download/"
    echo "  3. Build from source (see BUILD_FROM_SOURCE.md)"
    exit 1
fi

echo "✓ Xcode Command Line Tools found"
echo "✓ CMake found: $(cmake --version | head -1)"
echo ""

# Clone FAISS if needed
if [ ! -d "faiss" ]; then
    echo "Cloning FAISS..."
    git clone https://github.com/facebookresearch/faiss.git
    echo "✓ FAISS cloned"
else
    echo "✓ FAISS directory exists"
fi

cd faiss

# Configure
echo ""
echo "Configuring FAISS..."
cmake -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DFAISS_ENABLE_GPU=OFF \
  -DFAISS_ENABLE_PYTHON=OFF \
  -DBUILD_TESTING=OFF \
  -DBUILD_SHARED_LIBS=ON \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DBLA_VENDOR=Apple

echo "✓ Configuration complete"

# Build
echo ""
echo "Building FAISS (this may take a few minutes)..."
cmake --build build -j$JOBS

echo "✓ Build complete"

# Install
echo ""
echo "Installing to $PREFIX (requires sudo)..."
sudo cmake --install build

echo ""
echo "========================================"
echo "✓ FAISS installed successfully!"
echo "========================================"
echo ""
echo "Installed files:"
echo "  Library: $PREFIX/lib/libfaiss.dylib"
echo "  Headers: $PREFIX/include/faiss/"
echo ""
echo "Verify installation:"
echo "  ls -la $PREFIX/lib/libfaiss.dylib"
echo "  ls -la $PREFIX/include/faiss/"
echo ""
echo "Next steps:"
echo "  1. cd ../sqlite_faiss_extension"
echo "  2. make"
echo "  3. ./test_extension.sh"
echo ""
