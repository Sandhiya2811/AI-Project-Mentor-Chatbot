"""Pluggable text embeddings.

hash                  - default; dependency-free lexical hashing vectors (works offline, English keywords)
sentence-transformers - local multilingual semantic model (pip install sentence-transformers)
ollama                - /api/embed on your Ollama server (e.g. nomic-embed-text, bge-m3)
"""
from __future__ import annotations

import logging
import re
import zlib

import numpy as np
import requests

from config import settings

log = logging.getLogger(__name__)
DIM = 4096
STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "is", "it", "for", "on", "with", "as", "this", "that", "be",
        "are", "you", "your", "i", "we", "can", "how", "what", "do", "does"}


class EmbeddingError(Exception):
    pass


def _hash_embed(texts: list[str]) -> np.ndarray:
    out = np.zeros((len(texts), DIM), dtype=np.float32)
    for row, text in enumerate(texts):
        toks = [t for t in re.findall(r"[^\W_]+", text.lower()) if t not in STOP and len(t) > 1]
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        for f in feats:
            h = zlib.crc32(f.encode("utf-8"))
            out[row, h % DIM] += 1.0
    out = np.log1p(out)
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return out / norms


class Embedder:
    def __init__(self) -> None:
        self.backend = settings.get("EMBEDDING_BACKEND") or "hash"
        self.model = settings.get("EMBEDDING_MODEL")
        self._st = None
        if self.backend == "sentence-transformers":
            try:
                from sentence_transformers import SentenceTransformer
                self.model = self.model or "paraphrase-multilingual-MiniLM-L12-v2"
                self._st = SentenceTransformer(self.model)
            except Exception as exc:  # not installed / download failed
                log.warning("sentence-transformers unavailable (%s) - falling back to hash embeddings", exc)
                self.backend, self.model = "hash", ""
        elif self.backend == "ollama":
            self.model = self.model or "nomic-embed-text"
        else:
            self.backend = "hash"

    @property
    def signature(self) -> str:
        return f"{self.backend}:{self.model}"

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, DIM), dtype=np.float32)
        if self.backend == "sentence-transformers":
            return np.asarray(self._st.encode(texts, normalize_embeddings=True), dtype=np.float32)
        if self.backend == "ollama":
            base = settings.provider_value("base_url") if settings.get("LLM_PROVIDER") == "ollama" else "http://localhost:11434"
            try:
                r = requests.post(f"{base}/api/embed", json={"model": self.model, "input": texts}, timeout=120)
                r.raise_for_status()
                vecs = np.asarray(r.json()["embeddings"], dtype=np.float32)
            except Exception as exc:
                raise EmbeddingError(f"Ollama embeddings failed: {exc}") from exc
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms[norms == 0] = 1
            return vecs / norms
        return _hash_embed(texts)
