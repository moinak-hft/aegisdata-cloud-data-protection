"""Explainable pattern detectors for common sensitive-data indicators.

These rules complement the small text classifier. They are not a substitute
for a production DLP engine or a complete secret-scanning product.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from aegisdata.models import Match


@dataclass(frozen=True)
class Candidate:
    category: str
    rule_id: str
    severity: str
    confidence: float
    start: int
    end: int
    recommendation: str


RULES: tuple[tuple[str, str, str, float, re.Pattern[str], str], ...] = (
    (
        "cloud_credential",
        "aws_access_key_id",
        "Critical",
        0.99,
        re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
        "Revoke or rotate the exposed cloud credential, then review its access history.",
    ),
    (
        "cloud_credential",
        "github_token",
        "Critical",
        0.98,
        re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
        "Revoke or rotate the exposed token and review repository audit logs.",
    ),
    (
        "cloud_credential",
        "slack_token",
        "Critical",
        0.98,
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
        "Revoke or rotate the exposed token and review workspace audit logs.",
    ),
    (
        "cloud_credential",
        "private_key_block",
        "Critical",
        0.99,
        re.compile(
            r"-----BEGIN (?:(?:RSA|EC|OPENSSH) )?PRIVATE KEY-----"
            r"[\s\S]*?(?:-----END (?:(?:RSA|EC|OPENSSH) )?PRIVATE KEY-----|\Z)"
        ),
        "Remove the private key from the shared location and replace it with a managed secret.",
    ),
    (
        "cloud_credential",
        "secret_assignment",
        "Critical",
        0.90,
        re.compile(
            r"\b(?:api[_ -]?key|client[_ -]?secret|aws[_ -]?secret[_ -]?access[_ -]?key)"
            r"\b\s*[:=]\s*[\"']?([A-Za-z0-9/+=_-]{12,})",
            re.IGNORECASE,
        ),
        "Rotate the exposed secret and move it to a secrets manager with scoped access.",
    ),
    (
        "cloud_credential",
        "password_assignment",
        "High",
        0.88,
        re.compile(r"\b(?:password|passwd|pwd)\b\s*[:=]\s*[\"']?[^\s\"']{8,}", re.IGNORECASE),
        "Remove the password from the file and rotate it if it was a real credential.",
    ),
    (
        "payment_card",
        "payment_card_candidate",
        "High",
        0.92,
        re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        "Restrict access to the record and use a compliant payment token instead of card data.",
    ),
    (
        "government_id",
        "us_ssn_candidate",
        "High",
        0.86,
        re.compile(r"\b(?!000|666|9\d{2})\d{3}[- ]?(?!00)\d{2}[- ]?(?!0000)\d{4}\b"),
        "Limit access, confirm business need, and replace the identifier with a token where possible.",
    ),
    (
        "email_address",
        "email_address",
        "Medium",
        0.96,
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        "Minimize exposure and share only with people who need the contact data.",
    ),
    (
        "phone_number",
        "us_phone_candidate",
        "Medium",
        0.82,
        re.compile(r"(?<!\d)(?:\+1[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]?\d{3}[ .-]?\d{4}(?!\d)"),
        "Minimize exposure and share only with people who need the contact data.",
    ),
)


SEVERITY_RANK = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
PLACEHOLDER = {
    "cloud_credential": "[REDACTED:CREDENTIAL]",
    "payment_card": "[REDACTED:PAYMENT_CARD]",
    "government_id": "[REDACTED:GOVERNMENT_ID]",
    "email_address": "[REDACTED:EMAIL]",
    "phone_number": "[REDACTED:PHONE]",
}


def _passes_luhn(value: str) -> bool:
    digits = [int(char) for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def detect(text: str) -> tuple[Match, ...]:
    """Return explainable matches, masking every recognized value in evidence."""
    candidates: list[Candidate] = []
    for category, rule_id, severity, confidence, pattern, recommendation in RULES:
        for found in pattern.finditer(text):
            if rule_id == "payment_card_candidate" and not _passes_luhn(found.group(0)):
                continue
            candidates.append(
                Candidate(
                    category=category,
                    rule_id=rule_id,
                    severity=severity,
                    confidence=confidence,
                    start=found.start(),
                    end=found.end(),
                    recommendation=recommendation,
                )
            )

    # A phone expression can overlap a card number. Keep the higher-severity
    # card/credential match and suppress lower-priority overlapping matches.
    candidates.sort(
        key=lambda item: (
            -SEVERITY_RANK[item.severity],
            -(item.end - item.start),
            item.start,
        )
    )
    accepted: list[Candidate] = []
    for candidate in candidates:
        overlaps = any(candidate.start < item.end and item.start < candidate.end for item in accepted)
        if not overlaps:
            accepted.append(candidate)
    accepted.sort(key=lambda item: item.start)

    matches: list[Match] = []
    for candidate in accepted:
        matches.append(
            Match(
                category=candidate.category,
                rule_id=candidate.rule_id,
                severity=candidate.severity,
                confidence=candidate.confidence,
                start=candidate.start,
                end=candidate.end,
                # Store a placeholder and offsets rather than surrounding source
                # text; unrecognized adjacent secrets must not leak into SQLite.
                masked_evidence=(
                    f"{PLACEHOLDER[candidate.category]} at text offsets "
                    f"{candidate.start}-{candidate.end}"
                ),
                recommendation=candidate.recommendation,
            )
        )
    return tuple(matches)


def redact_text(text: str, matches: tuple[Match, ...]) -> str:
    """Return a redacted copy in memory; never changes or writes the source."""
    ranked = sorted(
        matches,
        key=lambda item: (-SEVERITY_RANK[item.severity], -(item.end - item.start), item.start),
    )
    accepted: list[Match] = []
    for item in ranked:
        if not any(item.start < prior.end and prior.start < item.end for prior in accepted):
            accepted.append(item)
    for item in sorted(accepted, key=lambda match: match.start, reverse=True):
        text = text[: item.start] + PLACEHOLDER[item.category] + text[item.end :]
    return text
