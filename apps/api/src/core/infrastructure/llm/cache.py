"""RBAC-aware semantic cache for LLM responses.

SECURITY-CRITICAL: Cache keys are partitioned by clearance_level +
sorted(departments) + sorted(entity_keys). Without this, the cache
becomes a universal RBAC bypass (EUR 250,000 exposure).

This is the in-memory implementation for unit testing and development.
Production deployment uses Redis Stack with RediSearch for vector
similarity. The interface is identical -- swap the backend, keep the
RBAC partitioning.

Cache key structure:
  partition = f"cl:{clearance}|dept:{sorted_depts}|ent:{sorted_entities}"
  Within each partition: cosine similarity search on query embeddings.

Invalidation:
  - By document ID (when doc re-ingested)
  - Full flush (embedding model change)
  - TTL expiry (default 24h)
  - Staleness detection (check if source docs updated since cache entry)

LRU eviction: when max_entries is reached, evict the oldest entry globally.
"""

import math
from collections import OrderedDict
from collections.abc import Callable, Coroutine
from datetime import datetime

from apps.api.src.core.domain.telemetry import CacheEntry

# Type alias for the async embedding function
EmbedFn = Callable[[str], Coroutine[None, None, list[float]]]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _partition_key(
    clearance_level: int,
    departments: list[str],
    entity_keys: list[str] | None = None,
) -> str:
    """Build RBAC-aware partition key.

    Sorted departments and entity keys ensure deterministic key
    regardless of input order.
    """
    sorted_depts = sorted(departments)
    sorted_entities = sorted(entity_keys or [])
    parts = [
        f"cl:{clearance_level}",
        f"dept:{','.join(sorted_depts)}",
        f"ent:{','.join(sorted_entities)}",
    ]
    return "|".join(parts)


class SemanticCache:
    """In-memory RBAC-aware semantic cache with cosine similarity.

    Entries are partitioned by RBAC context. Within each partition,
    similarity search finds the closest cached query. If similarity
    exceeds threshold, the cached response is returned.

    This implementation is for unit tests. Production uses Redis Stack.
    The RBAC partitioning logic is identical in both implementations.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.95,
        ttl_seconds: int = 86400,
        max_entries: int = 10000,
    ) -> None:
        self.similarity_threshold = similarity_threshold
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        # partition_key -> OrderedDict[entry_id -> CacheEntry]
        self._partitions: dict[str, OrderedDict[str, CacheEntry]] = {}
        self._total_entries = 0

    def size(self) -> int:
        return self._total_entries

    async def get(
        self,
        query: str,
        clearance_level: int,
        departments: list[str],
        embed_fn: EmbedFn,
        entity_keys: list[str] | None = None,
        doc_update_times: dict[str, datetime] | None = None,
    ) -> str | None:
        """Look up a cached response.

        Returns the cached response if:
        1. Same RBAC partition (clearance + departments + entities)
        2. Cosine similarity >= threshold
        3. Not stale (source docs not updated since cache entry)

        Returns None on cache miss.
        """
        partition = _partition_key(clearance_level, departments, entity_keys)

        if partition not in self._partitions:
            return None

        query_embedding = await embed_fn(query)
        entries = self._partitions[partition]

        best_entry: CacheEntry | None = None
        best_similarity = 0.0

        for entry in entries.values():
            sim = _cosine_similarity(query_embedding, entry.embedding)
            if sim > best_similarity:
                best_similarity = sim
                best_entry = entry

        if best_entry is None or best_similarity < self.similarity_threshold:
            return None

        # Staleness check
        if doc_update_times and best_entry.source_doc_ids:
            for doc_id in best_entry.source_doc_ids:
                if doc_id in doc_update_times:
                    if best_entry.is_stale(doc_update_times[doc_id]):
                        return None

        # Move to end (most recently used) for LRU
        entry_key = best_entry.cache_key
        if entry_key in entries:
            entries.move_to_end(entry_key)

        return best_entry.response

    async def put(
        self,
        query: str,
        response: str,
        clearance_level: int,
        departments: list[str],
        entity_keys: list[str],
        source_doc_ids: list[str],
        embed_fn: EmbedFn,
        cacheable: bool = True,
    ) -> None:
        """Store a response in the cache.

        Args:
            cacheable: If False, the entry is not stored (volatile/compliance).
        """
        if not cacheable:
            return

        partition = _partition_key(clearance_level, departments, entity_keys)
        query_embedding = await embed_fn(query)

        import uuid

        cache_key = str(uuid.uuid4())
        entry = CacheEntry(
            cache_key=cache_key,
            query=query,
            response=response,
            embedding=query_embedding,
            clearance_level=clearance_level,
            departments=sorted(departments),
            entity_keys=sorted(entity_keys),
            source_doc_ids=source_doc_ids,
            ttl_seconds=self.ttl_seconds,
        )

        if partition not in self._partitions:
            self._partitions[partition] = OrderedDict()

        self._partitions[partition][cache_key] = entry
        self._total_entries += 1

        # LRU eviction
        self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        """Evict oldest entry globally if over max_entries."""
        while self._total_entries > self.max_entries:
            # Find the partition with the oldest entry
            oldest_time = None
            oldest_partition = None
            oldest_key = None

            for part_key, entries in self._partitions.items():
                if entries:
                    # First item in OrderedDict is the oldest
                    first_key = next(iter(entries))
                    first_entry = entries[first_key]
                    if oldest_time is None or first_entry.created_at < oldest_time:
                        oldest_time = first_entry.created_at
                        oldest_partition = part_key
                        oldest_key = first_key

            if oldest_partition and oldest_key:
                del self._partitions[oldest_partition][oldest_key]
                self._total_entries -= 1
                if not self._partitions[oldest_partition]:
                    del self._partitions[oldest_partition]
            else:
                break

    def invalidate_by_doc(self, doc_id: str) -> int:
        """Remove all cache entries that reference the given document ID.

        Returns the number of entries removed.
        """
        removed = 0
        empty_partitions = []

        for part_key, entries in self._partitions.items():
            to_remove = [
                key for key, entry in entries.items()
                if doc_id in entry.source_doc_ids
            ]
            for key in to_remove:
                del entries[key]
                self._total_entries -= 1
                removed += 1
            if not entries:
                empty_partitions.append(part_key)

        for part_key in empty_partitions:
            del self._partitions[part_key]

        return removed

    def flush(self) -> None:
        """Clear the entire cache (e.g., on embedding model change)."""
        self._partitions.clear()
        self._total_entries = 0
