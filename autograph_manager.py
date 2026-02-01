#!/usr/bin/env python3
"""
autograph_manager.py - Knowledge Graph Manager for Grounding Autographs

Manages the autograph knowledge graph that learns from user grounding choices.
Each grounding decision creates an "autograph" - a signature linking context to sources.

Design Principles:
- CSV storage for human readability and git-friendliness
- Embeddings for semantic similarity (reuses existing FAISS infrastructure)
- Low friction: learns from normal grounding workflow
- Graceful degradation: works without embeddings, better with them
"""

import csv
import json
import hashlib
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path

# Optional: sentence-transformers for embeddings
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    print("Warning: sentence-transformers not available. Semantic search disabled.", flush=True)


@dataclass
class KnowledgeNode:
    """A node in the knowledge graph (context, file, concept, etc.)"""
    node_id: str
    node_type: str  # context, file, concept, session, web
    label: str
    embedding_id: Optional[str] = None
    created: str = ""
    last_seen: str = ""
    metadata: str = "{}"

    def __post_init__(self):
        if not self.created:
            self.created = datetime.utcnow().isoformat() + "Z"
        if not self.last_seen:
            self.last_seen = self.created


@dataclass
class KnowledgeEdge:
    """An edge in the knowledge graph (autograph entry)"""
    timestamp: str
    source_node: str
    edge_type: str  # accepted, rejected, ignored, discusses
    target_node: str
    weight: float
    context_summary: str
    command: str  # ground, preground, postground, cite, research


class AutographManager:
    """
    Manages the autograph knowledge graph.

    Usage:
        manager = AutographManager("/path/to/knowledge_graph/")

        # Log a grounding choice
        manager.log_autograph(
            context_summary="MCP grounding architecture",
            command="ground",
            sources_offered=["file:mcp_research.md", "file:semantic.md"],
            sources_accepted=["file:mcp_research.md"],
            sources_rejected=["file:semantic.md"]
        )

        # Get suggestions for a context
        suggestions = manager.suggest_sources("working on MCP tools")
    """

    def __init__(self, kg_path: str):
        self.kg_path = Path(kg_path)
        self.nodes_file = self.kg_path / "nodes.csv"
        self.edges_file = self.kg_path / "edges.csv"
        self.config_file = self.kg_path / "config.json"
        self.embeddings_file = self.kg_path / "embeddings.npy"
        self.embedding_index_file = self.kg_path / "embedding_index.json"

        # Load config
        self.config = self._load_config()

        # Initialize embedding model if available
        self.model = None
        self.embeddings = None
        self.embedding_index = {}  # node_id -> index in embeddings array

        if EMBEDDINGS_AVAILABLE:
            try:
                self.model = SentenceTransformer(self.config["settings"]["embedding_model"])
                self._load_embeddings()
            except Exception as e:
                print(f"Warning: Could not load embedding model: {e}", flush=True)

    def _load_config(self) -> Dict:
        """Load configuration from JSON file"""
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return {
            "settings": {
                "decay_factor": 0.95,
                "auto_suggest_threshold": 0.5,
                "auto_include_threshold": 0.8,
                "max_suggestions": 5
            },
            "edge_weights": {
                "accepted": 1.0,
                "rejected": -0.5,
                "ignored": 0.0,
                "discusses": 0.5
            }
        }

    def _load_embeddings(self):
        """Load embeddings from numpy file"""
        if self.embeddings_file.exists() and self.embedding_index_file.exists():
            self.embeddings = np.load(self.embeddings_file)
            with open(self.embedding_index_file, 'r') as f:
                self.embedding_index = json.load(f)

    def _save_embeddings(self):
        """Save embeddings to numpy file"""
        if self.embeddings is not None:
            np.save(self.embeddings_file, self.embeddings)
            with open(self.embedding_index_file, 'w') as f:
                json.dump(self.embedding_index, f)

    def _generate_context_hash(self, context: str) -> str:
        """Generate a short hash for context identification"""
        return hashlib.md5(context.encode()).hexdigest()[:8]

    def _embed_text(self, text: str) -> Optional[np.ndarray]:
        """Generate embedding for text"""
        if self.model is None:
            return None
        return self.model.encode(text, convert_to_numpy=True)

    def _add_embedding(self, node_id: str, text: str) -> Optional[str]:
        """Add embedding for a node, return embedding_id"""
        if self.model is None:
            return None

        embedding = self._embed_text(text)
        if embedding is None:
            return None

        # Add to embeddings array
        if self.embeddings is None:
            self.embeddings = embedding.reshape(1, -1)
        else:
            self.embeddings = np.vstack([self.embeddings, embedding])

        idx = len(self.embedding_index)
        self.embedding_index[node_id] = idx
        self._save_embeddings()

        return f"emb:{node_id}"

    def _find_similar_contexts(self, query: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """Find contexts similar to query using embeddings"""
        if self.model is None or self.embeddings is None or len(self.embeddings) == 0:
            return []

        query_embedding = self._embed_text(query)
        if query_embedding is None:
            return []

        # Cosine similarity
        query_norm = query_embedding / np.linalg.norm(query_embedding)
        embeddings_norm = self.embeddings / np.linalg.norm(self.embeddings, axis=1, keepdims=True)
        similarities = np.dot(embeddings_norm, query_norm)

        # Get top-k indices
        top_indices = np.argsort(similarities)[-top_k:][::-1]

        # Map back to node_ids
        index_to_node = {v: k for k, v in self.embedding_index.items()}
        results = []
        for idx in top_indices:
            if idx in index_to_node:
                results.append((index_to_node[idx], float(similarities[idx])))

        return results

    def _read_nodes(self) -> List[KnowledgeNode]:
        """Read all nodes from CSV"""
        nodes = []
        if not self.nodes_file.exists():
            return nodes

        with open(self.nodes_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                nodes.append(KnowledgeNode(**row))
        return nodes

    def _write_node(self, node: KnowledgeNode):
        """Append a node to CSV"""
        file_exists = self.nodes_file.exists()
        with open(self.nodes_file, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'node_id', 'node_type', 'label', 'embedding_id',
                'created', 'last_seen', 'metadata'
            ])
            if not file_exists:
                writer.writeheader()
            writer.writerow(asdict(node))

    def _read_edges(self) -> List[KnowledgeEdge]:
        """Read all edges from CSV"""
        edges = []
        if not self.edges_file.exists():
            return edges

        with open(self.edges_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                row['weight'] = float(row['weight'])
                edges.append(KnowledgeEdge(**row))
        return edges

    def _write_edge(self, edge: KnowledgeEdge):
        """Append an edge to CSV"""
        file_exists = self.edges_file.exists()
        with open(self.edges_file, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'timestamp', 'source_node', 'edge_type', 'target_node',
                'weight', 'context_summary', 'command'
            ])
            if not file_exists:
                writer.writeheader()
            writer.writerow(asdict(edge))

    def _get_or_create_node(self, node_id: str, node_type: str, label: str) -> KnowledgeNode:
        """Get existing node or create new one"""
        nodes = self._read_nodes()
        for node in nodes:
            if node.node_id == node_id:
                # Update last_seen
                node.last_seen = datetime.utcnow().isoformat() + "Z"
                return node

        # Create new node
        embedding_id = None
        if node_type == "context":
            embedding_id = self._add_embedding(node_id, label)

        node = KnowledgeNode(
            node_id=node_id,
            node_type=node_type,
            label=label,
            embedding_id=embedding_id
        )
        self._write_node(node)
        return node

    def log_autograph(
        self,
        context_summary: str,
        command: str,
        sources_offered: List[str],
        sources_accepted: List[str] = None,
        sources_rejected: List[str] = None
    ) -> Dict[str, Any]:
        """
        Log a grounding choice as autograph entries.

        Args:
            context_summary: What user was working on
            command: Which grounding command (ground, preground, postground, cite, research)
            sources_offered: All sources offered to user
            sources_accepted: Sources user accepted (pulled into context)
            sources_rejected: Sources user explicitly rejected

        Returns:
            Dict with autograph details
        """
        sources_accepted = sources_accepted or []
        sources_rejected = sources_rejected or []

        timestamp = datetime.utcnow().isoformat() + "Z"
        context_hash = self._generate_context_hash(context_summary)
        context_node_id = f"context:{context_hash}"

        # Create/update context node
        self._get_or_create_node(context_node_id, "context", context_summary)

        edges_created = []
        weights = self.config["edge_weights"]

        # Log accepted sources
        for source in sources_accepted:
            source_node_id = f"file:{os.path.basename(source)}"
            self._get_or_create_node(source_node_id, "file", source)

            edge = KnowledgeEdge(
                timestamp=timestamp,
                source_node=context_node_id,
                edge_type="accepted",
                target_node=source_node_id,
                weight=weights["accepted"],
                context_summary=context_summary,
                command=command
            )
            self._write_edge(edge)
            edges_created.append(asdict(edge))

        # Log rejected sources
        for source in sources_rejected:
            source_node_id = f"file:{os.path.basename(source)}"
            self._get_or_create_node(source_node_id, "file", source)

            edge = KnowledgeEdge(
                timestamp=timestamp,
                source_node=context_node_id,
                edge_type="rejected",
                target_node=source_node_id,
                weight=weights["rejected"],
                context_summary=context_summary,
                command=command
            )
            self._write_edge(edge)
            edges_created.append(asdict(edge))

        # Log ignored sources (offered but neither accepted nor rejected)
        ignored = set(sources_offered) - set(sources_accepted) - set(sources_rejected)
        for source in ignored:
            source_node_id = f"file:{os.path.basename(source)}"
            self._get_or_create_node(source_node_id, "file", source)

            edge = KnowledgeEdge(
                timestamp=timestamp,
                source_node=context_node_id,
                edge_type="ignored",
                target_node=source_node_id,
                weight=weights["ignored"],
                context_summary=context_summary,
                command=command
            )
            self._write_edge(edge)
            edges_created.append(asdict(edge))

        return {
            "context_node": context_node_id,
            "edges_created": len(edges_created),
            "accepted": len(sources_accepted),
            "rejected": len(sources_rejected),
            "ignored": len(ignored)
        }

    def query_autographs(self, context: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Query autographs for patterns related to a context.

        Returns edges that match similar contexts.
        """
        # Find similar contexts using embeddings
        similar_contexts = self._find_similar_contexts(context, top_k=limit)

        if not similar_contexts:
            # Fallback: simple text matching
            edges = self._read_edges()
            context_lower = context.lower()
            matching = [e for e in edges if context_lower in e.context_summary.lower()]
            return [asdict(e) for e in matching[:limit]]

        # Get edges for similar contexts
        edges = self._read_edges()
        results = []

        for ctx_node_id, similarity in similar_contexts:
            for edge in edges:
                if edge.source_node == ctx_node_id:
                    result = asdict(edge)
                    result['context_similarity'] = similarity
                    results.append(result)

        # Sort by similarity then weight
        results.sort(key=lambda x: (-x.get('context_similarity', 0), -x['weight']))
        return results[:limit]

    def suggest_sources(self, context: str, threshold: float = None) -> List[Dict[str, Any]]:
        """
        Get source suggestions based on accumulated autographs.

        Returns sources that were frequently accepted in similar contexts.
        """
        if threshold is None:
            threshold = self.config["settings"]["auto_suggest_threshold"]

        max_suggestions = self.config["settings"]["max_suggestions"]

        # Find similar contexts
        similar_contexts = self._find_similar_contexts(context, top_k=20)

        if not similar_contexts:
            return []

        # Aggregate scores for each source
        edges = self._read_edges()
        source_scores = {}

        for ctx_node_id, similarity in similar_contexts:
            if similarity < threshold:
                continue

            for edge in edges:
                if edge.source_node == ctx_node_id:
                    source = edge.target_node
                    if source not in source_scores:
                        source_scores[source] = {"accepted": 0, "rejected": 0, "total_weight": 0}

                    if edge.edge_type == "accepted":
                        source_scores[source]["accepted"] += similarity
                        source_scores[source]["total_weight"] += edge.weight * similarity
                    elif edge.edge_type == "rejected":
                        source_scores[source]["rejected"] += similarity
                        source_scores[source]["total_weight"] += edge.weight * similarity

        # Calculate confidence and filter
        suggestions = []
        for source, scores in source_scores.items():
            total = scores["accepted"] + scores["rejected"]
            if total > 0:
                confidence = scores["accepted"] / total
                if confidence >= threshold:
                    suggestions.append({
                        "source": source,
                        "confidence": round(confidence, 3),
                        "total_weight": round(scores["total_weight"], 3),
                        "accept_count": round(scores["accepted"], 2),
                        "reject_count": round(scores["rejected"], 2)
                    })

        # Sort by confidence then weight
        suggestions.sort(key=lambda x: (-x["confidence"], -x["total_weight"]))
        return suggestions[:max_suggestions]

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the autograph graph"""
        nodes = self._read_nodes()
        edges = self._read_edges()

        node_types = {}
        for node in nodes:
            node_types[node.node_type] = node_types.get(node.node_type, 0) + 1

        edge_types = {}
        for edge in edges:
            edge_types[edge.edge_type] = edge_types.get(edge.edge_type, 0) + 1

        # Determine bootstrap phase
        total_edges = len(edges)
        if total_edges == 0:
            phase = "Cold"
        elif total_edges < 10:
            phase = "Learning"
        elif total_edges < 50:
            phase = "Warm"
        else:
            phase = "Hot"

        return {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "node_types": node_types,
            "edge_types": edge_types,
            "bootstrap_phase": phase,
            "embeddings_available": EMBEDDINGS_AVAILABLE and self.model is not None,
            "embeddings_count": len(self.embedding_index) if self.embedding_index else 0
        }


# Convenience function for quick testing
if __name__ == "__main__":
    import sys

    kg_path = sys.argv[1] if len(sys.argv) > 1 else "./knowledge_graph"
    manager = AutographManager(kg_path)

    # Print stats
    stats = manager.get_stats()
    print(json.dumps(stats, indent=2))
