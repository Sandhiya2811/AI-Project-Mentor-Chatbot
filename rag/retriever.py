"""Retrieval for the mentor: global knowledge base + the current project's own requirements."""
from __future__ import annotations

import threading

import numpy as np

from rag.knowledge_base import Chunk, KnowledgeBase, chunk_text
from rag.embeddings import EmbeddingError

_kb: KnowledgeBase | None = None
_kb_lock = threading.Lock()
_project_cache: dict[tuple, tuple[list[Chunk], np.ndarray]] = {}


def get_kb() -> KnowledgeBase:
    global _kb
    with _kb_lock:
        if _kb is None:
            _kb = KnowledgeBase()
        return _kb


def reset_kb() -> None:
    """Call after changing embedding settings."""
    global _kb
    with _kb_lock:
        _kb = None
    _project_cache.clear()


def _project_chunks(project: dict, tasks: list[dict], requirements: list[dict]) -> list[Chunk]:
    text = [f"# Project {project['title']}\nObjective: {project.get('objective', '')}\n"
            f"Language: {project.get('programming_language', '')}"]
    text += [f"## Requirement\n{r['name']}" for r in requirements if r["kind"] == "requirement"]
    for t in tasks:
        if t["status"] != "locked":  # never leak tasks the student has not reached yet
            text.append(f"## Task {t['position']}: {t['title']}\n{t['description']}\nExpected: {t['expected_output']}")
    return chunk_text("\n\n".join(text), "project requirements")


def retrieve(query: str, project: dict | None = None, tasks: list[dict] | None = None,
             requirements: list[dict] | None = None, k: int = 4) -> list[Chunk]:
    kb = get_kb()
    results = [c for c, _ in kb.search(query, k=k)]
    if project and tasks:
        sig = (project["id"], tuple((t["id"], t["status"]) for t in tasks), kb.embedder.signature)
        if sig not in _project_cache:
            chunks = _project_chunks(project, tasks, requirements or [])
            try:
                _project_cache[sig] = (chunks, kb.embedder.embed([c.text for c in chunks]))
            except EmbeddingError:
                _project_cache[sig] = (chunks, np.zeros((len(chunks), 1), dtype=np.float32))
        chunks, vecs = _project_cache[sig]
        try:
            q = kb.embedder.embed([query])[0]
            if vecs.shape[1] == q.shape[0] and len(chunks):
                top = np.argsort(-(vecs @ q))[:2]
                results += [chunks[i] for i in top if float(vecs[i] @ q) > 0.08]
        except EmbeddingError:
            pass
    return results


def format_chunks(chunks: list[Chunk], max_chars: int = 3200) -> str:
    out, used = [], 0
    for c in chunks:
        piece = f"[{c.source}] {c.text}"
        if used + len(piece) > max_chars:
            break
        out.append(piece)
        used += len(piece)
    return "\n---\n".join(out)
