"""Embeddings locales via ONNX (default del producto: offline, sin API, reproducible).

Modelo por defecto: `paraphrase-multilingual-MiniLM-L12-v2` (384 dims, mean pooling).
Es multilingue por diseno, que es el requisito que la medicion de F0/F1 puso en primer plano:
las preguntas se hacen en espanol y el codigo esta en ingles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

DEFAULT_MODEL_DIR = ".models/multilingual-minilm"
DEFAULT_EMBEDDER_ID = "onnx-minilm-multilingual-384"
MODEL_ENV_VAR = "DOCU_MODEL_DIR"


def resolve_model_dir(*roots: Path | str | None) -> Path | None:
    """Busca el modelo ONNX sin obligar a configurarlo.

    Orden: variable de entorno, `.models/` del proyecto, `.models/` del workspace, directorio
    actual. Devolver `None` es un caso normal: el motor sigue funcionando sin canal denso.
    """
    import os

    from_env = os.environ.get(MODEL_ENV_VAR)
    if from_env and (Path(from_env) / "model.onnx").exists():
        return Path(from_env)
    candidates = [Path(root) / DEFAULT_MODEL_DIR for root in roots if root is not None]
    candidates.append(Path(os.getcwd()) / DEFAULT_MODEL_DIR)
    for candidate in candidates:
        if (candidate / "model.onnx").exists() and (candidate / "tokenizer.json").exists():
            return candidate
    return None


@dataclass
class OnnxEmbedder:
    """Implementa el puerto `Embedder`. Carga perezosa: importar el modulo no exige onnxruntime."""

    model_dir: Path | str = DEFAULT_MODEL_DIR
    embedder_id: str = DEFAULT_EMBEDDER_ID
    max_length: int = 256
    batch_size: int = 16
    _session: object | None = None
    _tokenizer: object | None = None
    _input_names: tuple[str, ...] = ()
    _dim: int = 384

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def available(self) -> bool:
        return (Path(self.model_dir) / "model.onnx").exists() and (
            Path(self.model_dir) / "tokenizer.json"
        ).exists()

    def _load(self) -> None:
        if self._session is not None:
            return
        if not self.available:
            raise FileNotFoundError(
                f"modelo ONNX no encontrado en {self.model_dir!r}; descarga tokenizer.json y model.onnx"
            )
        import onnxruntime as ort
        from tokenizers import Tokenizer

        directory = Path(self.model_dir)
        tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        tokenizer.enable_truncation(max_length=self.max_length)
        tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        session = ort.InferenceSession(
            str(directory / "model.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self._tokenizer = tokenizer
        self._session = session
        self._input_names = tuple(item.name for item in session.get_inputs())

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self._load()
        assert self._tokenizer is not None and self._session is not None
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            encodings = self._tokenizer.encode_batch(batch)
            feed: dict[str, object] = {
                "input_ids": [enc.ids for enc in encodings],
                "attention_mask": [enc.attention_mask for enc in encodings],
            }
            if "token_type_ids" in self._input_names:
                feed["token_type_ids"] = [enc.type_ids for enc in encodings]
            outputs = self._session.run(None, feed)
            hidden = outputs[0]
            vectors.extend(
                _mean_pool_normalize(hidden[index], encodings[index].attention_mask)
                for index in range(len(batch))
            )
        return vectors


def _mean_pool_normalize(token_vectors: Sequence[Sequence[float]], mask: Sequence[int]) -> list[float]:
    """Media enmascarada + normalizacion L2: coseno equivalente a producto escalar."""
    dim = len(token_vectors[0])
    total = [0.0] * dim
    count = 0
    for vector, flag in zip(token_vectors, mask):
        if not flag:
            continue
        count += 1
        for index, value in enumerate(vector):
            total[index] += value
    if count == 0:
        return total
    pooled = [value / count for value in total]
    norm = math.sqrt(sum(value * value for value in pooled)) or 1.0
    return [value / norm for value in pooled]


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Similitud coseno; ambos lados vienen normalizados, pero se protege el caso general."""
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0
