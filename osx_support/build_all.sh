#!/bin/bash
# Build all macOS native components

set -e

echo "Building macOS Native File Search System"
echo "========================================"
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Build SQLite Extension
echo -e "${BLUE}[1/2] Building SQLite FAISS Extension...${NC}"
cd sqlite_faiss_extension
make clean
make
echo -e "${GREEN}✓ SQLite extension built${NC}"
echo ""

# Build Background Indexer
echo -e "${BLUE}[2/2] Building Background Indexer...${NC}"
cd ../background_indexer
swift build -c release
echo -e "${GREEN}✓ Background indexer built${NC}"
echo ""

# Summary
echo "========================================"
echo -e "${GREEN}Build Complete!${NC}"
echo ""
echo "Products:"
echo "  • sqlite_faiss_extension/faiss_extension.dylib"
echo "  • background_indexer/.build/release/FileIndexer"
echo ""
echo "Next steps:"
echo "  1. Test:    cd sqlite_faiss_extension && ./test_extension.sh"
echo "  2. Install: sudo make install (in sqlite_faiss_extension/)"
echo "  3. Install: ./install.sh (in background_indexer/)"
echo ""
