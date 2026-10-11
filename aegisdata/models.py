"""Small typed objects shared by the scanner, storage layer, and UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Match:
    category: str
    rule_id: str
    severity: str
    confidence: float
    start: int
    end: int
    masked_evidence: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScanReport:
    source: str
    sha256: str
    byte_count: int
    scanned_at_utc: str
    sensitivity: str
    model_probability: float
    risk_score: int
    categories: tuple[str, ...]
    recommendation: str
    matches: tuple[Match, ...]
    model_backend: str = "TF-IDF + logistic-regression baseline"
    model_category_probabilities: tuple[tuple[str, float], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "sha256": self.sha256,
            "byte_count": self.byte_count,
            "scanned_at_utc": self.scanned_at_utc,
            "sensitivity": self.sensitivity,
            "model_probability": self.model_probability,
            "risk_score": self.risk_score,
            "categories": list(self.categories),
            "recommendation": self.recommendation,
            "matches": [match.to_dict() for match in self.matches],
            "model_backend": self.model_backend,
            "model_category_probabilities": dict(self.model_category_probabilities),
        }
