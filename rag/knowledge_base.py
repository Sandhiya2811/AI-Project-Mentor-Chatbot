"""FAISS-backed knowledge base built from Markdown / text / PDF files in storage/knowledge/."""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from config import INDEX_DIR, KNOWLEDGE_DIR
from rag.embeddings import Embedder, EmbeddingError

try:
    import faiss  # type: ignore
except ImportError:  # numpy brute force is used instead
    faiss = None

log = logging.getLogger(__name__)
SUFFIXES = {".md", ".txt", ".pdf"}


@dataclass
class Chunk:
    text: str
    source: str
    title: str


def chunk_text(text: str, source: str, max_chars: int = 900) -> list[Chunk]:
    chunks: list[Chunk] = []
    doc_title = source
    sections = re.split(r"(?m)^(#{1,3} .+)$", text)
    heading, body = "", sections[0]
    pairs = [(heading, body)]
    for i in range(1, len(sections), 2):
        pairs.append((sections[i].lstrip("# ").strip(), sections[i + 1] if i + 1 < len(sections) else ""))
    for heading, body in pairs:
        if heading and not chunks and not any(h for h, _ in pairs[:1] if h):
            doc_title = doc_title if doc_title != source else heading
        paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        buf = ""
        for p in paras + [""]:
            if p and len(buf) + len(p) < max_chars:
                buf = f"{buf}\n\n{p}".strip()
                continue
            if buf:
                chunks.append(Chunk(f"{heading}\n{buf}".strip(), source, heading or doc_title))
            buf = p[:max_chars] if p else ""
    return chunks


def _read(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            return "\n\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
        except Exception:
            return ""
    return path.read_text(encoding="utf-8", errors="ignore")


class KnowledgeBase:
    def __init__(self) -> None:
        self.embedder = Embedder()
        self.chunks: list[Chunk] = []
        self.vectors: np.ndarray | None = None
        self.index = None
        self.ready = False
        self.error = ""
        self._lock = threading.Lock()

    # ---- build / load ----------------------------------------------------------------------
    def _manifest(self) -> dict:
        files = {p.relative_to(KNOWLEDGE_DIR).as_posix(): [p.stat().st_mtime_ns, p.stat().st_size]
                 for p in sorted(KNOWLEDGE_DIR.rglob("*")) if p.is_file() and p.suffix.lower() in SUFFIXES}
        return {"embedder": self.embedder.signature, "files": files}

    def ensure_index(self, force: bool = False) -> None:
        with self._lock:
            try:
                INDEX_DIR.mkdir(parents=True, exist_ok=True)
                manifest = self._manifest()
                mpath, cpath, vpath = INDEX_DIR / "manifest.json", INDEX_DIR / "chunks.json", INDEX_DIR / "vectors.npy"
                if (not force and mpath.exists() and cpath.exists() and vpath.exists()
                        and json.loads(mpath.read_text("utf-8")) == manifest):
                    self.chunks = [Chunk(**c) for c in json.loads(cpath.read_text("utf-8"))]
                    self.vectors = np.load(vpath)
                else:
                    self.chunks = []
                    for rel in manifest["files"]:
                        self.chunks += chunk_text(_read(KNOWLEDGE_DIR / rel), Path(rel).stem.replace("_", " "))
                    self.vectors = self.embedder.embed([c.text for c in self.chunks])
                    cpath.write_text(json.dumps([c.__dict__ for c in self.chunks], ensure_ascii=False), "utf-8")
                    np.save(vpath, self.vectors)
                    mpath.write_text(json.dumps(manifest), "utf-8")
                self._build_faiss()
                self.ready, self.error = True, ""
                log.info("Knowledge base ready: %d chunks (%s, %s)", len(self.chunks), self.embedder.signature,
                         "faiss" if self.index is not None else "numpy")
            except (EmbeddingError, OSError, ValueError) as exc:
                self.ready, self.error = False, str(exc)
                log.warning("Knowledge base unavailable: %s", exc)

    def _build_faiss(self) -> None:
        self.index = None
        if faiss is not None and self.vectors is not None and len(self.vectors):
            self.index = faiss.IndexFlatIP(self.vectors.shape[1])
            self.index.add(np.ascontiguousarray(self.vectors, dtype=np.float32))

    # ---- query -------------------------------------------------------------------------------
    def search(self, query: str, k: int = 4, min_score: float = 0.08) -> list[tuple[Chunk, float]]:
        if not self.ready or self.vectors is None or not len(self.vectors):
            return []
        try:
            q = self.embedder.embed([query])
        except EmbeddingError:
            return []
        k = min(k, len(self.chunks))
        if self.index is not None:
            scores, ids = self.index.search(np.ascontiguousarray(q, dtype=np.float32), k)
            pairs = list(zip(ids[0].tolist(), scores[0].tolist()))
        else:
            sims = (self.vectors @ q[0]).tolist()
            pairs = sorted(enumerate(sims), key=lambda x: -x[1])[:k]
        return [(self.chunks[i], s) for i, s in pairs if i >= 0 and s >= min_score]
