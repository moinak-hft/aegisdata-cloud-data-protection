"""Optional local DistilBERT multi-label category model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aegisdata.config import MAX_TRANSFORMER_CHUNKS, TRANSFORMER_MODEL_DIR


def _chunks(text: str, *, width: int = 900, overlap: int = 120) -> list[str]:
    """Create overlapping character windows so long files are not silently truncated."""
    normalized = " ".join(text.split())
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + width)
        if end < len(normalized):
            boundary = normalized.rfind(" ", start + width // 2, end)
            if boundary > start:
                end = boundary
        chunks.append(normalized[start:end])
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap)

    if MAX_TRANSFORMER_CHUNKS <= 1:
        return [chunks[0]]
    if len(chunks) <= MAX_TRANSFORMER_CHUNKS:
        return chunks
    # Keep coverage across the entire document rather than only its first pages.
    indexes = [round(i * (len(chunks) - 1) / (MAX_TRANSFORMER_CHUNKS - 1)) for i in range(MAX_TRANSFORMER_CHUNKS)]
    return [chunks[index] for index in indexes]


class TransformerCategoryModel:
    """Loads saved weights from disk and performs local multi-label inference."""

    def __init__(self, model_dir: Path = TRANSFORMER_MODEL_DIR):
        if not (model_dir / "config.json").exists():
            raise FileNotFoundError(
                f"Transformer model metadata not found at {model_dir}. "
                "Run scripts/train_transformer.py first."
            )
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as error:
            raise RuntimeError(
                "The optional transformer dependencies are missing. Install them with "
                "`python -m pip install -r requirements-ml.txt`."
            ) from error

        self.torch = torch
        self.model_dir = model_dir
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            str(model_dir), local_files_only=True
        )
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)
        self.model.eval()
        self.labels = [
            self.model.config.id2label[index]
            for index in range(self.model.config.num_labels)
        ]
        metadata_path = model_dir / "aegisdata_model.json"
        self.metadata: dict[str, Any] = (
            json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        )

    def category_probabilities(self, text: str) -> dict[str, float]:
        chunks = _chunks(text)
        if not chunks:
            return {label: 0.0 for label in self.labels}

        probabilities: list[list[float]] = []
        for start in range(0, len(chunks), 8):
            batch = chunks[start : start + 8]
            encoded = self.tokenizer(
                batch,
                truncation=True,
                max_length=256,
                padding=True,
                return_tensors="pt",
            )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            with self.torch.inference_mode():
                logits = self.model(**encoded).logits
                probabilities.extend(self.torch.sigmoid(logits).cpu().tolist())

        # A high-scoring passage should surface at document level. These scores
        # are triage signals, not calibrated probabilities of a real breach.
        return {
            label: round(max(row[index] for row in probabilities), 4)
            for index, label in enumerate(self.labels)
        }

    @property
    def backend_name(self) -> str:
        return "TF-IDF baseline + local DistilBERT multi-label"
