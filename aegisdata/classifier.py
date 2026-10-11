"""Train a transparent document-level triage model on synthetic examples."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from aegisdata.config import TRAINING_DATA_PATH
from aegisdata.config import TRANSFORMER_MODEL_DIR
from aegisdata.transformer_model import TransformerCategoryModel


class ContextClassifier:
    """Binary context classifier; rules remain the source of exact-value matches."""

    def __init__(self, training_path: Path = TRAINING_DATA_PATH):
        self.training_path = training_path
        texts, labels = self._read_training_data(training_path)
        self.pipeline = Pipeline(
            steps=[
                (
                    "tfidf",
                    TfidfVectorizer(
                        lowercase=True,
                        ngram_range=(1, 2),
                        min_df=1,
                        max_features=20000,
                        sublinear_tf=True,
                    ),
                ),
                (
                    "classifier",
                    LogisticRegression(
                        max_iter=1000,
                        class_weight="balanced",
                        random_state=42,
                    ),
                ),
            ]
        )
        self.pipeline.fit(texts, labels)
        self.transformer: TransformerCategoryModel | None = None
        if (TRANSFORMER_MODEL_DIR / "config.json").exists():
            self.transformer = TransformerCategoryModel(TRANSFORMER_MODEL_DIR)

    @staticmethod
    def _read_training_data(path: Path) -> tuple[list[str], list[int]]:
        if not path.exists():
            raise FileNotFoundError(
                f"Training corpus not found: {path}. Run scripts/generate_synthetic_corpus.py first."
            )
        texts: list[str] = []
        labels: list[int] = []
        with path.open("r", encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                label = int(row["label"])
                if label not in (0, 1) or not row["text"].strip():
                    continue
                texts.append(row["text"].strip())
                labels.append(label)
        if len(set(labels)) != 2:
            raise ValueError("The training corpus must include both label 0 and label 1 examples.")
        return texts, labels

    def probability_sensitive(self, text: str) -> float:
        return self.predict_signals(text)[0]

    def predict_signals(self, text: str) -> tuple[float, dict[str, float]]:
        """Return the combined triage score and optional transformer categories."""
        probabilities = self.pipeline.predict_proba([text])[0]
        classes = list(self.pipeline.named_steps["classifier"].classes_)
        baseline_probability = float(probabilities[classes.index(1)])
        category_probabilities = (
            self.transformer.category_probabilities(text) if self.transformer is not None else {}
        )
        combined_probability = max([baseline_probability, *category_probabilities.values()])
        return combined_probability, category_probabilities

    @property
    def backend_name(self) -> str:
        return (
            self.transformer.backend_name
            if self.transformer is not None
            else "TF-IDF + logistic-regression baseline"
        )


def evaluate(training_path: Path = TRAINING_DATA_PATH) -> dict[str, Any]:
    """Report a reproducible stratified holdout evaluation for the synthetic corpus."""
    texts, labels = ContextClassifier._read_training_data(training_path)
    train_texts, test_texts, train_labels, test_labels = train_test_split(
        texts,
        labels,
        test_size=0.25,
        random_state=42,
        stratify=labels,
    )
    pipeline = Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    ngram_range=(1, 2),
                    min_df=1,
                    max_features=20000,
                    sublinear_tf=True,
                ),
            ),
            (
                "classifier",
                LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42),
            ),
        ]
    )
    pipeline.fit(train_texts, train_labels)
    predicted = pipeline.predict(test_texts)
    return {
        "evaluation_scope": "synthetic holdout only; not a production effectiveness claim",
        "examples_total": len(labels),
        "examples_train": len(train_labels),
        "examples_test": len(test_labels),
        "accuracy": round(float(accuracy_score(test_labels, predicted)), 4),
        "precision_sensitive": round(float(precision_score(test_labels, predicted, zero_division=0)), 4),
        "recall_sensitive": round(float(recall_score(test_labels, predicted, zero_division=0)), 4),
        "f1_sensitive": round(float(f1_score(test_labels, predicted, zero_division=0)), 4),
        "report": classification_report(test_labels, predicted, zero_division=0),
    }
