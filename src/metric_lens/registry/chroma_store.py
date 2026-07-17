from __future__ import annotations

from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from metric_lens.models import MetricDefinition

CHROMA_PATH = Path("chroma_db")
COLLECTION_NAME = "metrics"

_model: SentenceTransformer | None = None
_collection: chromadb.Collection | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _get_collection(path: Path = CHROMA_PATH) -> chromadb.Collection:
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(path))
        _collection = client.get_or_create_collection(
            COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def _to_text(metric: MetricDefinition) -> str:
    parts = [metric.name, metric.label, metric.formula_normalized]
    if metric.description:
        parts.append(metric.description)
    if metric.numerator:
        parts.append(f"분자 {metric.numerator}")
    if metric.denominator:
        parts.append(f"분모 {metric.denominator}")
    return " ".join(parts)


def _doc_id(metric: MetricDefinition) -> str:
    return f"{metric.name}__{metric.department}"


def add_metric(metric: MetricDefinition) -> None:
    col = _get_collection()
    text = _to_text(metric)
    emb = _get_model().encode(text).tolist()
    col.upsert(
        ids=[_doc_id(metric)],
        embeddings=[emb],
        documents=[text],
        metadatas=[{"name": metric.name, "department": metric.department}],
    )


def find_similar(metric: MetricDefinition, n_results: int = 5) -> list[dict]:
    col = _get_collection()
    if col.count() == 0:
        return []

    text = _to_text(metric)
    emb = _get_model().encode(text).tolist()

    try:
        results = col.query(
            query_embeddings=[emb],
            n_results=min(n_results, col.count()),
            where={"name": {"$ne": metric.name}},
        )
    except Exception:
        results = col.query(
            query_embeddings=[emb],
            n_results=min(n_results, col.count()),
        )

    candidates = []
    for i, meta in enumerate(results["metadatas"][0]):
        if meta["name"] == metric.name and meta["department"] == metric.department:
            continue
        candidates.append({
            "name": meta["name"],
            "department": meta["department"],
            "similarity": 1.0 - results["distances"][0][i],
        })
    return candidates
