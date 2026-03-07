"""Compare chunking strategies on the 12-doc LogiCore corpus.

Measures: chunk count, avg chunk size, size variance, clause integrity
(does a full clause stay in one chunk?).

Usage:
    python scripts/benchmark_chunking.py [--data-dir data/mock-contracts/]

No external services required. Reads text files from disk.

Output: Formatted table comparing fixed-size vs semantic vs parent-child chunking.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.src.rag.chunking import (
    FixedSizeChunker,
    ParentChildChunker,
    SemanticChunker,
)
from apps.api.src.rag.embeddings import MockEmbedder
from tests.evaluation.corpus import CORPUS, CorpusDocument


def load_corpus_from_dir(data_dir: Path) -> list[CorpusDocument]:
    """Load .txt files from a directory. Falls back to inline corpus."""
    if not data_dir.exists():
        print(f"  [INFO] {data_dir} not found, using inline corpus")
        return CORPUS

    files = sorted(data_dir.glob("*.txt"))
    if not files:
        print(f"  [INFO] No .txt in {data_dir}, using inline corpus")
        return CORPUS

    docs = []
    for f in files:
        parts = f.stem.split("-")
        if len(parts) >= 3:
            doc_id = "-".join(parts[:3])
        else:
            doc_id = f.stem
        text = f.read_text(encoding="utf-8")
        docs.append(CorpusDocument(
            doc_id=doc_id,
            text=text,
            department="unknown",
            clearance_level=1,
        ))

    print(f"  [INFO] Loaded {len(docs)} documents from {data_dir}")
    return docs


# ---------------------------------------------------------------------------
# Clause integrity check
# ---------------------------------------------------------------------------


# Key clauses that should stay intact in chunks
KEY_CLAUSES = [
    "Penalty: EUR 500 per late shipment",
    "Maximum daily driving: 9 hours",
    "Severance formula: 0.5 months salary per year of service",
    "SLA: on-time delivery >= 98.5%",
    "Penalty: EUR 5,000 per compliance violation",
    "Annual value: EUR 2,100,000",
    "Probation period: 6 months",
    "Fire extinguisher inspection every 6 months",
]


def check_clause_integrity(chunks: list[str], clauses: list[str]) -> dict:
    """Check what fraction of key clauses stay within a single chunk."""
    total = 0
    intact = 0
    for clause in clauses:
        # Check if this clause exists in the full corpus
        found_in_corpus = False
        for doc in CORPUS:
            if clause in doc.text:
                found_in_corpus = True
                break
        if not found_in_corpus:
            continue

        total += 1
        # Check if any single chunk contains the entire clause
        for chunk in chunks:
            if clause in chunk:
                intact += 1
                break

    return {
        "total_clauses": total,
        "intact_clauses": intact,
        "integrity_rate": intact / total if total > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# Run benchmarks
# ---------------------------------------------------------------------------


def benchmark_strategy(
    strategy_name: str,
    chunker,
    corpus: list[CorpusDocument],
) -> dict:
    """Run a single chunking strategy and collect metrics."""
    all_chunks: list[str] = []
    chunk_counts: list[int] = []
    chunk_sizes: list[int] = []

    for doc in corpus:
        results = chunker.chunk(doc.text)
        chunks = [r.content for r in results]
        all_chunks.extend(chunks)
        chunk_counts.append(len(chunks))
        chunk_sizes.extend(len(c) for c in chunks)

    integrity = check_clause_integrity(all_chunks, KEY_CLAUSES)

    return {
        "strategy": strategy_name,
        "total_chunks": len(all_chunks),
        "avg_chunks_per_doc": statistics.mean(chunk_counts) if chunk_counts else 0,
        "avg_chunk_size": statistics.mean(chunk_sizes) if chunk_sizes else 0,
        "min_chunk_size": min(chunk_sizes) if chunk_sizes else 0,
        "max_chunk_size": max(chunk_sizes) if chunk_sizes else 0,
        "size_stddev": statistics.stdev(chunk_sizes) if len(chunk_sizes) > 1 else 0,
        "clause_integrity": integrity["integrity_rate"],
        "clauses_intact": f"{integrity['intact_clauses']}/{integrity['total_clauses']}",
    }


def main():
    parser = argparse.ArgumentParser(description="Compare chunking strategies")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/mock-contracts/"),
        help="Directory containing .txt documents",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Save results to JSON file",
    )
    args = parser.parse_args()

    print("=" * 78)
    print("CHUNKING STRATEGY COMPARISON")
    print("=" * 78)

    corpus = load_corpus_from_dir(args.data_dir)
    if not corpus:
        corpus = CORPUS
        print("  Using inline 12-doc corpus")
    print(f"  Corpus size: {len(corpus)} documents")
    print()

    # Mock embedder for semantic chunking
    embedder = MockEmbedder(dimensions=128)

    def sync_embed(texts: list[str]) -> list[list[float]]:
        """Synchronous wrapper for MockEmbedder."""
        return [embedder._hash_to_vector(t) for t in texts]

    # Configure strategies
    strategies = [
        ("Fixed-size (512, overlap=50)", FixedSizeChunker(chunk_size=512, overlap=50)),
        ("Fixed-size (256, overlap=25)", FixedSizeChunker(chunk_size=256, overlap=25)),
        (
            "Semantic (threshold=0.5)",
            SemanticChunker(
                similarity_threshold=0.5,
                min_chunk_size=100,
                max_chunk_size=2000,
                embed_fn=sync_embed,
            ),
        ),
        (
            "Semantic (threshold=0.3)",
            SemanticChunker(
                similarity_threshold=0.3,
                min_chunk_size=100,
                max_chunk_size=2000,
                embed_fn=sync_embed,
            ),
        ),
        ("Parent-Child (default)", ParentChildChunker()),
        (
            "Parent-Child (min_child=30)",
            ParentChildChunker(min_child_size=30),
        ),
    ]

    results = []
    for name, chunker in strategies:
        result = benchmark_strategy(name, chunker, corpus)
        results.append(result)

    # Print table
    headers = [
        "Strategy",
        "Chunks",
        "Avg/Doc",
        "Avg Size",
        "Min",
        "Max",
        "StdDev",
        "Clause",
    ]
    widths = [30, 8, 8, 10, 6, 6, 8, 12]

    header_line = ""
    for h, w in zip(headers, widths):
        header_line += f"  {h:<{w}}"
    print(header_line)
    print("  " + "-" * (sum(widths) + len(widths) * 2))

    for r in results:
        line = (
            f"  {r['strategy']:<30}"
            f"  {r['total_chunks']:<8}"
            f"  {r['avg_chunks_per_doc']:<8.1f}"
            f"  {r['avg_chunk_size']:<10.0f}"
            f"  {r['min_chunk_size']:<6}"
            f"  {r['max_chunk_size']:<6}"
            f"  {r['size_stddev']:<8.0f}"
            f"  {r['clauses_intact']:<12}"
        )
        print(line)

    # Architect verdict
    print()
    print("  ARCHITECT ANALYSIS:")
    print("  " + "-" * 60)

    best_integrity = max(results, key=lambda r: r["clause_integrity"])
    worst_integrity = min(results, key=lambda r: r["clause_integrity"])

    print(f"  Best clause integrity: {best_integrity['strategy']}")
    print(f"    -> {best_integrity['clauses_intact']} key clauses preserved")
    print(f"  Worst clause integrity: {worst_integrity['strategy']}")
    print(f"    -> {worst_integrity['clauses_intact']} key clauses preserved")
    print()
    print("  DECISION: Clause integrity determines chunking strategy choice.")
    print("  A strategy that splits 'Penalty: EUR 5,000 per compliance violation'")
    print("  across two chunks loses critical information for RAG retrieval.")
    print("  The cost of broken clauses: the LLM gets partial context,")
    print("  generates wrong answers, and the user makes a wrong decision.")
    print()
    print("  RECOMMENDATION: Use the strategy with highest clause integrity")
    print("  for contract/legal documents. Switch to smaller fixed-size chunks")
    print("  only when documents are >10 pages and retrieval latency matters.")
    print("=" * 78)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n  Results saved to {args.output_json}")


if __name__ == "__main__":
    main()
