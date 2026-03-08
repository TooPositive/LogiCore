"""Seed mock documents into Qdrant for Phase 1 demo.

Usage: uv run python scripts/seed_documents.py

Requires:
- Qdrant running on localhost:6333
- Azure OpenAI credentials in .env
"""

import asyncio
from pathlib import Path

from apps.api.src.core.infrastructure.qdrant.client import get_qdrant_client
from apps.api.src.core.infrastructure.qdrant.collections import ensure_collection
from apps.api.src.core.rag.embeddings import get_embeddings
from apps.api.src.core.rag.ingestion import ingest_document

# Document manifest: (file_name, document_id, department_id, clearance_level)
DOCUMENTS = [
    ("DOC-SAFETY-001-quality-manual.txt", "DOC-SAFETY-001", "warehouse", 1),
    ("DOC-HR-002-exec-compensation.txt", "DOC-HR-002", "hr", 4),
    ("DOC-HR-003-driver-safety.txt", "DOC-HR-003", "warehouse", 1),
    ("DOC-HR-004-termination-procedures.txt", "DOC-HR-004", "hr", 3),
    ("DOC-LEGAL-001-pharmacorp-contract.txt", "DOC-LEGAL-001", "legal", 2),
    ("DOC-LEGAL-002-freshfoods-contract.txt", "DOC-LEGAL-002", "legal", 2),
]

DATA_DIR = Path(__file__).parent.parent / "data" / "mock-contracts"


async def main() -> None:
    client = await get_qdrant_client()
    await ensure_collection(client)

    embeddings = get_embeddings()

    total_chunks = 0
    for file_name, doc_id, dept, clearance in DOCUMENTS:
        file_path = DATA_DIR / file_name
        text = file_path.read_text(encoding="utf-8")

        result = await ingest_document(
            text=text,
            document_id=doc_id,
            department_id=dept,
            clearance_level=clearance,
            source_file=file_name,
            qdrant_client=client,
            embed_fn=embeddings.aembed_documents,
        )

        print(f"  {doc_id} ({dept}, clearance={clearance}): {result.chunks_created} chunks")
        total_chunks += result.chunks_created

    print(f"\nDone. {len(DOCUMENTS)} documents, {total_chunks} total chunks ingested.")


if __name__ == "__main__":
    asyncio.run(main())
