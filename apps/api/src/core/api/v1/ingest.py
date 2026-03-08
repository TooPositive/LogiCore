"""POST /api/v1/ingest — document ingestion endpoint."""

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

from apps.api.src.core.domain.document import IngestRequest, IngestResponse
from apps.api.src.core.infrastructure.qdrant.client import get_qdrant_client
from apps.api.src.core.rag.embeddings import get_embeddings
from apps.api.src.core.rag.ingestion import ingest_document

router = APIRouter(prefix="/api/v1", tags=["ingest"])

# Allowlist directory for ingestion — only files under this path are accepted.
# In production, this would come from settings/env var.
ALLOWED_DATA_DIR = Path(__file__).resolve().parents[6] / "data"


@router.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest) -> IngestResponse:
    file_path = Path(request.file_path).resolve()

    # Zero-trust: reject paths outside the allowed data directory
    if not str(file_path).startswith(str(ALLOWED_DATA_DIR.resolve())):
        raise HTTPException(
            status_code=403,
            detail="File path outside allowed data directory",
        )

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {request.file_path}")

    text = file_path.read_text(encoding="utf-8")
    document_id = request.title or f"DOC-{uuid.uuid4().hex[:8].upper()}"

    qdrant = await get_qdrant_client()
    embeddings = get_embeddings()

    result = await ingest_document(
        text=text,
        document_id=document_id,
        department_id=request.department_id,
        clearance_level=request.clearance_level,
        source_file=request.file_path,
        qdrant_client=qdrant,
        embed_fn=embeddings.aembed_documents,
    )

    return result
