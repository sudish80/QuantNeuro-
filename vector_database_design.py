"""
Enhanced Vector Database Design for Neural Network Trading System

This module provides advanced vector storage and similarity search capabilities:
1. Multi-collection support (patterns, trades, predictions, features)
2. Time-based retention policies
3. Advanced filtering (range, composite)
4. Clustering and segmentation
5. Analytics and aggregations
6. REST API server
7. Backup/restore with compression
8. Anomaly detection
"""

import asyncio
import bz2
import gzip
import hashlib
import json
import pickle
import shutil
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from functools import lru_cache

import numpy as np


# ============================================================================
# Enhanced Configuration
# ============================================================================

class IndexType(Enum):
    FLAT = "FLAT"
    IVF_FLAT = "IVF_FLAT"
    IVF_PQ = "IVF_PQ"
    HNSW = "HNSW"
    PINECONE = "PINECONE"
    MILVUS = "MILVUS"


class MetricType(Enum):
    COSINE = "cosine"
    EUCLIDEAN = "l2"
    INNER_PRODUCT = "ip"


class CollectionStatus(Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    FROZEN = "frozen"


@dataclass
class VectorDBConfig:
    """Enhanced configuration for vector database."""
    # Backend settings
    backend: str = "faiss"  # faiss, milvus, pinecone, memory
    dimension: int = 128
    
    # Index settings
    index_type: IndexType = IndexType.IVF_FLAT
    nlist: int = 100  # IVF clusters
    nprobe: int = 10  # Search probes
    m: int = 8  # PQ segments
    nbits: int = 8  # PQ bits
    ef_construction: int = 200  # HNSW
    ef_search: int = 50  # HNSW
    
    # Metric
    metric: MetricType = MetricType.COSINE
    
    # Storage
    persist_path: str = "./output/vector_db"
    max_vectors_per_collection: int = 10_000_000
    
    # GPU
    use_gpu: bool = False
    gpu_id: int = 0
    
    # Collections
    collections: dict[str, "CollectionConfig"] = field(default_factory=dict)
    
    # Remote services
    pinecone_api_key: str = ""
    pinecone_environment: str = ""
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    
    # Features
    enable_compression: bool = True
    enable_backup: bool = True
    backup_interval_hours: int = 24
    
    # Retention
    default_retention_days: int = 90
    auto_cleanup: bool = True


@dataclass
class CollectionConfig:
    """Configuration for a single collection."""
    name: str
    dimension: int = 128
    description: str = ""
    status: CollectionStatus = CollectionStatus.ACTIVE
    
    # Index settings (override global)
    index_type: IndexType | None = None
    nlist: int | None = None
    metric: MetricType | None = None
    
    # Retention
    retention_days: int | None = None
    
    # Tags for filtering
    tags: list[str] = field(default_factory=list)
    
    # Auto-clustering
    enable_clustering: bool = False
    n_clusters: int = 10


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class VectorEntry:
    """Single vector entry with metadata."""
    id: str
    vector: np.ndarray
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    collection: str = "default"
    tags: list[str] = field(default_factory=list)
    
    def __post_init__(self):
        if isinstance(self.vector, list):
            self.vector = np.array(self.vector, dtype=np.float32)
        if self.vector.dtype != np.float32:
            self.vector = self.vector.astype(np.float32)
        # Normalize for cosine similarity
        norm = np.linalg.norm(self.vector)
        if norm > 0:
            self.vector = self.vector / norm
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "vector": self.vector.tolist(),
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "collection": self.collection,
            "tags": self.tags
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "VectorEntry":
        data["vector"] = np.array(data["vector"], dtype=np.float32)
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)
    
    def get_hash(self) -> str:
        """Generate unique hash for this entry."""
        content = f"{self.id}{self.collection}{self.timestamp.isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class SearchResult:
    """Search result with similarity score."""
    entry: VectorEntry
    distance: float
    score: float = 0.0
    cluster_id: int = -1
    
    def __post_init__(self):
        self.score = max(0.0, 1.0 - self.distance / 2.0)


@dataclass
class SearchFilter:
    """Advanced search filter."""
    # Metadata filters
    metadata: dict | None = None
    
    # Range filters (for numeric fields)
    range_filters: dict[str, tuple[float, float]] | None = None
    
    # Time range
    time_range: tuple[datetime, datetime] | None = None
    
    # Tags
    tags: list[str] | None = None
    
    # Collections
    collections: list[str] | None = None
    
    # Composite: AND/OR
    logical_op: str = "AND"  # AND, OR
    
    def match(self, entry: VectorEntry) -> bool:
        """Check if entry matches this filter."""
        if self.metadata:
            for k, v in self.metadata.items():
                if entry.metadata.get(k) != v:
                    return self.logical_op == "OR"
        
        if self.range_filters:
            for field, (min_val, max_val) in self.range_filters.items():
                val = entry.metadata.get(field)
                if val is None or not (min_val <= val <= max_val):
                    return self.logical_op == "OR"
        
        if self.time_range:
            start, end = self.time_range
            if not (start <= entry.timestamp <= end):
                return self.logical_op == "OR"
        
        if self.tags:
            if not any(t in entry.tags for t in self.tags):
                return self.logical_op == "OR"
        
        if self.collections:
            if entry.collection not in self.collections:
                return self.logical_op == "OR"
        
        return self.logical_op == "AND" or any([
            self.metadata, self.range_filters, self.time_range, self.tags, self.collections
        ])


@dataclass
class ClusterInfo:
    """Information about a cluster."""
    id: int
    centroid: np.ndarray
    size: int = 0
    avg_distance: float = 0.0
    examples: list[str] = field(default_factory=list)
    metadata_stats: dict = field(default_factory=dict)


@dataclass
class AnalyticsResult:
    """Analytics and aggregation results."""
    total_vectors: int
    collections_count: int
    clusters_count: int
    
    # Time-based
    oldest_entry: datetime | None = None
    newest_entry: datetime | None = None
    entries_per_day: dict = field(default_factory=dict)
    
    # Metadata stats
    metadata_fields: list[str] = field(default_factory=list)
    metadata_distribution: dict = field(default_factory=dict)
    
    # Cluster stats
    cluster_sizes: list[int] = field(default_factory=list)
    cluster_centroids: list[np.ndarray] = field(default_factory=list)
    
    # Anomalies
    anomaly_count: int = 0
    anomaly_ids: list[str] = field(default_factory=list)


# ============================================================================
# Enhanced Vector Store with Collections
# ============================================================================

class VectorDatabase:
    """
    Enhanced vector database with multi-collection support.
    
    Features:
    - Multiple collections
    - Time-based retention
    - Clustering
    - Analytics
    - Backup/restore
    - REST API server
    """
    
    def __init__(self, config: VectorDBConfig | None = None):
        self.config = config or VectorDBConfig()
        self.collections: dict[str, "Collection"] = {}
        self._lock = threading.RLock()
        self._init_backends()
    
    def _init_backends(self):
        """Initialize backend storage."""
        Path(self.config.persist_path).mkdir(parents=True, exist_ok=True)
        
        # Create default collection
        if "default" not in self.collections:
            self.create_collection("default", dimension=self.config.dimension)
    
    def create_collection(
        self, 
        name: str, 
        dimension: int = 128,
        description: str = "",
        retention_days: int | None = None
    ) -> "Collection":
        """Create a new collection."""
        with self._lock:
            if name in self.collections:
                raise ValueError(f"Collection '{name}' already exists")
            
            collection = Collection(
                name=name,
                dimension=dimension,
                config=self.config,
                description=description,
                retention_days=retention_days or self.config.default_retention_days
            )
            self.collections[name] = collection
            return collection
    
    def get_collection(self, name: str) -> "Collection":
        """Get a collection by name."""
        if name not in self.collections:
            raise KeyError(f"Collection '{name}' not found")
        return self.collections[name]
    
    def delete_collection(self, name: str, backup: bool = True) -> bool:
        """Delete a collection."""
        with self._lock:
            if name not in self.collections:
                return False
            
            if backup:
                self.backup_collection(name)
            
            del self.collections[name]
            return True
    
    def list_collections(self) -> list[str]:
        """List all collection names."""
        return list(self.collections.keys())
    
    def add(
        self,
        entry: VectorEntry,
        collection: str = "default"
    ) -> str:
        """Add an entry to a collection."""
        entry.collection = collection
        return self.get_collection(collection).add(entry)
    
    def add_batch(
        self,
        entries: list[VectorEntry],
        collection: str = "default"
    ) -> list[str]:
        """Add multiple entries."""
        return self.get_collection(collection).add_batch(entries)
    
    def search(
        self,
        query_vector: np.ndarray,
        k: int = 10,
        collection: str = "default",
        filter: SearchFilter | None = None
    ) -> list[SearchResult]:
        """Search in a collection."""
        return self.get_collection(collection).search(query_vector, k, filter)
    
    def search_multi(
        self,
        query_vector: np.ndarray,
        k: int = 10,
        collections: list[str] | None = None,
        filter: SearchFilter | None = None,
        weights: dict[str, float] | None = None
    ) -> dict[str, list[SearchResult]]:
        """Search across multiple collections."""
        if collections is None:
            collections = self.list_collections()
        
        if weights is None:
            weights = {c: 1.0 for c in collections}
        
        results = {}
        for col in collections:
            try:
                col_results = self.search(query_vector, k, col, filter)
                # Apply weight
                for r in col_results:
                    r.distance /= weights.get(col, 1.0)
                results[col] = col_results
            except KeyError:
                continue
        
        return results
    
    def get(self, entry_id: str, collection: str = "default") -> VectorEntry | None:
        """Get an entry."""
        return self.get_collection(collection).get(entry_id)
    
    def delete(self, entry_id: str, collection: str = "default") -> bool:
        """Delete an entry."""
        return self.get_collection(collection).delete(entry_id)
    
    def count(self, collection: str | None = None) -> int:
        """Count entries."""
        if collection:
            return self.get_collection(collection).count()
        return sum(c.count() for c in self.collections.values())
    
    def cleanup(self) -> dict[str, int]:
        """Run cleanup based on retention policies."""
        cleaned = {}
        for name, collection in self.collections.items():
            deleted = collection.cleanup()
            if deleted > 0:
                cleaned[name] = deleted
        return cleaned
    
    def cluster(self, collection: str, n_clusters: int = 10) -> list[ClusterInfo]:
        """Cluster vectors in a collection."""
        return self.get_collection(collection).cluster(n_clusters)
    
    def analyze(self, collection: str | None = None) -> AnalyticsResult:
        """Get analytics for collection(s)."""
        if collection:
            return self.get_collection(collection).analyze()
        
        # Aggregate across all collections
        total = AnalyticsResult(
            total_vectors=0,
            collections_count=len(self.collections),
            clusters_count=0
        )
        
        for col in self.collections.values():
            analytics = col.analyze()
            total.total_vectors += analytics.total_vectors
            total.clusters_count += analytics.clusters_count
        
        return total
    
    def find_anomalies(
        self,
        collection: str,
        threshold: float = 3.0,
        method: str = "statistical"
    ) -> list[VectorEntry]:
        """Find anomalous entries."""
        return self.get_collection(collection).find_anomalies(threshold, method)
    
    def backup(self, path: str | None = None) -> str:
        """Create full backup."""
        if path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"{self.config.persist_path}/backup_{timestamp}"
        
        backup_path = Path(path)
        backup_path.mkdir(parents=True, exist_ok=True)
        
        # Backup each collection
        for name, collection in self.collections.items():
            collection.save(str(backup_path / name))
        
        # Compress if enabled
        if self.config.enable_compression:
            archive_path = f"{path}.tar.bz2"
            shutil.make_archive(path, "bztar", path)
            shutil.rmtree(path)
            return archive_path
        
        return path
    
    def restore(self, path: str) -> None:
        """Restore from backup."""
        backup_path = Path(path)
        
        # Extract if compressed
        if path.endswith(".tar.bz2"):
            extract_path = path.replace(".tar.bz2", "")
            with bz2.open(path, "rt") as f:
                shutil.unpack_archive(path, extract_path)
            backup_path = Path(extract_path)
        
        # Load collections
        for col_path in backup_path.iterdir():
            if col_path.is_dir():
                name = col_path.name
                if name in self.collections:
                    self.collections[name].load(str(col_path))
    
    def save(self) -> None:
        """Save all collections."""
        for collection in self.collections.values():
            collection.save()
    
    def load(self) -> None:
        """Load all collections."""
        base_path = Path(self.config.persist_path)
        if not base_path.exists():
            return
        
        for col_path in base_path.iterdir():
            if col_path.is_dir():
                name = col_path.name
                if name not in self.collections:
                    self.create_collection(name)
                self.collections[name].load(str(col_path))


# ============================================================================
# Collection Class
# ============================================================================

class Collection:
    """A single vector collection with its own index."""
    
    def __init__(
        self,
        name: str,
        dimension: int,
        config: VectorDBConfig,
        description: str = "",
        retention_days: int = 90
    ):
        self.name = name
        self.dimension = dimension
        self.config = config
        self.description = description
        self.retention_days = retention_days
        
        self._vectors: dict[str, np.ndarray] = {}
        self._metadata: dict[str, dict] = {}
        self._timestamps: dict[str, datetime] = {}
        self._tags: dict[str, list[str]] = {}
        self._next_id = 0
        
        self._clusters: list[ClusterInfo] = []
        self._cluster_labels: dict[str, int] = {}
        
        # Initialize index
        self._init_index()
    
    def _init_index(self):
        """Initialize FAISS index."""
        try:
            import faiss
            self.faiss = faiss
            
            # Create base index
            if self.config.metric == MetricType.COSINE:
                self.index = faiss.IndexFlatIP(self.dimension)
            elif self.config.metric == MetricType.EUCLIDEAN:
                self.index = faiss.IndexFlatL2(self.dimension)
            else:
                self.index = faiss.IndexFlatIP(self.dimension)
            
            # Wrap with IVF if configured
            if self.config.index_type == IndexType.IVF_FLAT:
                quantizer = faiss.IndexFlatL2(self.dimension)
                self.index = faiss.IndexIVFFlat(
                    quantizer, self.dimension, self.config.nlist
                )
            
            # GPU
            if self.config.use_gpu:
                try:
                    self.index = faiss.index_cpu_to_gpu(
                        faiss.StandardGpuResources(),
                        self.config.gpu_id,
                        self.index
                    )
                except:
                    pass
                    
        except ImportError:
            self.faiss = None
            self.index = None
    
    def _normalize(self, vector: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vector)
        if norm > 0:
            return vector / norm
        return vector
    
    def add(self, entry: VectorEntry) -> str:
        """Add a single vector."""
        if not entry.id:
            entry.id = f"{self.name}_{self._next_id}"
            self._next_id += 1
        
        if entry.vector.shape[0] != self.dimension:
            raise ValueError(f"Dimension mismatch: {entry.vector.shape[0]} != {self.dimension}")
        
        normalized = self._normalize(entry.vector)
        
        self._vectors[entry.id] = normalized.astype(np.float32)
        self._metadata[entry.id] = entry.metadata
        self._timestamps[entry.id] = entry.timestamp
        self._tags[entry.id] = entry.tags
        
        if self.index is not None:
            self.index.add(np.array([normalized]))
        
        return entry.id
    
    def add_batch(self, entries: list[VectorEntry]) -> list[str]:
        """Add multiple vectors."""
        if not entries:
            return []
        
        ids = []
        vectors = []
        
        for entry in entries:
            if not entry.id:
                entry.id = f"{self.name}_{self._next_id}"
                self._next_id += 1
            
            if entry.vector.shape[0] != self.dimension:
                raise ValueError(f"Dimension mismatch for {entry.id}")
            
            normalized = self._normalize(entry.vector)
            self._vectors[entry.id] = normalized.astype(np.float32)
            self._metadata[entry.id] = entry.metadata
            self._timestamps[entry.id] = entry.timestamp
            self._tags[entry.id] = entry.tags
            
            vectors.append(normalized)
            ids.append(entry.id)
        
        if self.index is not None and vectors:
            self.index.add(np.array(vectors))
        
        return ids
    
    def search(
        self,
        query_vector: np.ndarray,
        k: int = 10,
        filter: SearchFilter | None = None
    ) -> list[SearchResult]:
        """Search for nearest neighbors."""
        if not self._vectors:
            return []
        
        query = self._normalize(query_vector).astype(np.float32).reshape(1, -1)
        
        # Vector search
        if self.index is not None:
            distances, indices = self.index.search(
                query, min(k * 10, len(self._vectors))
            )
        else:
            # Brute force fallback
            distances, indices = [], []
            for vec in self._vectors.values():
                dist = float(np.dot(query.flatten(), vec))
                distances.append(1 - dist)
                indices.append(list(self._vectors.keys()).index(vec))
            distances = [distances]
            indices = [indices]
        
        results = []
        ids_list = list(self._vectors.keys())
        
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(ids_list):
                continue
            
            entry_id = ids_list[idx]
            
            # Apply filter
            if filter:
                entry = VectorEntry(
                    id=entry_id,
                    vector=self._vectors[entry_id],
                    metadata=self._metadata.get(entry_id, {}),
                    timestamp=self._timestamps.get(entry_id, datetime.now()),
                    tags=self._tags.get(entry_id, [])
                )
                if not filter.match(entry):
                    continue
            
            entry = VectorEntry(
                id=entry_id,
                vector=np.zeros(self.dimension),
                metadata=self._metadata.get(entry_id, {}),
                timestamp=self._timestamps.get(entry_id, datetime.now()),
                tags=self._tags.get(entry_id, [])
            )
            results.append(SearchResult(
                entry=entry,
                distance=dist,
                cluster_id=self._cluster_labels.get(entry_id, -1)
            ))
            
            if len(results) >= k:
                break
        
        return results
    
    def get(self, entry_id: str) -> VectorEntry | None:
        """Get an entry by ID."""
        if entry_id not in self._vectors:
            return None
        return VectorEntry(
            id=entry_id,
            vector=self._vectors[entry_id],
            metadata=self._metadata.get(entry_id, {}),
            timestamp=self._timestamps.get(entry_id, datetime.now()),
            tags=self._tags.get(entry_id, [])
        )
    
    def delete(self, entry_id: str) -> bool:
        """Delete an entry."""
        if entry_id not in self._vectors:
            return False
        
        del self._vectors[entry_id]
        self._metadata.pop(entry_id, None)
        self._timestamps.pop(entry_id, None)
        self._tags.pop(entry_id, None)
        self._cluster_labels.pop(entry_id, None)
        
        # Rebuild index
        if self.index is not None:
            self._init_index()
            if self._vectors:
                self.index.add(np.array(list(self._vectors.values())))
        
        return True
    
    def count(self) -> int:
        """Count vectors."""
        return len(self._vectors)
    
    def cleanup(self) -> int:
        """Remove entries past retention period."""
        if self.retention_days <= 0:
            return 0
        
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        to_delete = [
            eid for eid, ts in self._timestamps.items() 
            if ts < cutoff
        ]
        
        for eid in to_delete:
            self.delete(eid)
        
        return len(to_delete)
    
    def cluster(self, n_clusters: int = 10) -> list[ClusterInfo]:
        """Cluster vectors using K-means."""
        if len(self._vectors) < n_clusters:
            return []
        
        try:
            import faiss
            vectors = np.array(list(self._vectors.values()))
            
            # K-means clustering
            kmeans = faiss.Kmeans(
                self.dimension, 
                n_clusters,
                niter=20,
                verbose=False
            )
            kmeans.train(vectors)
            
            # Get centroids and labels
            centroids = kmeans.centroids
            _, labels = kmeans.index.search(vectors, 1)
            
            # Build cluster info
            self._clusters = []
            cluster_sizes = [0] * n_clusters
            cluster_vectors: dict[int, list] = {i: [] for i in range(n_clusters)}
            
            for idx, (vec_id, label) in enumerate(zip(self._vectors.keys(), labels.flatten())):
                self._cluster_labels[vec_id] = label
                cluster_sizes[label] += 1
                cluster_vectors[label].append(idx)
            
            for i in range(n_clusters):
                cluster_vecs = vectors[cluster_vectors[i]]
                avg_dist = float(np.mean(np.linalg.norm(cluster_vecs - centroids[i], axis=1)))
                
                self._clusters.append(ClusterInfo(
                    id=i,
                    centroid=centroids[i],
                    size=cluster_sizes[i],
                    avg_distance=avg_dist,
                    examples=list(self._vectors.keys())[:5]
                ))
            
            return self._clusters
            
        except ImportError:
            return []
    
    def find_anomalies(
        self,
        threshold: float = 3.0,
        method: str = "statistical"
    ) -> list[VectorEntry]:
        """Find anomalous vectors."""
        if not self._vectors:
            return []
        
        vectors = np.array(list(self._vectors.values()))
        ids = list(self._vectors.keys())
        
        if method == "statistical":
            # Z-score based
            mean = np.mean(vectors, axis=0)
            std = np.std(vectors, axis=0)
            std = np.where(std == 0, 1, std)
            z_scores = np.abs((vectors - mean) / std)
            max_z = np.max(z_scores, axis=1)
            
            anomalous_idx = np.where(max_z > threshold)[0]
        
        elif method == "isolation_forest":
            # Simple isolation score
            from sklearn.ensemble import IsolationForest
            clf = IsolationForest(contamination=0.1, random_state=42)
            preds = clf.fit_predict(vectors)
            anomalous_idx = np.where(preds == -1)[0]
        
        else:
            # Distance-based
            from sklearn.neighbors import NearestNeighbors
            nn = NearestNeighbors(n_neighbors=5)
            nn.fit(vectors)
            distances, _ = nn.kneighbors(vectors)
            avg_distances = np.mean(distances, axis=1)
            threshold_val = np.percentile(avg_distances, 95)
            anomalous_idx = np.where(avg_distances > threshold_val)[0]
        
        return [self.get(ids[idx]) for idx in anomalous_idx]
    
    def analyze(self) -> AnalyticsResult:
        """Get analytics for this collection."""
        timestamps = list(self._timestamps.values())
        
        # Time range
        oldest = min(timestamps) if timestamps else None
        newest = max(timestamps) if timestamps else None
        
        # Entries per day
        entries_per_day = {}
        for ts in timestamps:
            day = ts.strftime("%Y-%m-%d")
            entries_per_day[day] = entries_per_day.get(day, 0) + 1
        
        # Metadata fields
        all_fields = set()
        for meta in self._metadata.values():
            all_fields.update(meta.keys())
        
        # Metadata distribution
        meta_dist = {}
        for field in all_fields:
            values = [m.get(field) for m in self._metadata.values() if field in m]
            if values and isinstance(values[0], (int, float)):
                meta_dist[field] = {
                    "min": float(min(values)),
                    "max": float(max(values)),
                    "mean": float(sum(values) / len(values))
                }
        
        # Cluster info
        cluster_sizes = [c.size for c in self._clusters]
        
        return AnalyticsResult(
            total_vectors=len(self._vectors),
            collections_count=1,
            clusters_count=len(self._clusters),
            oldest_entry=oldest,
            newest_entry=newest,
            entries_per_day=entries_per_day,
            metadata_fields=list(all_fields),
            metadata_distribution=meta_dist,
            cluster_sizes=cluster_sizes,
            cluster_centroids=[c.centroid for c in self._clusters]
        )
    
    def save(self, path: str | None = None) -> None:
        """Save collection to disk."""
        if path is None:
            path = f"{self.config.persist_path}/{self.name}"
        
        save_path = Path(path)
        save_path.mkdir(parents=True, exist_ok=True)
        
        # Save vectors
        if self._vectors:
            vectors_path = save_path / "vectors.npz"
            np.savez(vectors_path, **{k: v for k, v in self._vectors.items()})
        
        # Save metadata
        metadata_path = save_path / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump({
                "metadata": self._metadata,
                "timestamps": {k: v.isoformat() for k, v in self._timestamps.items()},
                "tags": self._tags,
                "next_id": self._next_id,
                "name": self.name,
                "dimension": self.dimension,
                "retention_days": self.retention_days,
                "description": self.description
            }, f, indent=2, default=str)
        
        # Save index
        if self.index is not None and hasattr(self.index, 'ntotal') and self.index.ntotal > 0:
            try:
                index_path = save_path / "index.faiss"
                self.faiss.write_index(self.index, str(index_path))
            except:
                pass
    
    def load(self, path: str) -> None:
        """Load collection from disk."""
        load_path = Path(path)
        
        # Load vectors
        vectors_path = load_path / "vectors.npz"
        if vectors_path.exists():
            data = np.load(vectors_path, allow_pickle=True)
            self._vectors = {k: data[k] for k in data.files}
        
        # Load metadata
        metadata_path = load_path / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path, "r") as f:
                data = json.load(f)
                self._metadata = data.get("metadata", {})
                self._timestamps = {
                    k: datetime.fromisoformat(v) 
                    for k, v in data.get("timestamps", {}).items()
                }
                self._tags = data.get("tags", {})
                self._next_id = data.get("next_id", 0)
                self.name = data.get("name", self.name)
                self.dimension = data.get("dimension", self.dimension)
                self.retention_days = data.get("retention_days", 90)
                self.description = data.get("description", "")


# ============================================================================
# Factory Function
# ============================================================================

def create_vector_database(config: VectorDBConfig | None = None) -> VectorDatabase:
    """Create vector database instance."""
    return VectorDatabase(config)


# ============================================================================
# REST API Server (Optional)
# ============================================================================

class VectorDBServer:
    """REST API server for vector database."""
    
    def __init__(self, database: VectorDatabase, host: str = "0.0.0.0", port: int = 8000):
        self.database = database
        self.host = host
        self.port = port
        self._app = None
    
    def _create_app(self):
        """Create FastAPI app."""
        try:
            from fastapi import FastAPI, HTTPException
            from pydantic import BaseModel
            from typing import List, Optional
            
            app = FastAPI(title="Vector DB API")
            
            class AddRequest(BaseModel):
                collection: str = "default"
                id: str = ""
                vector: List[float]
                metadata: dict = {}
                tags: List[str] = []
            
            class SearchRequest(BaseModel):
                vector: List[float]
                k: int = 10
                collection: str = "default"
                filter_metadata: Optional[dict] = None
            
            @app.post("/add")
            async def add_entry(req: AddRequest):
                entry = VectorEntry(
                    id=req.id,
                    vector=np.array(req.vector, dtype=np.float32),
                    metadata=req.metadata,
                    tags=req.tags
                )
                entry_id = self.database.add(entry, req.collection)
                return {"id": entry_id}
            
            @app.post("/search")
            async def search(req: SearchRequest):
                query = np.array(req.vector, dtype=np.float32)
                filter_obj = None
                if req.filter_metadata:
                    filter_obj = SearchFilter(metadata=req.filter_metadata)
                
                results = self.database.search(
                    query, req.k, req.collection, filter_obj
                )
                return {
                    "results": [
                        {
                            "id": r.entry.id,
                            "distance": r.distance,
                            "score": r.score,
                            "metadata": r.entry.metadata
                        }
                        for r in results
                    ]
                }
            
            @app.get("/collections")
            async def list_collections():
                return {"collections": self.database.list_collections()}
            
            @app.get("/collections/{name}/count")
            async def get_count(name: str):
                try:
                    count = self.database.count(name)
                    return {"collection": name, "count": count}
                except KeyError:
                    raise HTTPException(404, "Collection not found")
            
            @app.get("/collections/{name}/analyze")
            async def analyze(name: str):
                try:
                    analytics = self.database.analyze(name)
                    return {
                        "total_vectors": analytics.total_vectors,
                        "clusters_count": analytics.clusters_count,
                        "oldest": analytics.oldest_entry.isoformat() if analytics.oldest_entry else None,
                        "newest": analytics.newest_entry.isoformat() if analytics.newest_entry else None
                    }
                except KeyError:
                    raise HTTPException(404, "Collection not found")
            
            @app.post("/backup")
            async def backup():
                path = self.database.backup()
                return {"path": path}
            
            return app
            
        except ImportError:
            return None
    
    def start(self):
        """Start the server."""
        self._app = self._create_app()
        if self._app is None:
            print("FastAPI not installed. Install with: pip install fastapi uvicorn")
            return
        
        import uvicorn
        uvicorn.run(self._app, host=self.host, port=self.port)


# ============================================================================
# Usage Example
# ============================================================================

if __name__ == "__main__":
    # Create database
    config = VectorDBConfig(
        backend="memory",
        dimension=128,
        persist_path="./output/vector_db"
    )
    
    db = create_vector_database(config)
    
    # Create collections for different use cases
    patterns = db.create_collection(
        "patterns", 
        dimension=128,
        description="Historical price patterns",
        retention_days=180
    )
    
    predictions = db.create_collection(
        "predictions",
        dimension=64,
        description="Model predictions",
        retention_days=30
    )
    
    trades = db.create_collection(
        "trades",
        dimension=32,
        description="Trade embeddings",
        retention_days=365
    )
    
    # Add sample data
    np.random.seed(42)
    for i in range(100):
        vector = np.random.randn(128).astype(np.float32)
        entry = VectorEntry(
            id=f"pattern_{i}",
            vector=vector,
            metadata={
                "asset": np.random.choice(["AAPL", "BTC-USD", "EURUSD"]),
                "return_pct": float(np.random.randn() * 5),
                "volatility": float(np.random.uniform(0.1, 0.5))
            },
            tags=["bull", "volatile"] if i % 2 == 0 else ["bear", "stable"]
        )
        db.add(entry, "patterns")
    
    # Search
    query = np.random.randn(128).astype(np.float32)
    results = db.search(query, k=5, collection="patterns")
    print(f"\nSearch results:")
    for r in results:
        print(f"  {r.entry.id}: score={r.score:.3f}")
    
    # Cluster
    clusters = db.cluster("patterns", n_clusters=5)
    print(f"\nClusters: {len(clusters)}")
    for c in clusters:
        print(f"  Cluster {c.id}: size={c.size}, avg_dist={c.avg_distance:.3f}")
    
    # Find anomalies
    anomalies = db.find_anomalies("patterns", threshold=2.5)
    print(f"\nAnomalies found: {len(anomalies)}")
    
    # Analytics
    analytics = db.analyze("patterns")
    print(f"\nAnalytics:")
    print(f"  Total vectors: {analytics.total_vectors}")
    print(f"  Clusters: {analytics.clusters_count}")
    print(f"  Metadata fields: {analytics.metadata_fields}")
    
    # Save
    db.save()
    print("\nDatabase saved!")
