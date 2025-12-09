# Top-level Makefile for macOS Native File Search

.PHONY: all clean install test help

all:
	@echo "Building all components..."
	@./build_all.sh

clean:
	@echo "Cleaning all components..."
	@cd sqlite_faiss_extension && make clean
	@cd background_indexer && swift package clean

install:
	@echo "Installing all components..."
	@cd sqlite_faiss_extension && sudo make install
	@cd background_indexer && ./install.sh

test:
	@echo "Testing all components..."
	@cd sqlite_faiss_extension && ./test_extension.sh
	@cd background_indexer && swift test

help:
	@echo "macOS Native File Search - Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all      - Build all components (default)"
	@echo "  clean    - Clean all build artifacts"
	@echo "  install  - Install all components"
	@echo "  test     - Run all tests"
	@echo "  help     - Show this help"
	@echo ""
	@echo "Components:"
	@echo "  • SQLite FAISS Extension (C++)"
	@echo "  • Background Indexer (Swift)"
	@echo ""
	@echo "Prerequisites:"
	@echo "  brew install faiss sqlite onnxruntime"
	@echo "  xcode-select --install"
