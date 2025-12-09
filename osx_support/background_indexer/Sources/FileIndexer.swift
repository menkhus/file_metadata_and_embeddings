import Foundation
import ArgumentParser

@main
struct FileIndexer: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "fileindexer",
        abstract: "Background file indexer for semantic search",
        version: "1.0.0"
    )
    
    @Option(name: .long, help: "Database path")
    var database: String = NSHomeDirectory() + "/Library/Application Support/FileSearch/file_metadata.db"
    
    @Option(name: .long, help: "Watch directories (comma-separated)")
    var watchPaths: String = ""
    
    @Flag(name: .long, help: "Run once and exit (no daemon mode)")
    var once: Bool = false
    
    @Flag(name: .long, help: "Verbose logging")
    var verbose: Bool = false
    
    mutating func run() async throws {
        print("FileIndexer starting...")
        print("Database: \(database)")
        
        let config = IndexerConfig(
            databasePath: database,
            watchPaths: parseWatchPaths(),
            verbose: verbose
        )
        
        let indexer = BackgroundIndexer(config: config)
        
        if once {
            try await indexer.indexOnce()
        } else {
            try await indexer.startDaemon()
        }
    }
    
    private func parseWatchPaths() -> [String] {
        if watchPaths.isEmpty {
            return [
                NSHomeDirectory() + "/Documents",
                NSHomeDirectory() + "/src",
                NSHomeDirectory() + "/Desktop"
            ]
        }
        return watchPaths.split(separator: ",").map { String($0).trimmingCharacters(in: .whitespaces) }
    }
}

struct IndexerConfig {
    let databasePath: String
    let watchPaths: [String]
    let verbose: Bool
    let maxFilesPerBatch: Int = 10
    let idleThresholdSeconds: TimeInterval = 300
    let maxMemoryMB: Int = 200
    let batteryThreshold: Double = 0.20
}

class BackgroundIndexer {
    private let config: IndexerConfig
    private var isRunning = false
    
    init(config: IndexerConfig) {
        self.config = config
    }
    
    func startDaemon() async throws {
        print("Starting daemon mode...")
        isRunning = true
        
        // Setup signal handlers
        signal(SIGTERM) { _ in
            print("Received SIGTERM, shutting down...")
            exit(0)
        }
        
        signal(SIGINT) { _ in
            print("Received SIGINT, shutting down...")
            exit(0)
        }
        
        // Main loop
        while isRunning {
            if shouldProcess() {
                try await processFiles()
            }
            
            // Sleep for 60 seconds
            try await Task.sleep(nanoseconds: 60_000_000_000)
        }
    }
    
    func indexOnce() async throws {
        print("Running one-time indexing...")
        try await processFiles()
        print("Indexing complete.")
    }
    
    private func shouldProcess() -> Bool {
        // Check battery level
        if let batteryLevel = getBatteryLevel(), batteryLevel < config.batteryThreshold {
            if config.verbose {
                print("Battery too low (\(Int(batteryLevel * 100))%), skipping...")
            }
            return false
        }
        
        // Check system idle time
        let idleTime = getSystemIdleTime()
        if idleTime < config.idleThresholdSeconds {
            if config.verbose {
                print("System not idle enough (\(Int(idleTime))s), skipping...")
            }
            return false
        }
        
        return true
    }
    
    private func processFiles() async throws {
        print("Processing files...")
        
        // TODO: Implement file discovery and processing
        // 1. Scan watch directories
        // 2. Find new/modified files
        // 3. Chunk files
        // 4. Generate embeddings
        // 5. Store in database
        
        // Stub implementation
        for watchPath in config.watchPaths {
            if config.verbose {
                print("Scanning: \(watchPath)")
            }
            
            // Process up to maxFilesPerBatch files
            let files = try discoverFiles(in: watchPath)
            let batch = Array(files.prefix(config.maxFilesPerBatch))
            
            for file in batch {
                if config.verbose {
                    print("  Processing: \(file)")
                }
                // TODO: Process file
            }
        }
    }
    
    private func discoverFiles(in path: String) throws -> [String] {
        let fileManager = FileManager.default
        var files: [String] = []
        
        guard let enumerator = fileManager.enumerator(atPath: path) else {
            return files
        }
        
        for case let file as String in enumerator {
            let fullPath = (path as NSString).appendingPathComponent(file)
            
            // Skip hidden files and directories
            if file.hasPrefix(".") {
                continue
            }
            
            // Only process text files
            let ext = (file as NSString).pathExtension.lowercased()
            if ["py", "js", "ts", "swift", "c", "cpp", "h", "md", "txt"].contains(ext) {
                files.append(fullPath)
            }
        }
        
        return files
    }
    
    private func getBatteryLevel() -> Double? {
        // TODO: Implement battery level check using IOKit
        return 1.0 // Stub: assume full battery
    }
    
    private func getSystemIdleTime() -> TimeInterval {
        // TODO: Implement system idle time check
        return 600.0 // Stub: assume idle
    }
}
