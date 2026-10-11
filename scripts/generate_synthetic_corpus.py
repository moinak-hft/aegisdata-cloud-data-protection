"""Generate a deterministic, non-sensitive corpus for the demo classifier."""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "synthetic_training.csv"

SENSITIVE_CONTEXTS = [
    "customer support exports include a contact email and service phone",
    "employee onboarding records contain a government tax identifier",
    "billing operations store payment card details for a customer",
    "the cloud deployment notes include an API credential",
    "a restricted customer profile contains personal contact information",
    "the incident attachment includes an access token and rotation notes",
    "finance records contain regulated payment account details",
    "the HR workspace stores private identity and payroll information",
    "a source configuration contains a password assignment",
    "the customer database backup includes personal identifiers",
    "the account recovery document contains a private key reference",
    "the sales export contains direct identifiers for named contacts",
    "the application log records an authentication secret",
    "a support ticket includes a user's email address and phone number",
    "the restricted spreadsheet stores cardholder data",
    "a cloud storage object exposes a credential in a configuration sample",
    "the data inventory lists a social security number field",
    "the employee file includes sensitive identity attributes",
    "the secrets rotation checklist references a client secret value",
    "the customer table contains a payment identifier and contact details",
]

GENERAL_CONTEXTS = [
    "the architecture overview describes service boundaries and request routing",
    "release notes summarize a user interface update and a bug fix",
    "the public product guide explains setup and troubleshooting steps",
    "the meeting agenda lists project milestones and owners",
    "a deployment checklist describes a rollback and health check procedure",
    "the engineering memo compares two database indexing strategies",
    "the support playbook explains how to reproduce a display issue",
    "the operations report summarizes system uptime and latency",
    "the documentation describes a public API endpoint and response format",
    "the sprint notes list completed tasks and upcoming work",
    "the training guide explains how to use the command line interface",
    "the product roadmap outlines features for a future release",
    "the code review discusses readability and maintainability improvements",
    "the service report summarizes routine maintenance activities",
    "the project plan tracks delivery dates and team responsibilities",
    "the quality report describes a reproducible interface defect",
    "the onboarding guide explains repository conventions and branch naming",
    "the research summary compares general software development approaches",
    "the test plan lists non-sensitive application behavior scenarios",
    "the incident review records a service restart and recovery timeline",
]

PREFIXES = [
    "Document context:",
    "Storage inventory note:",
    "Review summary:",
    "Cloud object description:",
    "Analyst note:",
]

SUFFIXES = [
    "The record is stored in a shared workspace.",
    "The item is part of a routine data inventory.",
    "The content is referenced by an internal workflow.",
    "The item was included in a scheduled review.",
    "The document is associated with an application service.",
]

SAFE_MARKERS = [
    "[EMAIL]", "[PHONE]", "[GOVERNMENT_ID]", "[PAYMENT_CARD]", "[API_SECRET]", "[PASSWORD]"
]


def generate(output_path: Path, rows_per_class: int, seed: int) -> int:
    if rows_per_class < 20:
        raise ValueError("Use at least 20 rows per class for a more useful demo holdout.")
    randomizer = random.Random(seed)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, int]] = []
    for label, contexts in ((1, SENSITIVE_CONTEXTS), (0, GENERAL_CONTEXTS)):
        for index in range(rows_per_class):
            context = contexts[index % len(contexts)]
            suffix = SUFFIXES[(index // len(contexts)) % len(SUFFIXES)]
            prefix = PREFIXES[(index + label) % len(PREFIXES)]
            if label:
                marker = SAFE_MARKERS[index % len(SAFE_MARKERS)]
                text = f"{prefix} {context}; example value {marker}. {suffix}"
            else:
                text = f"{prefix} {context}. {suffix}"
            # Vary order deterministically so the holdout is not just adjacent copies.
            rows.append((text, label))
    randomizer.shuffle(rows)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["text", "label"])
        writer.writerows(rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--rows-per-class", type=int, default=250)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    count = generate(args.output, args.rows_per_class, args.seed)
    print(f"Wrote {count} synthetic examples to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
