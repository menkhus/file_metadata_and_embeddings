# Knowledge Graph - Structure for AI Alignment

Using SQLite as a Knowledge Graph to guide AI agent behavior.

## The Problem

**Without structure:**
```
User: "Find authentication code"
AI: Searches randomly, returns 100 results, no context
```

**With Knowledge Graph:**
```
User: "Find authentication code"
AI: 
1. Checks KG: "authentication" relates to "security", "login", "users"
2. Finds auth.py is central node
3. Follows edges to related files (login.js, user_model.py)
4. Returns structured answer with relationships
```

**KG provides guardrails and context!**

## SQLite as Knowledge Graph

### Schema Design

```sql
-- Nodes: Entities in your codebase
CREATE TABLE kg_nodes (
    id INTEGER PRIMARY KEY,
    node_type TEXT NOT NULL,  -- 'file', 'function', 'class', 'concept', 'module'
    name TEXT NOT NULL,
    file_path TEXT,
    chunk_id INTEGER,
    embedding BLOB,  -- For semantic similarity
    metadata TEXT,   -- JSON
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(node_type, name, file_path)
);

-- Edges: Relationships between entities
CREATE TABLE kg_edges (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    edge_type TEXT NOT NULL,  -- 'imports', 'calls', 'defines', 'similar_to', 'part_of'
    weight REAL DEFAULT 1.0,  -- Strength of relationship
    metadata TEXT,  -- JSON
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES kg_nodes(id),
    FOREIGN KEY (target_id) REFERENCES kg_nodes(id),
    UNIQUE(source_id, target_id, edge_type)
);

-- Concepts: High-level semantic concepts
CREATE TABLE kg_concepts (
    id INTEGER PRIMARY KEY,
    concept TEXT NOT NULL UNIQUE,  -- 'authentication', 'database', 'api'
    description TEXT,
    embedding BLOB,
    related_concepts TEXT,  -- JSON array
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Concept-Node mappings
CREATE TABLE kg_concept_nodes (
    concept_id INTEGER NOT NULL,
    node_id INTEGER NOT NULL,
    relevance REAL DEFAULT 1.0,  -- How relevant is this node to concept
    FOREIGN KEY (concept_id) REFERENCES kg_concepts(id),
    FOREIGN KEY (node_id) REFERENCES kg_nodes(id),
    PRIMARY KEY (concept_id, node_id)
);

-- Indexes for fast traversal
CREATE INDEX idx_kg_edges_source ON kg_edges(source_id, edge_type);
CREATE INDEX idx_kg_edges_target ON kg_edges(target_id, edge_type);
CREATE INDEX idx_kg_nodes_type ON kg_nodes(node_type);
CREATE INDEX idx_kg_concept_nodes_concept ON kg_concept_nodes(concept_id);
```

## Building the Knowledge Graph

### Step 1: Extract Entities (Nodes)

```python
#!/usr/bin/env python3
"""
build_knowledge_graph.py - Build KG from indexed files
"""

import sqlite3
import ast
import re
from pathlib import Path

class KnowledgeGraphBuilder:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
    
    def build_from_index(self):
        """Build KG from existing index"""
        print("Building Knowledge Graph...")
        
        # 1. Create file nodes
        self.create_file_nodes()
        
        # 2. Extract code entities (functions, classes)
        self.extract_code_entities()
        
        # 3. Extract relationships (imports, calls)
        self.extract_relationships()
        
        # 4. Extract concepts (semantic)
        self.extract_concepts()
        
        # 5. Link concepts to nodes
        self.link_concepts_to_nodes()
        
        print("Knowledge Graph built!")
    
    def create_file_nodes(self):
        """Create nodes for each file"""
        files = self.conn.execute("""
            SELECT DISTINCT file_path, file_type
            FROM text_chunks_v2
        """).fetchall()
        
        for file_path, file_type in files:
            self.conn.execute("""
                INSERT OR IGNORE INTO kg_nodes (node_type, name, file_path)
                VALUES ('file', ?, ?)
            """, (Path(file_path).name, file_path))
        
        self.conn.commit()
        print(f"Created {len(files)} file nodes")
    
    def extract_code_entities(self):
        """Extract functions, classes from Python files"""
        python_files = self.conn.execute("""
            SELECT DISTINCT file_path, 
                   json_extract(chunk_envelope, '$.content') as content
            FROM text_chunks_v2
            WHERE file_type = '.py'
        """).fetchall()
        
        for file_path, content in python_files:
            try:
                tree = ast.parse(content)
                
                # Extract functions
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        self.add_entity_node(
                            'function',
                            node.name,
                            file_path,
                            {'lineno': node.lineno}
                        )
                    
                    elif isinstance(node, ast.ClassDef):
                        self.add_entity_node(
                            'class',
                            node.name,
                            file_path,
                            {'lineno': node.lineno}
                        )
            except:
                pass  # Skip files with syntax errors
        
        self.conn.commit()
    
    def extract_relationships(self):
        """Extract relationships between entities"""
        # Imports
        self.extract_imports()
        
        # Function calls
        self.extract_calls()
        
        # Similarity (from embeddings)
        self.extract_similarity()
    
    def extract_imports(self):
        """Extract import relationships"""
        python_files = self.conn.execute("""
            SELECT DISTINCT file_path,
                   json_extract(chunk_envelope, '$.content') as content
            FROM text_chunks_v2
            WHERE file_type = '.py'
        """).fetchall()
        
        for file_path, content in python_files:
            # Find imports
            imports = re.findall(r'import\s+(\w+)', content)
            imports += re.findall(r'from\s+(\w+)\s+import', content)
            
            source_id = self.get_node_id('file', file_path)
            
            for imported in imports:
                # Try to find the imported file
                target_id = self.find_file_by_name(imported)
                if target_id:
                    self.add_edge(source_id, target_id, 'imports')
        
        self.conn.commit()
    
    def extract_concepts(self):
        """Extract high-level concepts using NLP"""
        # Common code concepts
        concepts = [
            ('authentication', 'User authentication and authorization'),
            ('database', 'Database operations and queries'),
            ('api', 'API endpoints and handlers'),
            ('error_handling', 'Error handling and exceptions'),
            ('logging', 'Logging and monitoring'),
            ('testing', 'Tests and test utilities'),
            ('configuration', 'Configuration and settings'),
            ('security', 'Security and encryption'),
            ('validation', 'Input validation'),
            ('caching', 'Caching mechanisms'),
        ]
        
        for concept, description in concepts:
            self.conn.execute("""
                INSERT OR IGNORE INTO kg_concepts (concept, description)
                VALUES (?, ?)
            """, (concept, description))
        
        self.conn.commit()
    
    def link_concepts_to_nodes(self):
        """Link concepts to relevant nodes using semantic search"""
        concepts = self.conn.execute("""
            SELECT id, concept FROM kg_concepts
        """).fetchall()
        
        for concept_id, concept in concepts:
            # Search for files related to this concept
            # (Using semantic search from our index)
            results = self.semantic_search(concept, limit=20)
            
            for file_path, score in results:
                node_id = self.get_node_id('file', file_path)
                if node_id:
                    self.conn.execute("""
                        INSERT OR IGNORE INTO kg_concept_nodes 
                        (concept_id, node_id, relevance)
                        VALUES (?, ?, ?)
                    """, (concept_id, node_id, score))
        
        self.conn.commit()
    
    def semantic_search(self, query, limit=20):
        """Search using existing semantic index"""
        # Use FAISS search from main system
        # Returns [(file_path, similarity_score), ...]
        pass  # Implementation uses existing search
    
    def add_entity_node(self, node_type, name, file_path, metadata):
        """Add an entity node"""
        self.conn.execute("""
            INSERT OR IGNORE INTO kg_nodes 
            (node_type, name, file_path, metadata)
            VALUES (?, ?, ?, ?)
        """, (node_type, name, file_path, json.dumps(metadata)))
    
    def add_edge(self, source_id, target_id, edge_type, weight=1.0):
        """Add an edge"""
        self.conn.execute("""
            INSERT OR IGNORE INTO kg_edges 
            (source_id, target_id, edge_type, weight)
            VALUES (?, ?, ?, ?)
        """, (source_id, target_id, edge_type, weight))
    
    def get_node_id(self, node_type, identifier):
        """Get node ID"""
        row = self.conn.execute("""
            SELECT id FROM kg_nodes
            WHERE node_type = ? AND (name = ? OR file_path = ?)
        """, (node_type, identifier, identifier)).fetchone()
        return row[0] if row else None
    
    def find_file_by_name(self, name):
        """Find file node by name"""
        row = self.conn.execute("""
            SELECT id FROM kg_nodes
            WHERE node_type = 'file' AND name LIKE ?
        """, (f'%{name}%',)).fetchone()
        return row[0] if row else None

if __name__ == "__main__":
    builder = KnowledgeGraphBuilder("file_metadata.db")
    builder.build_from_index()
```

## Querying the Knowledge Graph

### SQL Queries for Graph Traversal

```sql
-- Find all files related to a concept
SELECT n.file_path, cn.relevance
FROM kg_concepts c
JOIN kg_concept_nodes cn ON c.id = cn.concept_id
JOIN kg_nodes n ON cn.node_id = n.id
WHERE c.concept = 'authentication'
ORDER BY cn.relevance DESC
LIMIT 10;

-- Find what a file imports
SELECT target.name, target.file_path
FROM kg_nodes source
JOIN kg_edges e ON source.id = e.source_id
JOIN kg_nodes target ON e.target_id = target.id
WHERE source.file_path = '/path/to/file.py'
  AND e.edge_type = 'imports';

-- Find files that import a specific file
SELECT source.name, source.file_path
FROM kg_nodes target
JOIN kg_edges e ON target.id = e.target_id
JOIN kg_nodes source ON e.source_id = source.id
WHERE target.file_path = '/path/to/file.py'
  AND e.edge_type = 'imports';

-- Find related concepts
SELECT c2.concept, COUNT(*) as shared_files
FROM kg_concepts c1
JOIN kg_concept_nodes cn1 ON c1.id = cn1.concept_id
JOIN kg_concept_nodes cn2 ON cn1.node_id = cn2.node_id
JOIN kg_concepts c2 ON cn2.concept_id = c2.id
WHERE c1.concept = 'authentication'
  AND c2.concept != 'authentication'
GROUP BY c2.concept
ORDER BY shared_files DESC;

-- Find central files (most connections)
SELECT n.file_path, COUNT(*) as connection_count
FROM kg_nodes n
JOIN kg_edges e ON n.id = e.source_id OR n.id = e.target_id
WHERE n.node_type = 'file'
GROUP BY n.file_path
ORDER BY connection_count DESC
LIMIT 10;

-- Find shortest path between two files
WITH RECURSIVE path(source_id, target_id, path, depth) AS (
    SELECT source_id, target_id, 
           source_id || '->' || target_id as path,
           1 as depth
    FROM kg_edges
    WHERE source_id = ?  -- Start node
    
    UNION ALL
    
    SELECT p.source_id, e.target_id,
           p.path || '->' || e.target_id,
           p.depth + 1
    FROM path p
    JOIN kg_edges e ON p.target_id = e.source_id
    WHERE p.depth < 5  -- Max depth
      AND p.path NOT LIKE '%' || e.target_id || '%'  -- Avoid cycles
)
SELECT path, depth
FROM path
WHERE target_id = ?  -- End node
ORDER BY depth
LIMIT 1;
```

## App Intents with Knowledge Graph

### Enhanced Search Intent

```swift
struct KnowledgeGraphSearchIntent: AppIntent {
    static var title: LocalizedStringResource = "Knowledge Graph Search"
    
    static var description = IntentDescription(
        """
        Search using the knowledge graph for structured results.
        Understands relationships between files, concepts, and code entities.
        Returns results with context and connections.
        """,
        categoryName: "Knowledge Graph"
    )
    
    @Parameter(title: "Query")
    var query: String
    
    @Parameter(title: "Include relationships", default: true)
    var includeRelationships: Bool
    
    func perform() async throws -> some IntentResult & ReturnsValue<KGSearchResult> {
        // 1. Find relevant concept
        let concept = try await findConcept(query)
        
        // 2. Get files related to concept
        let files = try await getConceptFiles(concept)
        
        // 3. Get relationships between files
        let relationships = includeRelationships ? 
            try await getRelationships(files) : []
        
        // 4. Build structured result
        let result = KGSearchResult(
            concept: concept,
            files: files,
            relationships: relationships,
            centralFiles: findCentralFiles(files, relationships)
        )
        
        return .result(value: result)
    }
}

struct KGSearchResult: AppEntity {
    var id: String = UUID().uuidString
    var concept: String
    var files: [FileNode]
    var relationships: [Relationship]
    var centralFiles: [FileNode]  // Most connected files
    
    static var typeDisplayRepresentation = TypeDisplayRepresentation(
        name: "Knowledge Graph Result"
    )
    
    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(
            title: "Results for '\(concept)'",
            subtitle: "\(files.count) files, \(relationships.count) connections"
        )
    }
}
```

### Get Related Files Intent

```swift
struct GetRelatedFilesIntent: AppIntent {
    static var title: LocalizedStringResource = "Get Related Files"
    
    static var description = IntentDescription(
        """
        Get files related to a given file using the knowledge graph.
        Shows imports, dependencies, similar files, and shared concepts.
        """,
        categoryName: "Knowledge Graph"
    )
    
    @Parameter(title: "File path")
    var filePath: String
    
    @Parameter(title: "Relationship types")
    var relationshipTypes: [RelationType]
    
    func perform() async throws -> some IntentResult & ReturnsValue<[RelatedFile]> {
        let related = try await KnowledgeGraph.shared.getRelated(
            filePath: filePath,
            relationshipTypes: relationshipTypes
        )
        
        return .result(value: related)
    }
}

enum RelationType: String, AppEnum {
    case imports = "Imports"
    case importedBy = "Imported By"
    case similar = "Similar To"
    case sharedConcept = "Shared Concept"
    case calls = "Calls"
    case calledBy = "Called By"
    
    static var typeDisplayRepresentation = TypeDisplayRepresentation(
        name: "Relationship Type"
    )
    
    static var caseDisplayRepresentations: [RelationType: DisplayRepresentation] = [
        .imports: "Imports",
        .importedBy: "Imported By",
        .similar: "Similar To",
        .sharedConcept: "Shared Concept",
        .calls: "Calls",
        .calledBy: "Called By"
    ]
}
```

## AI Agent Guardrails

### Using KG to Guide AI

```swift
class AIGuardrails {
    func validateQuery(_ query: String) async -> QueryValidation {
        // 1. Check if query maps to known concepts
        let concepts = try? await findRelatedConcepts(query)
        
        if concepts.isEmpty {
            return .unknown(suggestion: "Try searching for: authentication, database, api")
        }
        
        // 2. Check if results would be meaningful
        let estimatedResults = try? await estimateResults(concepts)
        
        if estimatedResults == 0 {
            return .noResults(suggestion: "No files found for this concept")
        }
        
        if estimatedResults > 1000 {
            return .tooMany(suggestion: "Query too broad, try being more specific")
        }
        
        return .valid(concepts: concepts, estimatedResults: estimatedResults)
    }
    
    func suggestRelatedQueries(_ query: String) async -> [String] {
        // Use KG to suggest related queries
        let concept = try? await findConcept(query)
        let related = try? await getRelatedConcepts(concept)
        
        return related.map { $0.concept }
    }
    
    func explainResults(_ results: [SearchResult]) async -> String {
        // Use KG to explain why these results were returned
        let concepts = results.flatMap { $0.concepts }
        let relationships = try? await getRelationships(results.map { $0.filePath })
        
        return """
        Found \(results.count) files related to: \(concepts.joined(separator: ", "))
        
        Key files:
        - \(results[0].fileName): Central file with \(relationships.count) connections
        - \(results[1].fileName): Imports \(results[0].fileName)
        
        These files work together to implement \(concepts[0]).
        """
    }
}
```

## Visualization (Optional)

### Export for Visualization

```python
def export_graph_for_viz(db_path, output_file):
    """Export KG in format for visualization tools"""
    conn = sqlite3.connect(db_path)
    
    # Get nodes
    nodes = conn.execute("""
        SELECT id, node_type, name, file_path
        FROM kg_nodes
    """).fetchall()
    
    # Get edges
    edges = conn.execute("""
        SELECT source_id, target_id, edge_type, weight
        FROM kg_edges
    """).fetchall()
    
    # Export as JSON for D3.js or similar
    graph = {
        'nodes': [
            {'id': id, 'type': type, 'name': name, 'path': path}
            for id, type, name, path in nodes
        ],
        'edges': [
            {'source': src, 'target': tgt, 'type': type, 'weight': weight}
            for src, tgt, type, weight in edges
        ]
    }
    
    with open(output_file, 'w') as f:
        json.dump(graph, f, indent=2)
```

## Summary

**Knowledge Graph Benefits:**
- ✅ Structure for AI agents
- ✅ Guardrails (validate queries, suggest alternatives)
- ✅ Context (relationships between files)
- ✅ Explainability (why these results?)
- ✅ Discovery (find related concepts)

**Implementation:**
- ✅ SQLite tables (nodes, edges, concepts)
- ✅ Build from existing index
- ✅ Query with SQL (fast graph traversal)
- ✅ Expose via App Intents
- ✅ Use for AI guardrails

**This gives AI agents structure and context! 🎯**
