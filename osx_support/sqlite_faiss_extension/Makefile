# Makefile for SQLite FAISS Extension

CXX = clang++
CXXFLAGS = -std=c++17 -fPIC -O3 -Wall
INCLUDES = -I/usr/local/include -I/opt/homebrew/include
LDFLAGS = -shared -L/usr/local/lib -L/opt/homebrew/lib
LIBS = -lfaiss -lsqlite3

TARGET = faiss_extension.dylib
SOURCES = Sources/faiss_extension.cpp Sources/onnx_encoder.cpp
OBJECTS = $(SOURCES:.cpp=.o)

.PHONY: all clean test install uninstall help

all: $(TARGET)

$(TARGET): $(OBJECTS)
	$(CXX) $(LDFLAGS) -o $@ $^ $(LIBS)

%.o: %.cpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) -c $< -o $@

clean:
	rm -f $(OBJECTS) $(TARGET) test_*.db

test: $(TARGET)
	@echo "Running tests with local extension..."
	./test_extension.sh

# Optional: Install system-wide (for distribution only)
install: $(TARGET)
	@echo "Installing to /usr/local/lib/sqlite3/..."
	@mkdir -p /usr/local/lib/sqlite3
	@cp $(TARGET) /usr/local/lib/sqlite3/
	@echo "✓ Installed to /usr/local/lib/sqlite3/$(TARGET)"
	@echo ""
	@echo "To uninstall: make uninstall"

# Uninstall system-wide installation
uninstall:
	@echo "Uninstalling from /usr/local/lib/sqlite3/..."
	@rm -f /usr/local/lib/sqlite3/$(TARGET)
	@echo "✓ Uninstalled"

help:
	@echo "SQLite FAISS Extension Build"
	@echo ""
	@echo "Targets:"
	@echo "  all        - Build extension (default)"
	@echo "  clean      - Remove build artifacts"
	@echo "  test       - Run test suite (uses local build)"
	@echo "  install    - Install to /usr/local/lib/sqlite3/ (optional)"
	@echo "  uninstall  - Remove system installation"
	@echo "  help       - Show this help"
	@echo ""
	@echo "Development workflow (no installation needed):"
	@echo "  make && make test"
	@echo "  sqlite3 test.db '.load ./faiss_extension.dylib'"
	@echo ""
	@echo "Prerequisites:"
	@echo "  See BUILD_FROM_SOURCE.md for building dependencies"
