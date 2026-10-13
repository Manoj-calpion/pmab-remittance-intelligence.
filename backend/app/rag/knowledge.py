"""Local deterministic retrieval. Not a clinical embedding model.

PostgreSQL deployments can store the same vectors in pgvector. The local
embedder is a token hash so tests retrieve the relevant synthetic sample
without calling Amazon Bedrock. It must not be described as a production
semantic model.
"""

import hashlib
import math
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import KnowledgeChunk, KnowledgeDocument


def embed_text(text: str, dimensions: int = 256) -> list[float]:
    vector = [0.0] * dimensions
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=False))


def chunk_text(text: str, size: int = 700) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        paragraphs = [text]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 1 > size and current:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return chunks


def index_document(db: Session, document: KnowledgeDocument, settings: Settings | None = None) -> None:
    active = settings or get_settings()
    existing = db.scalar(select(KnowledgeChunk.id).where(KnowledgeChunk.document_id == document.id).limit(1))
    if existing is not None:
        return
    for index, content in enumerate(chunk_text(document.content_text)):
        db.add(
            KnowledgeChunk(
                document_id=document.id,
                chunk_index=index,
                content=content,
                embedding=embed_text(content, active.embedding_dimensions),
                token_count=len(content.split()),
            )
        )


def index_all_documents(db: Session, settings: Settings | None = None) -> None:
    for document in db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.is_active.is_(True))).all():
        index_document(db, document, settings)
    db.flush()


def search_knowledge(db: Session, query: str, settings: Settings | None = None, limit: int = 3) -> dict:
    active = settings or get_settings()
    if active.embedding_provider != "local_hash":
        raise RuntimeError(
            "EMBEDDING_PROVIDER is not local_hash. This build does not silently fall back when the configured embedding provider is unavailable."
        )
    index_all_documents(db, active)
    query_vector = embed_text(query, active.embedding_dimensions)
    scored = []
    rows = db.execute(select(KnowledgeChunk, KnowledgeDocument).join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)).all()
    for chunk, document in rows:
        if not document.is_active or not isinstance(chunk.embedding, list):
            continue
        scored.append((cosine(query_vector, chunk.embedding), chunk, document))
    scored.sort(key=lambda item: item[0], reverse=True)
    citations = []
    for score, chunk, document in scored[:limit]:
        citations.append(
            {
                "title": document.title,
                "document_type": document.document_type,
                "version": document.version,
                "source_label": document.source_label,
                "is_approved": document.is_approved,
                "score": round(score, 4),
                "excerpt": chunk.content[:400],
            }
        )
    approved = [item for item in citations if item["is_approved"]]
    return {
        "query": query,
        "citations": citations,
        "approved_citation_count": len(approved),
        "notice": "Only approved documents can support a payer-policy statement. Synthetic samples are not payer policy.",
    }
