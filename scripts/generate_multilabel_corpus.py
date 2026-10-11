"""Build a reproducible, entirely synthetic multi-label document corpus."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "synthetic_multilabel.csv"

CATEGORIES = (
    "cloud_credential",
    "payment_card",
    "government_id",
    "email_address",
    "phone_number",
    "health_information",
    "financial_account",
)

PREFIXES = (
    "Storage review:",
    "Data inventory:",
    "Analyst summary:",
    "Document excerpt:",
    "Cloud object note:",
    "Security review:",
)
SUFFIXES = (
    "The sample contains fictional information for a local security exercise.",
    "This record is synthetic and must not be treated as real customer data.",
    "The note is included to demonstrate document-level classification.",
    "No external service receives the content during this exercise.",
)
VALUES = ("customer portal", "billing service", "support workspace", "staff directory", "claims archive")

SINGLE_LABEL_TEMPLATES: dict[str, tuple[str, ...]] = {
    "cloud_credential": (
        "A deployment file stores an API token [SYNTHETIC_TOKEN] used by the {system}.",
        "The service configuration includes a client secret placeholder [SYNTHETIC_SECRET].",
        "An access key is present in the cloud integration notes and should be rotated.",
        "The incident record describes an exposed authentication credential in a config file.",
        "A private key placeholder [SYNTHETIC_PRIVATE_KEY] appears in the automation bundle.",
        "The operations export contains a password field for the {system}.",
        "The repository scan found a synthetic bearer token in a deployment manifest.",
        "A cloud account recovery note refers to a credential stored in a shared folder.",
        "The support attachment contains a test secret assignment for a service account.",
        "A CI pipeline variable contains a synthetic access token that needs rotation.",
        "The infrastructure inventory points to a private key file used by a workload.",
        "A configuration sample includes a test password and a note about secret rotation.",
    ),
    "payment_card": (
        "The transaction export includes a cardholder account and payment card details.",
        "A billing record stores a synthetic card number placeholder [SYNTHETIC_CARD].",
        "The checkout support file contains payment card data for a customer order.",
        "The finance attachment contains cardholder records and a payment authorization reference.",
        "A compliance review found payment card fields in the order archive.",
        "The merchant report includes a synthetic card account used in a test transaction.",
        "The customer invoice export contains a payment card number field.",
        "The settlement file refers to cardholder data retained by the billing system.",
        "A support case includes payment details associated with a returned purchase.",
        "The account record stores card expiry and a synthetic payment number.",
        "A test dataset describes payment card data collected during checkout.",
        "The billing workspace contains cardholder information that needs restricted access.",
    ),
    "government_id": (
        "The employee onboarding file contains a government tax identifier field.",
        "A benefits record stores a synthetic national identity number placeholder.",
        "The customer profile includes a social security number field for verification.",
        "The claims attachment contains a government-issued identity number.",
        "The HR export includes a passport identifier and date of birth field.",
        "An account recovery file references a driver's license identifier.",
        "The payroll archive contains a synthetic taxpayer identification record.",
        "The identity verification note includes a government ID value placeholder.",
        "A benefits spreadsheet lists national identity data for enrolled employees.",
        "The customer application asks for a government-issued identification number.",
        "The onboarding document includes a synthetic social insurance identifier.",
        "A restricted identity record stores a passport number and issuing country.",
    ),
    "email_address": (
        "The support export includes the customer's direct contact email address.",
        "A user profile stores an email address for account recovery.",
        "The sales list contains named contacts and their business email addresses.",
        "A service ticket records a customer's private email contact information.",
        "The staff directory includes work email addresses linked to employee names.",
        "A membership export stores an email address for each individual account.",
        "The notification log contains recipient email details for an account holder.",
        "A customer record lists a personal email address and communication preference.",
        "The registration file contains user email identifiers and consent status.",
        "A contact spreadsheet maps account owners to their email addresses.",
        "The profile backup includes a synthetic email field for each user.",
        "A help desk attachment contains the email address of a named customer.",
    ),
    "phone_number": (
        "The customer support export contains a direct phone number for callback.",
        "A user profile stores a personal telephone number for verification.",
        "The staff directory links employee names to mobile phone details.",
        "The appointment report includes patient phone numbers and contact times.",
        "A service ticket records a customer telephone number for follow-up.",
        "The account recovery file uses a phone number as a verification contact.",
        "A membership list contains mobile numbers associated with individual accounts.",
        "The delivery export includes a recipient telephone number.",
        "A synthetic phone field appears in the customer profile backup.",
        "The HR contact sheet contains personal telephone information.",
        "An incident note includes a callback phone number for the reporting user.",
        "The reservation system stores phone contact details for each guest.",
    ),
    "health_information": (
        "The clinical summary links a patient's diagnosis with their treatment plan.",
        "A benefits attachment lists a member's medication and care history.",
        "The claims record contains a synthetic diagnosis code and patient visit details.",
        "The wellness file stores an individual's medical condition and appointment notes.",
        "A restricted case report includes a patient's laboratory results.",
        "The health plan export contains treatment history for enrolled members.",
        "A care coordination note records symptoms and a clinician's assessment.",
        "The medical archive describes an individual's prescription and diagnosis.",
        "The insurance document links a member identity to a health claim.",
        "A synthetic patient record includes procedure and recovery information.",
        "The clinic attachment contains medical history and provider notes.",
        "A care record associates a patient with a sensitive health condition.",
    ),
    "financial_account": (
        "The treasury export contains bank account and routing information.",
        "A customer finance record stores an account balance and transaction history.",
        "The payroll file includes bank deposit details for employees.",
        "A loan application contains an individual's income and financial account data.",
        "The reconciliation report lists account numbers and payment transfers.",
        "A synthetic banking record includes an account identifier and balance.",
        "The finance archive stores wire transfer instructions for a business account.",
        "A billing profile contains bank debit details associated with a customer.",
        "The investment summary describes an individual's portfolio and holdings.",
        "The accounts payable file includes supplier bank account information.",
        "A credit review note contains financial account and repayment details.",
        "The payment reconciliation includes customer bank transfer references.",
    ),
}

MULTI_LABEL_TEMPLATES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("email_address", "phone_number"), "The customer profile stores an email contact and callback phone number."),
    (("cloud_credential", "government_id"), "The onboarding bundle includes a service credential and an identity verification field."),
    (("payment_card", "email_address"), "The billing export links payment card details with a customer's email contact."),
    (("health_information", "government_id"), "The patient file links a government identity record to diagnosis and treatment notes."),
    (("financial_account", "government_id"), "The loan archive combines bank account details with a government identity field."),
    (("cloud_credential", "email_address"), "The support attachment contains a synthetic API secret and user email address."),
    (("payment_card", "phone_number"), "The checkout record includes cardholder payment details and a telephone contact."),
    (("financial_account", "email_address"), "The customer finance export associates bank transfer data with an email address."),
    (("health_information", "phone_number"), "The clinic appointment file includes a patient's care note and phone contact."),
    (("cloud_credential", "financial_account"), "A restricted service configuration and treasury export contain credential and bank account context."),
)

NEGATIVE_TEMPLATES = (
    "The architecture guide describes public request routing and service boundaries.",
    "Release notes summarize a user interface improvement and routine bug fixes.",
    "The operations memo explains backup rotation without including credentials or customer records.",
    "The public setup guide documents an API endpoint but contains no token or secret value.",
    "The project plan tracks milestones, team owners, and delivery dates.",
    "The test plan uses placeholders and does not include real personal or financial data.",
    "The meeting notes discuss database indexing and query performance.",
    "The deployment checklist describes health checks and rollback procedures.",
    "A public product page explains how to configure notification preferences.",
    "The maintenance report records uptime and latency for a test service.",
    "The developer guide explains how to name variables and organize source files.",
    "The design review compares navigation layouts and accessibility improvements.",
    "A synthetic security policy explains that passwords should never be stored in source code.",
    "The training document teaches how to identify fake card and identity values in a mock dataset.",
    "The system inventory lists software versions and non-sensitive service owners.",
    "The incident review records a service restart and a successful recovery timeline.",
    "A public FAQ explains how customers update their profile settings.",
    "The analytics summary contains aggregate counts with no individual records.",
    "The engineering note compares email delivery providers without listing recipients.",
    "The project retrospective records lessons about testing and documentation quality.",
    "The open-source README includes installation commands and feature descriptions.",
    "A product roadmap outlines planned improvements for the next release.",
    "The code review discusses readability, maintainability, and error handling.",
    "The storage guide describes encryption concepts without showing actual secret values.",
)


def build_rows(variants: int) -> list[dict[str, str]]:
    if variants < 2:
        raise ValueError("Use at least two variants per template group for grouped evaluation.")
    rows: list[dict[str, str]] = []
    group_index = 0

    def add_group(group_id: str, context: str, labels: set[str]) -> None:
        nonlocal group_index
        for variant in range(variants):
            prefix = PREFIXES[(group_index + variant) % len(PREFIXES)]
            suffix = SUFFIXES[(group_index + variant * 2) % len(SUFFIXES)]
            system = VALUES[(group_index + variant) % len(VALUES)]
            row = {
                "template_group": group_id,
                "text": f"{prefix} {context.format(system=system)} {suffix}",
            }
            row.update({f"label_{category}": "1" if category in labels else "0" for category in CATEGORIES})
            rows.append(row)
        group_index += 1

    for category, contexts in SINGLE_LABEL_TEMPLATES.items():
        for index, context in enumerate(contexts):
            add_group(f"single-{category}-{index:02d}", context, {category})

    for index, (labels, context) in enumerate(MULTI_LABEL_TEMPLATES):
        add_group(f"multi-{index:02d}", context, set(labels))

    for index, context in enumerate(NEGATIVE_TEMPLATES):
        add_group(f"negative-{index:02d}", context, set())
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--variants", type=int, default=4)
    args = parser.parse_args()
    rows = build_rows(args.variants)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    columns = ["template_group", "text", *(f"label_{category}" for category in CATEGORIES)]
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} synthetic rows across {len(set(row['template_group'] for row in rows))} template groups to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
