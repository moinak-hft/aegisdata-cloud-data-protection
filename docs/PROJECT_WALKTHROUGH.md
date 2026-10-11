# AegisData project walkthrough

This guide explains the project as a security data pipeline so you can describe each design choice in a demo or interview.

## Goal

Cloud storage can contain personal data or credentials in files that were never intended to be public or broadly shared. AegisData demonstrates a small discovery-and-triage loop: inspect an authorized source, identify suspicious content, produce evidence that does not repeat the value, prioritize the file, and retain enough metadata to review the scan later.

The project is deliberately local-first. It starts with generated files; then Moto can emulate the S3 API on localhost, so you can demonstrate the boto3 connector without an AWS account or AWS bill. The prototype makes no claim that a single model can replace a full DSPM/DLP platform.

## Component-by-component tour

### 1. Source adapters

`streamlit_app.py` receives browser uploads in memory. The CLI accepts one local file or a directory. `cli.py` also has an optional S3 adapter. All source types converge on the same `scan_bytes` function, so the rules and score logic do not vary by source.

The S3 adapter requires an explicit bucket, and accepts a prefix and maximum object count. With a real AWS endpoint it uses the configured boto3 profile; with a local endpoint it supplies dummy credentials and calls the local service. It filters by supported suffix, checks listed object size before retrieval, then calls `GetObject`. The scanner itself has no S3 write operation. A separate seed script writes only synthetic samples to a validated localhost endpoint.

### 2. Extraction

`extractors.py` accepts plain text, Markdown, CSV, JSON, and PDFs. Non-PDF files decode as UTF-8 with replacement for malformed bytes. PDFs are parsed in memory, with a page cap and password-protected files rejected. Pages with fewer than 24 extractable characters are treated as possible scans. The optional OCR path renders those pages with pypdfium2 and recognizes them using local Tesseract. Page count, OCR page count, and render DPI are bounded/configurable. OCR can misread low-quality scans and complex layouts, so findings need review.

### 3. Exact-value detectors

`detectors.py` runs separate, named rules. Each rule has a category, confidence, severity, and remediation recommendation. Credit-card candidates must pass the Luhn checksum, which filters many accidental digit sequences. Token patterns and credential assignments are intentionally narrow; a real secret format can be missed, and arbitrary strings can be false positives.

When several matches overlap, higher-severity and longer matches take precedence. The stored evidence contains only a category placeholder and character offsets, not a surrounding excerpt. This avoids persisting an adjacent value that another rule did not recognize. A redacted text copy is built in memory only when requested from the upload UI.

### 4. Synthetic text classifiers

`scripts/generate_synthetic_corpus.py` creates a balanced CSV of 500 safe examples by default. Sensitive examples contain typed placeholders such as `[EMAIL]` and `[API_SECRET]`, not real identifiers or working secrets. The negative class is general documentation text.

`classifier.py` learns TF-IDF unigram/bigram features and fits logistic regression as the always-available baseline. If a local model exists under `models/aegisdata-distilbert/`, `ContextClassifier` also loads a fine-tuned DistilBERT classifier and combines its maximum category signal with the baseline triage score. The transformer scores overlapping document chunks for seven labels. Its category output is stored separately from exact-rule findings; it does not create entity offsets or redaction spans.

`scripts/generate_multilabel_corpus.py` creates synthetic category-labeled examples with a source-template group ID. `scripts/train_transformer.py` makes deterministic train/validation/test splits that keep each template group intact, fine-tunes DistilBERT, and records per-category precision, recall, F1, average precision, and false positives per 1,000 negative examples. This is a more careful synthetic benchmark, but it still does not estimate real-world performance. More distinct, reviewed examples would be needed for credible claims.

### 5. Risk and explanation

`scanner.py` combines exact-match categories, the baseline context score, and optional transformer category scores. Credential, payment-card, and government-ID categories start with higher weights than contact categories. Transformer categories can raise a file for review, but do not become exact matches and do not override rule evidence.

The final report includes a SHA-256 content hash, byte count, timestamp, sensitivity label, score, categories, remediation suggestion, and masked match records. The hash helps distinguish versions without storing the file body; it does not prove where a file came from.

### 6. Local history

`storage.py` stores scan rows and masked findings in `data/aegisdata.db`. It does not store extracted text or original match values. It does retain the source name or S3 URI, so the database can still reveal sensitive location metadata. Keep it local and do not commit it to a public repository.

### 7. Review and redaction

The Streamlit dashboard shows scan history and category counts. For the current upload, it can produce a redacted text copy in memory and offer it as a download. That download contains extracted text rather than a modified copy of the original PDF or Office document. The application does not overwrite the source file or modify S3.

## Demo script

1. Run the sample directory scan and explain why each sample receives its label.
2. Open Streamlit and scan `customer_export.txt`.
3. Point out that the exact values do not appear in the finding evidence.
4. Download the `.redacted.txt` file and explain that it is a derivative text export, not an in-place edit.
5. Scan `general_notes.md` to show that the tool handles a benign example too.
6. Run the evaluation command. State clearly that its numbers apply only to the synthetic holdout.
7. If available, install the optional OCR dependencies and Tesseract, then scan a synthetic image-only PDF and show the extracted/redacted text.
8. Optionally generate the multi-label corpus, fine-tune DistilBERT, restart Streamlit, and compare the model category suggestions with exact-rule findings.
9. Start Moto locally, seed the demo bucket, and run `scan-s3` with `--endpoint-url http://127.0.0.1:5000` to demonstrate the S3 API without an AWS account.
10. If you later have an AWS sandbox, use the read-only policy, synthetic files, a narrow prefix, and a small object cap.

## Questions to be ready for

- **Why combine rules and ML?** Rules identify specific known formats and give evidence; ML adds a context signal when sensitive concepts are discussed without a recognizable value. Both have gaps.
- **Why include two models?** TF-IDF is a lightweight baseline. DistilBERT adds a neural, context-aware category signal. Keeping both allows a meaningful comparison and a fallback when model weights are not installed.
- **What do the classifier scores mean?** They are model outputs under synthetic training distributions, not calibrated probabilities that a real-world file contains regulated information.
- **What is the most important operational risk?** False negatives can create a false sense of safety. The demo must be validated on representative data and should not make access-control decisions.
- **What would you build next?** Add reviewed, span-labeled data for token classification, then validate the model and OCR against a distinct benchmark before adding more cloud connectors.
