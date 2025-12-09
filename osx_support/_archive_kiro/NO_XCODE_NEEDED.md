# Building Without Xcode IDE

Complete guide to building everything with just command-line tools.

## What You Need

**Only this:**
```bash
xcode-select --install
```

This installs:
- `clang` (C/C++ compiler)
- `clang++` (C++ compiler)
- `make` (build tool)
- `git` (version control)
- `swift` (Swift compiler)
- `swiftc` (Swift compiler)

**You do NOT need:**
- ❌ Xcode.app (the IDE)
- ❌ Xcode project files (optional)
- ❌ Interface Builder
- ❌ Storyboards

## Build Everything

```bash
cd osx_support

# Build all components
./build_all.sh

# Or individually
cd sqlite_faiss_extension && make
cd ../background_indexer && swift build
```

## What About the .xcodeproj Files?

The Xcode project files are **optional** - they're there for people who prefer the IDE, but you can ignore them completely.

**Command-line build uses:**
- `Makefile` (for C++ extension)
- `Package.swift` (for Swift indexer)

**Xcode IDE uses:**
- `.xcodeproj` files
- `.xcworkspace` file

Both build the same code!

## Tools Comparison

### Command Line Tools (Minimal)
```bash
# What you get with xcode-select --install
/usr/bin/clang          # C compiler
/usr/bin/clang++        # C++ compiler
/usr/bin/swift          # Swift compiler
/usr/bin/swiftc         # Swift compiler
/usr/bin/make           # Build tool
/usr/bin/git            # Version control
/usr/bin/cmake          # Build system
```

**Size:** ~2 GB

### Full Xcode IDE (Optional)
```bash
# What you get with Xcode.app
/Applications/Xcode.app/
├── Contents/
│   ├── Developer/
│   │   └── usr/bin/      # Same tools as above
│   └── MacOS/
│       └── Xcode         # The IDE itself
```

**Size:** ~15 GB

**You only need the 2 GB version!**

## Build Process

### C++ Extension

```bash
cd sqlite_faiss_extension

# Makefile does this:
clang++ -std=c++17 -fPIC -O3 -Wall \
  -I/usr/local/include \
  -c Sources/faiss_extension.cpp -o Sources/faiss_extension.o

clang++ -shared \
  -L/usr/local/lib \
  -o faiss_extension.dylib \
  Sources/faiss_extension.o \
  -lfaiss -lsqlite3
```

**No Xcode IDE involved!**

### Swift Indexer

```bash
cd background_indexer

# Swift Package Manager does this:
swift build -c release

# Which runs:
swiftc -O \
  Sources/FileIndexer.swift \
  -o .build/release/FileIndexer
```

**No Xcode IDE involved!**

## Continuous Integration

Perfect for CI/CD pipelines:

```yaml
# .github/workflows/build.yml
name: Build
on: [push]
jobs:
  build:
    runs-on: macos-13
    steps:
      - uses: actions/checkout@v3
      
      - name: Install Command Line Tools
        run: xcode-select --install || true
      
      - name: Build
        run: |
          cd osx_support
          ./build_all.sh
      
      - name: Test
        run: |
          cd osx_support/sqlite_faiss_extension
          make test
```

**No Xcode IDE needed in CI!**

## Editor Recommendations

### Vim/Neovim
```bash
# Edit C++
vim sqlite_faiss_extension/Sources/faiss_extension.cpp

# Build
:!make

# Test
:!make test
```

### VS Code
```bash
# Install C++ and Swift extensions
code --install-extension ms-vscode.cpptools
code --install-extension swift-server.swift

# Open project
code osx_support/
```

### Sublime Text
```bash
# Edit and build
subl osx_support/

# Build system (Tools → Build System → New Build System)
{
    "cmd": ["make"],
    "working_dir": "$file_path",
    "file_regex": "^(..[^:]*):([0-9]+):?([0-9]+)?:? (.*)$"
}
```

### Emacs
```elisp
;; Edit C++
(find-file "sqlite_faiss_extension/Sources/faiss_extension.cpp")

;; Compile
(compile "make")
```

## Debugging Without Xcode

### LLDB (Command Line Debugger)

```bash
# Debug C++ extension
lldb sqlite3
(lldb) run test.db
sqlite> .load ./faiss_extension.dylib
sqlite> SELECT faiss_build_index();

# Set breakpoints
(lldb) breakpoint set --name faiss_build_index_func
(lldb) continue

# Inspect variables
(lldb) frame variable
(lldb) print my_variable
```

### Swift Debugging

```bash
# Debug Swift indexer
lldb .build/debug/FileIndexer
(lldb) run --once --verbose

# Set breakpoints
(lldb) breakpoint set --file FileIndexer.swift --line 42
(lldb) continue
```

## Why Command Line?

**Advantages:**
- ✅ Faster (no IDE overhead)
- ✅ Scriptable (automation)
- ✅ CI/CD friendly
- ✅ Works over SSH
- ✅ Less disk space (2 GB vs 15 GB)
- ✅ Faster builds (no indexing)
- ✅ Use your favorite editor

**When to use Xcode IDE:**
- GUI debugging
- Interface Builder
- Storyboards
- Asset catalogs
- Profiling tools

**For this project:** Command line is sufficient!

## Common Tasks

### Build
```bash
cd osx_support && ./build_all.sh
```

### Test
```bash
cd sqlite_faiss_extension && make test
cd background_indexer && swift test
```

### Clean
```bash
cd sqlite_faiss_extension && make clean
cd background_indexer && swift package clean
```

### Run
```bash
# Extension
sqlite3 test.db ".load ./sqlite_faiss_extension/faiss_extension.dylib"

# Indexer
./background_indexer/.build/release/FileIndexer --once --verbose
```

### Debug
```bash
lldb sqlite3
lldb .build/debug/FileIndexer
```

## Summary

**You need:**
- Command Line Tools (`xcode-select --install`)
- Text editor of choice
- Terminal

**You don't need:**
- Xcode.app (the IDE)
- 15 GB of disk space
- GUI tools

**Build with:**
- `make` (C++ extension)
- `swift build` (Swift indexer)
- `./build_all.sh` (everything)

**That's it!** Professional macOS development without the IDE bloat.
