"""Local CPU embeddings via fastembed (ONNX Runtime — no PyTorch, small memory footprint)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Sequence
from typing import Protocol

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    model_name: str
    dim: int

    @property
    def loaded(self) -> bool: ...
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    def __init__(
        self,
        model_name: str,
        dim: int,
        batch_size: int = 16,
        threads: int = 2,
        cache_dir: str | None = None,
        query_prefix: str = "",
    ):
        self.model_name = model_name
        self.dim = dim
        self.batch_size = batch_size
        self.threads = threads
        self.cache_dir = cache_dir
        self.query_prefix = query_prefix
        self._model = None
        # One embedding call at a time: caps peak memory on a 4 GB host and keeps latency predictable.
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        from fastembed import TextEmbedding  # lazy: heavy import

        start = time.perf_counter()
        self._model = TextEmbedding(
            model_name=self.model_name,
            cache_dir=self.cache_dir,
            threads=self.threads,
            # ONNX Runtime's arena keeps peak memory forever; without it steady-state RSS roughly
            # halves (measured 443 MB -> 219 MB) at a negligible speed cost.
            enable_cpu_mem_arena=False,
        )
        probe = next(iter(self._model.embed(["warmup"])))
        if len(probe) != self.dim:
            raise RuntimeError(
                f"Embedding model {self.model_name} produces {len(probe)}-dim vectors but "
                f"EMBEDDING_DIM={self.dim}. Update the setting and the vector column."
            )
        logger.info("embedding model loaded in %.1fs", time.perf_counter() - start)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.load()
        with self._lock:
            return [v.tolist() for v in self._model.embed(list(texts), batch_size=self.batch_size)]

    def embed_query(self, text: str) -> list[float]:
        self.load()
        with self._lock:
            return next(iter(self._model.embed([self.query_prefix + text]))).tolist()
