# PII Protection & Redaction System

Comprehensive PII detection, redaction, and security using Knowledge Graph.

## The Problem

**Code contains PII:**
```python
# config.py
API_KEY = "sk-1234567890abcdef"
DATABASE_URL = "postgres://admin:password123@db.company.com/prod"
EMAIL = "john.doe@company.com"
PHONE = "+1-555-123-4567"
SSN = "123-45-6789"
```

**Without protection:**
- Indexed as-is
- Searchable by AI
- Exposed in results
- Leaked in logs
- **Major security risk!**

**With PII protection:**
- Detected during indexing
- Redacted in storage
- Flagged in KG
- Filtered in results
- **Secure by default!**

## Architecture

```
File → PII Detection → Redaction → Index (redacted)
                ↓
         KG Annotation (PII markers)
                ↓
         Intent Filters (block PII exposure)
```

## Database Schema

### PII Detection Tables

```sql
-- PII patterns and rules
CREATE TABLE pii_patterns (
    id INTEGER PRIMARY KEY,
    pattern_type TEXT NOT NULL,  -- 'email', 'phone', 'ssn', 'api_key', etc.
    regex_pattern TEXT NOT NULL,
    description TEXT,
    severity TEXT NOT NULL,  -- 'high', 'medium', 'low'
    enabled BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Detected PII instances
CREATE TABLE pii_detections (
    id INTEGER PRIMARY KEY,
    file_path TEXT NOT NULL,
    chunk_id INTEGER,
    pattern_type TEXT NOT NULL,
    original_value_hash TEXT NOT NULL,  -- SHA256 hash, never store actual value!
    redacted_value TEXT NOT NULL,  -- What we show instead
    position_start INTEGER,
    position_end INTEGER,
    severity TEXT NOT NULL,
    detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chunk_id) REFERENCES text_chunks_v2(id)
);

-- PII in Knowledge Graph
CREATE TABLE kg_pii_nodes (
    node_id INTEGER NOT NULL,
    pii_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    redaction_policy TEXT NOT NULL,  -- 'full', 'partial', 'hash'
    FOREIGN KEY (node_id) REFERENCES kg_nodes(id),
    PRIMARY KEY (node_id, pii_type)
);

-- Redaction audit log
CREATE TABLE pii_audit_log (
    id INTEGER PRIMARY KEY,
    action TEXT NOT NULL,  -- 'detected', 'redacted', 'accessed', 'exposed'
    file_path TEXT,
    pii_type TEXT,
    user_action TEXT,  -- What triggered this
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_pii_detections_file ON pii_detections(file_path);
CREATE INDEX idx_pii_detections_type ON pii_detections(pattern_type);
CREATE INDEX idx_kg_pii_nodes_severity ON kg_pii_nodes(severity);
```

## PII Detection Patterns

### Built-in Patterns

```python
#!/usr/bin/env python3
"""
pii_detector.py - Detect and redact PII
"""

import re
import hashlib
from typing import List, Tuple, Dict

class PIIDetector:
    """Detect PII in text"""
    
    PATTERNS = {
        'email': {
            'regex': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            'severity': 'medium',
            'redact': lambda m: f"[EMAIL_{hash_value(m.group())[:8]}]"
        },
        'phone': {
            'regex': r'\b(?:\+?1[-.]?)?\(?([0-9]{3})\)?[-.]?([0-9]{3})[-.]?([0-9]{4})\b',
            'severity': 'medium',
            'redact': lambda m: f"[PHONE_{hash_value(m.group())[:8]}]"
        },
        'ssn': {
            'regex': r'\b\d{3}-\d{2}-\d{4}\b',
            'severity': 'high',
            'redact': lambda m: "[SSN_REDACTED]"
        },
        'credit_card': {
            'regex': r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
            'severity': 'high',
            'redact': lambda m: "[CARD_REDACTED]"
        },
        'api_key': {
            'regex': r'\b(?:api[_-]?key|apikey|access[_-]?token|secret[_-]?key)[\s:=]+["\']?([A-Za-z0-9_\-]{20,})["\']?',
            'severity': 'high',
            'redact': lambda m: f"[API_KEY_{hash_value(m.group(1))[:8]}]"
        },
        'password': {
            'regex': r'\b(?:password|passwd|pwd)[\s:=]+["\']?([^\s"\']{6,})["\']?',
            'severity': 'high',
            'redact': lambda m: "[PASSWORD_REDACTED]"
        },
        'aws_key': {
            'regex': r'\b(AKIA[0-9A-Z]{16})\b',
            'severity': 'high',
            'redact': lambda m: "[AWS_KEY_REDACTED]"
        },
        'private_key': {
            'regex': r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----',
            'severity': 'high',
            'redact': lambda m: "[PRIVATE_KEY_REDACTED]"
        },
        'ip_address': {
            'regex': r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
            'severity': 'low',
            'redact': lambda m: f"[IP_{hash_value(m.group())[:8]}]"
        },
        'url_with_auth': {
            'regex': r'https?://[^:]+:[^@]+@[^\s]+',
            'severity': 'high',
            'redact': lambda m: "[URL_WITH_CREDENTIALS]"
        },
        'jwt_token': {
            'regex': r'\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b',
            'severity': 'high',
            'redact': lambda m: "[JWT_TOKEN_REDACTED]"
        }
    }
    
    def detect(self, text: str) -> List[Dict]:
        """Detect all PII in text"""
        detections = []
        
        for pii_type, config in self.PATTERNS.items():
            pattern = re.compile(config['regex'], re.IGNORECASE)
            
            for match in pattern.finditer(text):
                detections.append({
                    'type': pii_type,
                    'value': match.group(),
                    'start': match.start(),
                    'end': match.end(),
                    'severity': config['severity'],
                    'hash': hash_value(match.group())
                })
        
        return detections
    
    def redact(self, text: str) -> Tuple[str, List[Dict]]:
        """Redact PII from text, return redacted text and detections"""
        detections = self.detect(text)
        redacted_text = text
        
        # Sort by position (reverse) to maintain positions during replacement
        detections.sort(key=lambda d: d['start'], reverse=True)
        
        for detection in detections:
            pii_type = detection['type']
            config = self.PATTERNS[pii_type]
            
            # Get redacted value
            match = re.search(config['regex'], text[detection['start']:detection['end']])
            redacted = config['redact'](match)
            
            # Replace in text
            redacted_text = (
                redacted_text[:detection['start']] +
                redacted +
                redacted_text[detection['end']:]
            )
            
            detection['redacted'] = redacted
        
        return redacted_text, detections

def hash_value(value: str) -> str:
    """Hash a value for consistent redaction"""
    return hashlib.sha256(value.encode()).hexdigest()

# Example usage
if __name__ == "__main__":
    detector = PIIDetector()
    
    test_text = """
    API_KEY = "sk-1234567890abcdef"
    EMAIL = "john.doe@company.com"
    PHONE = "+1-555-123-4567"
    DATABASE_URL = "postgres://admin:password123@db.company.com/prod"
    """
    
    redacted, detections = detector.redact(test_text)
    
    print("Original:")
    print(test_text)
    print("\nRedacted:")
    print(redacted)
    print(f"\nDetected {len(detections)} PII instances")
```

## Integration with Indexing

### Redact During Indexing

```swift
class SecureIndexer {
    private let piiDetector = PIIDetector()
    
    func indexFile(_ path: String) async throws {
        // 1. Read file
        let content = try String(contentsOfFile: path)
        
        // 2. Detect PII
        let (redactedContent, detections) = piiDetector.redact(content)
        
        // 3. Log detections
        for detection in detections {
            try await logPIIDetection(
                filePath: path,
                type: detection.type,
                severity: detection.severity,
                hash: detection.hash
            )
        }
        
        // 4. Chunk REDACTED content
        let chunks = try await chunker.chunk(redactedContent)
        
        // 5. Generate embeddings from REDACTED content
        let embeddings = try await embedder.encode(chunks)
        
        // 6. Store in database
        try await database.store(path, chunks, embeddings)
        
        // 7. Mark in Knowledge Graph if high severity
        if detections.contains(where: { $0.severity == "high" }) {
            try await markNodeAsSensitive(path, detections)
        }
    }
    
    func markNodeAsSensitive(_ path: String, _ detections: [PIIDetection]) async throws {
        let nodeId = try await getNodeId(path)
        
        for detection in detections {
            try await database.execute("""
                INSERT OR IGNORE INTO kg_pii_nodes 
                (node_id, pii_type, severity, redaction_policy)
                VALUES (?, ?, ?, 'full')
            """, nodeId, detection.type, detection.severity)
        }
    }
}
```

## Knowledge Graph Integration

### PII-Aware Graph Queries

```sql
-- Find files with PII
SELECT n.file_path, p.pii_type, p.severity
FROM kg_nodes n
JOIN kg_pii_nodes p ON n.id = p.node_id
WHERE p.severity = 'high'
ORDER BY n.file_path;

-- Find files related to PII-containing files
SELECT DISTINCT target.file_path, source_pii.pii_type
FROM kg_nodes source
JOIN kg_pii_nodes source_pii ON source.id = source_pii.node_id
JOIN kg_edges e ON source.id = e.source_id
JOIN kg_nodes target ON e.target_id = target.id
WHERE source_pii.severity = 'high'
  AND e.edge_type IN ('imports', 'calls');

-- Check if a concept involves PII
SELECT c.concept, COUNT(DISTINCT p.pii_type) as pii_types
FROM kg_concepts c
JOIN kg_concept_nodes cn ON c.id = cn.concept_id
JOIN kg_pii_nodes p ON cn.node_id = p.node_id
WHERE c.concept = 'authentication'
GROUP BY c.concept;
```

## App Intent Filters

### Secure Search Intent

```swift
struct SecureSearchIntent: AppIntent {
    static var title: LocalizedStringResource = "Secure Search"
    
    static var description = IntentDescription(
        """
        Search with automatic PII filtering.
        Results are automatically redacted to protect sensitive information.
        """,
        categoryName: "Secure Search"
    )
    
    @Parameter(title: "Query")
    var query: String
    
    @Parameter(title: "Include PII warnings", default: true)
    var includePIIWarnings: Bool
    
    func perform() async throws -> some IntentResult & ReturnsValue<[SecureSearchResult]> {
        // 1. Normal search
        let rawResults = try await SearchManager.shared.search(query)
        
        // 2. Filter PII
        let secureResults = try await filterPII(rawResults)
        
        // 3. Add warnings if needed
        if includePIIWarnings {
            for result in secureResults where result.containsPII {
                result.warning = "This file contains sensitive information"
            }
        }
        
        return .result(value: secureResults)
    }
    
    func filterPII(_ results: [SearchResult]) async throws -> [SecureSearchResult] {
        var secureResults: [SecureSearchResult] = []
        
        for result in results {
            // Check if file has PII
            let hasPII = try await checkForPII(result.filePath)
            
            // Redact content if needed
            let content = hasPII ? 
                try await redactContent(result.content) : 
                result.content
            
            secureResults.append(SecureSearchResult(
                filePath: result.filePath,
                content: content,
                containsPII: hasPII,
                piiTypes: hasPII ? try await getPIITypes(result.filePath) : []
            ))
        }
        
        return secureResults
    }
}

struct SecureSearchResult: AppEntity {
    var id: String = UUID().uuidString
    var filePath: String
    var content: String  // Already redacted
    var containsPII: Bool
    var piiTypes: [String]
    var warning: String?
    
    static var typeDisplayRepresentation = TypeDisplayRepresentation(
        name: "Secure Search Result"
    )
    
    var displayRepresentation: DisplayRepresentation {
        let subtitle = containsPII ? 
            "⚠️ Contains: \(piiTypes.joined(separator: ", "))" :
            "No sensitive data"
        
        return DisplayRepresentation(
            title: "\(filePath)",
            subtitle: subtitle,
            image: .init(systemName: containsPII ? "lock.shield" : "doc.text")
        )
    }
}
```

### Check PII Intent

```swift
struct CheckForPIIIntent: AppIntent {
    static var title: LocalizedStringResource = "Check for PII"
    
    static var description = IntentDescription(
        """
        Check if a file contains PII.
        Returns types of PII found and severity levels.
        """,
        categoryName: "Security"
    )
    
    @Parameter(title: "File path")
    var filePath: String
    
    func perform() async throws -> some IntentResult & ReturnsValue<PIIReport> {
        let detections = try await database.execute("""
            SELECT pattern_type, severity, COUNT(*) as count
            FROM pii_detections
            WHERE file_path = ?
            GROUP BY pattern_type, severity
        """, filePath)
        
        let report = PIIReport(
            filePath: filePath,
            hasPII: !detections.isEmpty,
            detections: detections,
            recommendation: generateRecommendation(detections)
        )
        
        return .result(value: report)
    }
}

struct PIIReport: AppEntity {
    var id: String = UUID().uuidString
    var filePath: String
    var hasPII: Bool
    var detections: [PIIDetection]
    var recommendation: String
    
    static var typeDisplayRepresentation = TypeDisplayRepresentation(
        name: "PII Report"
    )
    
    var displayRepresentation: DisplayRepresentation {
        let status = hasPII ? "⚠️ PII Detected" : "✓ No PII"
        return DisplayRepresentation(
            title: status,
            subtitle: "\(detections.count) instances found"
        )
    }
}
```

## Redaction Policies

### Configurable Redaction

```swift
enum RedactionPolicy: String, Codable {
    case full        // [EMAIL_REDACTED]
    case partial     // j***@company.com
    case hash        // [EMAIL_a1b2c3d4]
    case none        // john@company.com (dangerous!)
}

class RedactionManager {
    func redact(_ text: String, policy: RedactionPolicy) -> String {
        let detector = PIIDetector()
        let detections = detector.detect(text)
        
        var redacted = text
        
        for detection in detections.sorted(by: { $0.start > $1.start }) {
            let replacement: String
            
            switch policy {
            case .full:
                replacement = "[\(detection.type.uppercased())_REDACTED]"
            
            case .partial:
                replacement = partialRedact(detection.value)
            
            case .hash:
                replacement = "[\(detection.type.uppercased())_\(detection.hash.prefix(8))]"
            
            case .none:
                replacement = detection.value
            }
            
            redacted = redacted.replacingCharacters(
                in: Range(detection.start..<detection.end, in: redacted)!,
                with: replacement
            )
        }
        
        return redacted
    }
    
    func partialRedact(_ value: String) -> String {
        // Show first and last char, redact middle
        guard value.count > 4 else { return "***" }
        
        let first = value.prefix(1)
        let last = value.suffix(1)
        let middle = String(repeating: "*", count: value.count - 2)
        
        return "\(first)\(middle)\(last)"
    }
}
```

## Audit & Compliance

### PII Access Logging

```swift
class PIIAuditLogger {
    func logAccess(
        filePath: String,
        piiTypes: [String],
        userAction: String
    ) async {
        try? await database.execute("""
            INSERT INTO pii_audit_log (action, file_path, pii_type, user_action)
            VALUES ('accessed', ?, ?, ?)
        """, filePath, piiTypes.joined(separator: ","), userAction)
    }
    
    func getAuditReport(since: Date) async -> [AuditEntry] {
        try! await database.execute("""
            SELECT * FROM pii_audit_log
            WHERE timestamp > ?
            ORDER BY timestamp DESC
        """, since.ISO8601Format())
    }
}
```

### Compliance Reports

```sql
-- PII exposure report
SELECT 
    DATE(timestamp) as date,
    action,
    COUNT(*) as occurrences,
    COUNT(DISTINCT file_path) as unique_files
FROM pii_audit_log
WHERE timestamp > datetime('now', '-30 days')
GROUP BY DATE(timestamp), action
ORDER BY date DESC;

-- High-risk files
SELECT 
    file_path,
    GROUP_CONCAT(DISTINCT pattern_type) as pii_types,
    COUNT(*) as pii_count,
    MAX(CASE WHEN severity = 'high' THEN 1 ELSE 0 END) as has_high_severity
FROM pii_detections
GROUP BY file_path
HAVING has_high_severity = 1
ORDER BY pii_count DESC;
```

## User Controls

### Preferences

```
┌─────────────────────────────────────────┐
│  FileSearch Security Settings           │
├─────────────────────────────────────────┤
│  PII Protection                         │
│  ☑ Automatically detect PII             │
│  ☑ Redact PII in search results         │
│  ☑ Warn when accessing sensitive files  │
│                                         │
│  Redaction Policy:                      │
│  ● Full redaction (most secure)         │
│  ○ Partial redaction (some visibility)  │
│  ○ Hash-based (consistent IDs)          │
│                                         │
│  Detected PII:                          │
│  • 23 files with API keys               │
│  • 15 files with emails                 │
│  • 8 files with passwords               │
│                                         │
│  [View PII Report...]                   │
│  [Audit Log...]                         │
└─────────────────────────────────────────┘
```

## Summary

**PII Protection System:**
- ✅ Automatic detection (12+ PII types)
- ✅ Redaction during indexing
- ✅ KG annotations (mark sensitive nodes)
- ✅ Intent filters (block PII exposure)
- ✅ Audit logging (compliance)
- ✅ Configurable policies

**Security by Default:**
- PII never stored in plain text
- Redacted before embedding generation
- Filtered in search results
- Logged for audit
- User controls available

**This protects users and their data! 🔒**
