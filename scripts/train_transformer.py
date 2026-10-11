"""Fine-tune a local DistilBERT multi-label classifier on synthetic examples."""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.model_selection import GroupShuffleSplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "synthetic_multilabel.csv"
DEFAULT_OUTPUT = ROOT / "models" / "aegisdata-distilbert"
CATEGORIES = (
    "cloud_credential",
    "payment_card",
    "government_id",
    "email_address",
    "phone_number",
    "health_information",
    "financial_account",
)


def load_rows(path: Path) -> tuple[list[str], np.ndarray, np.ndarray]:
    texts: list[str] = []
    groups: list[str] = []
    labels: list[list[float]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        expected = {"text", "template_group", *(f"label_{category}" for category in CATEGORIES)}
        if not expected.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"Corpus columns missing: {sorted(expected - set(reader.fieldnames or []))}")
        for row in reader:
            text = row["text"].strip()
            if not text:
                continue
            texts.append(text)
            groups.append(row["template_group"])
            labels.append([float(row[f"label_{category}"]) for category in CATEGORIES])
    if len(texts) < 50 or len(set(groups)) < 20:
        raise ValueError("Corpus is too small. Regenerate it with scripts/generate_multilabel_corpus.py.")
    return texts, np.asarray(labels, dtype=np.float32), np.asarray(groups)


def split_by_template(
    groups: np.ndarray, labels: np.ndarray, seed: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Keep every variant of one source template entirely inside one split."""
    def has_every_class(indexes: np.ndarray) -> bool:
        if len(indexes) == 0:
            return False
        positive_counts = labels[indexes].sum(axis=0)
        return bool(np.all(positive_counts > 0) and np.all(positive_counts < len(indexes)))

    # Multi-label grouped stratification is not built into GroupShuffleSplit.
    # Try deterministic seeds until all categories and negatives appear in each
    # split, while still holding every template group out intact.
    for attempt in range(100):
        outer = GroupShuffleSplit(n_splits=1, test_size=0.20, random_state=seed + attempt)
        train_validation, test = next(outer.split(np.zeros(len(groups)), groups=groups))
        inner = GroupShuffleSplit(n_splits=1, test_size=0.20, random_state=seed + 1000 + attempt)
        train_local, validation_local = next(
            inner.split(np.zeros(len(train_validation)), groups=groups[train_validation])
        )
        train = train_validation[train_local]
        validation = train_validation[validation_local]
        if all(has_every_class(indexes) for indexes in (train, validation, test)):
            if (
                set(groups[train]).isdisjoint(groups[validation])
                and set(groups[train]).isdisjoint(groups[test])
                and set(groups[validation]).isdisjoint(groups[test])
            ):
                return train, validation, test
    raise ValueError(
        "Could not make train/validation/test splits with every label represented. "
        "Add more distinct template groups to the corpus."
    )


def evaluate_predictions(y_true: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score, precision_recall_fscore_support

    predicted = probabilities >= 0.5
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, predicted, average=None, zero_division=0
    )
    average_precision = average_precision_score(y_true, probabilities, average=None)
    false_positives = ((predicted == 1) & (y_true == 0)).sum(axis=0)
    negatives = (y_true == 0).sum(axis=0)
    per_category = {
        category: {
            "precision": round(float(precision[index]), 4),
            "recall": round(float(recall[index]), 4),
            "f1": round(float(f1[index]), 4),
            "average_precision": round(float(average_precision[index]), 4),
            "positive_examples": int(support[index]),
            "false_positives_per_1000_negative_examples": round(
                float(false_positives[index] / max(int(negatives[index]), 1) * 1000), 2
            ),
        }
        for index, category in enumerate(CATEGORIES)
    }
    micro = precision_recall_fscore_support(y_true, predicted, average="micro", zero_division=0)
    macro = precision_recall_fscore_support(y_true, predicted, average="macro", zero_division=0)
    return {
        "threshold": 0.5,
        "micro_precision": round(float(micro[0]), 4),
        "micro_recall": round(float(micro[1]), 4),
        "micro_f1": round(float(micro[2]), 4),
        "macro_precision": round(float(macro[0]), 4),
        "macro_recall": round(float(macro[1]), 4),
        "macro_f1": round(float(macro[2]), 4),
        "per_category": per_category,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--base-model", default="distilbert/distilbert-base-uncased")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=3e-5)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.epochs < 1 or args.batch_size < 1 or not 0 < args.learning_rate < 1:
        parser.error("epochs and batch-size must be positive; learning-rate must be between 0 and 1.")

    try:
        import torch
        from torch.utils.data import DataLoader, Dataset
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as error:
        raise SystemExit(
            "Transformer training packages are missing. Run `python -m pip install -r requirements-ml.txt`."
        ) from error

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    texts, labels, groups = load_rows(args.data)
    train_idx, validation_idx, test_idx = split_by_template(groups, labels, args.seed)
    for name, indexes in (("train", train_idx), ("validation", validation_idx), ("test", test_idx)):
        positives = labels[indexes].sum(axis=0)
        if np.any(positives == 0):
            missing = [CATEGORIES[i] for i in np.where(positives == 0)[0]]
            raise ValueError(f"{name} split has no positive examples for: {', '.join(missing)}")

    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    id2label = {index: category for index, category in enumerate(CATEGORIES)}
    label2id = {category: index for index, category in enumerate(CATEGORIES)}
    model = AutoModelForSequenceClassification.from_pretrained(
        args.base_model,
        num_labels=len(CATEGORIES),
        problem_type="multi_label_classification",
        id2label=id2label,
        label2id=label2id,
    )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    class EncodedRows(Dataset):
        def __init__(self, indexes: np.ndarray):
            selected_texts = [texts[index] for index in indexes]
            encoded = tokenizer(
                selected_texts,
                truncation=True,
                max_length=args.max_length,
                padding="max_length",
                return_tensors="pt",
            )
            self.input_ids = encoded["input_ids"]
            self.attention_mask = encoded["attention_mask"]
            self.labels = torch.tensor(labels[indexes], dtype=torch.float32)

        def __len__(self) -> int:
            return int(self.labels.shape[0])

        def __getitem__(self, index: int) -> dict[str, Any]:
            return {
                "input_ids": self.input_ids[index],
                "attention_mask": self.attention_mask[index],
                "labels": self.labels[index],
            }

    train_loader = DataLoader(EncodedRows(train_idx), batch_size=args.batch_size, shuffle=True)
    validation_loader = DataLoader(EncodedRows(validation_idx), batch_size=args.batch_size)
    test_loader = DataLoader(EncodedRows(test_idx), batch_size=args.batch_size)

    train_label_counts = labels[train_idx].sum(axis=0)
    negative_counts = len(train_idx) - train_label_counts
    pos_weight = torch.tensor(negative_counts / np.maximum(train_label_counts, 1), dtype=torch.float32, device=device)
    loss_function = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)

    def predict(loader: DataLoader) -> tuple[np.ndarray, np.ndarray]:
        model.eval()
        all_probs: list[np.ndarray] = []
        all_targets: list[np.ndarray] = []
        with torch.inference_mode():
            for batch in loader:
                targets = batch.pop("labels").cpu().numpy()
                inputs = {key: value.to(device) for key, value in batch.items()}
                probs = torch.sigmoid(model(**inputs).logits).cpu().numpy()
                all_probs.append(probs)
                all_targets.append(targets)
        return np.concatenate(all_targets), np.concatenate(all_probs)

    best_macro_f1 = -1.0
    best_weights: dict[str, Any] | None = None
    for epoch in range(args.epochs):
        model.train()
        running_loss = 0.0
        for batch in train_loader:
            targets = batch.pop("labels").to(device)
            inputs = {key: value.to(device) for key, value in batch.items()}
            optimizer.zero_grad(set_to_none=True)
            loss = loss_function(model(**inputs).logits, targets)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            running_loss += float(loss.item())
        y_validation, p_validation = predict(validation_loader)
        validation_metrics = evaluate_predictions(y_validation, p_validation)
        print(
            f"epoch {epoch + 1}/{args.epochs} "
            f"loss={running_loss / max(len(train_loader), 1):.4f} "
            f"validation_macro_f1={validation_metrics['macro_f1']:.4f}"
        )
        if validation_metrics["macro_f1"] > best_macro_f1:
            best_macro_f1 = validation_metrics["macro_f1"]
            best_weights = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}

    if best_weights is None:
        raise RuntimeError("Training did not produce a model checkpoint.")
    model.load_state_dict(best_weights)
    test_targets, test_probabilities = predict(test_loader)
    test_metrics = evaluate_predictions(test_targets, test_probabilities)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.output_dir, safe_serialization=True)
    tokenizer.save_pretrained(args.output_dir)

    metadata = {
        "model_name": "AegisData DistilBERT multi-label classifier",
        "base_model": args.base_model,
        "categories": list(CATEGORIES),
        "category_threshold": 0.5,
        "max_length": args.max_length,
        "document_chunk_chars": 900,
        "chunk_aggregation": "maximum category score across sampled overlapping chunks",
        "trained_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": str(args.data.name),
        "dataset_rows": len(texts),
        "unique_template_groups": int(len(set(groups))),
        "split_rows": {
            "train": int(len(train_idx)),
            "validation": int(len(validation_idx)),
            "test": int(len(test_idx)),
        },
        "evaluation_scope": "synthetic, template-group-held-out demo evaluation; not real-world effectiveness",
        "test_metrics": test_metrics,
    }
    (args.output_dir / "aegisdata_model.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2))
    print(f"Saved local model to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
