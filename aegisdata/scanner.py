"""Orchestrate extraction, pattern detection, model triage, and risk scoring."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from aegisdata.classifier import ContextClassifier
from aegisdata.config import MAX_FILE_BYTES
from aegisdata.detectors import detect
from aegisdata.extractors import extract_text
from aegisdata.models import ScanReport


CATEGORY_POINTS = {
    "cloud_credential": 100,
    "payment_card": 92,
    "government_id": 88,
    "email_address": 52,
    "phone_number": 48,
    "health_information": 88,
    "financial_account": 82,
}


def _risk_score(
    categories: tuple[str, ...],
    model_probability: float,
    model_category_probabilities: dict[str, float],
) -> int:
    rule_score = max((CATEGORY_POINTS.get(category, 0) for category in categories), default=0)
    distinct_bonus = min(12, max(0, len(set(categories)) - 1) * 4)
    model_bonus = round(model_probability * 8) if rule_score else round(model_probability * 65)
    model_category_score = max(
        (round(CATEGORY_POINTS.get(category, 50) * probability * 0.8)
         for category, probability in model_category_probabilities.items()),
        default=0,
    )
    return min(100, max(rule_score + distinct_bonus + model_bonus, model_category_score))


def _sensitivity(risk_score: int, model_probability: float) -> str:
    if risk_score >= 90:
        return "Critical"
    if risk_score >= 70:
        return "High"
    if risk_score >= 45 or model_probability >= 0.72:
        return "Medium"
    return "Low"


def _recommendation(
    categories: tuple[str, ...],
    model_probability: float,
    model_category_probabilities: dict[str, float],
) -> str:
    priority = ("cloud_credential", "payment_card", "government_id", "email_address", "phone_number")
    if categories:
        first = next((category for category in priority if category in categories), categories[0])
        recommendation_by_category = {
            "cloud_credential": "Rotate exposed credentials; restrict access and review audit logs.",
            "payment_card": "Restrict access and replace card data with a compliant payment token.",
            "government_id": "Restrict access and replace the identifier with a token where possible.",
            "email_address": "Minimize exposure and confirm that each recipient needs the contact data.",
            "phone_number": "Minimize exposure and confirm that each recipient needs the contact data.",
        }
        return recommendation_by_category[first]
    if model_category_probabilities:
        category, probability = max(model_category_probabilities.items(), key=lambda item: item[1])
        if probability >= 0.5:
            return (
                f"Review the passage the model categorized as {category.replace('_', ' ')}; "
                "this is a contextual suggestion, not an exact-value match."
            )
    if model_probability >= 0.72:
        return "Review the document context; the model found sensitive-data language without an exact rule match."
    return "No action suggested by this prototype; review sampling and data-source coverage before relying on it."


def scan_bytes(
    filename: str,
    content: bytes,
    classifier: ContextClassifier,
    *,
    source: str | None = None,
) -> tuple[ScanReport, str]:
    """Scan one in-memory object. The returned text is only for caller-side redaction."""
    if len(content) > MAX_FILE_BYTES:
        raise ValueError(f"File is {len(content)} bytes; configured limit is {MAX_FILE_BYTES}.")
    text = extract_text(filename, content)
    matches = detect(text)
    if hasattr(classifier, "predict_signals"):
        model_probability, model_category_probabilities = classifier.predict_signals(text)
    else:
        model_probability = classifier.probability_sensitive(text)
        model_category_probabilities = {}
    categories = tuple(sorted({match.category for match in matches}))
    risk_score = _risk_score(categories, model_probability, model_category_probabilities)
    report = ScanReport(
        source=source or filename,
        sha256=hashlib.sha256(content).hexdigest(),
        byte_count=len(content),
        scanned_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        sensitivity=_sensitivity(risk_score, model_probability),
        model_probability=round(model_probability, 4),
        risk_score=risk_score,
        categories=categories,
        recommendation=_recommendation(categories, model_probability, model_category_probabilities),
        matches=matches,
        model_backend=getattr(classifier, "backend_name", "Unknown classifier"),
        model_category_probabilities=tuple(sorted(model_category_probabilities.items())),
    )
    return report, text
