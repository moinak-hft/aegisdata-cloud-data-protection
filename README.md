# AegisData

A local-first tool for finding sensitive data in documents and selected cloud storage locations. AegisData combines pattern-based detection, optional text classifiers, scanned-PDF OCR, masked findings, and a small review dashboard.

The scan path is inspectable: extracted text is analyzed in the local process, findings show which detector fired, and source documents are not written to the scan database. This is a prototype for experimentation, not a production data-loss-prevention system.

## What it does

- Scans TXT, Markdown, CSV, JSON, and PDF files from the dashboard or a local folder.
- Detects a limited set of personal-data and credential patterns with regular expressions and a Luhn check.
- Adds a scikit-learn TF-IDF classifier and an optional locally fine-tuned DistilBERT multi-label model for document and text-chunk context.
- Uses Tesseract OCR on sparse-text PDF pages when the optional OCR dependencies are installed.
- Shows masked evidence, risk labels, detector details, and suggested review actions.
- Keeps scan metadata and history in a local SQLite database.
- Can read a selected S3 prefix; Moto provides a local S3-compatible workflow that does not require an AWS account.

## Scan flow

~~~mermaid
flowchart LR
    subgraph source["1 · Sources"]
        upload["Browser upload"]
        folder["Local folder"]
        s3["Optional S3 prefix<br/>read-only"]
    end

    subgraph extract["2 · Extract text locally"]
        parser["Parse TXT · MD · CSV · JSON · PDF"]
        direct["Extract available text"]
        ocr["Render sparse-text PDF pages<br/>pypdfium2 + Tesseract OCR"]
        normalize["Normalized text<br/>held in process memory"]
    end

    subgraph analyze["3 · Analyze"]
        rules["Pattern detectors<br/>regex + Luhn"]
        baseline["TF-IDF context classifier<br/>scikit-learn"]
        transformer["Optional category classifier<br/>fine-tuned DistilBERT"]
        combine["Risk scoring<br/>and review guidance"]
    end

    subgraph results["4 · Review"]
        ui["Dashboard<br/>masked evidence"]
        history["SQLite<br/>scan metadata"]
        export["Redacted text<br/>download"]
    end

    upload --> parser
    folder --> parser
    s3 --> parser
    parser --> direct --> normalize

    parser -. sparse-text PDF page .-> ocr --> normalize
    normalize --> rules
    normalize --> baseline
    normalize -. optional .-> transformer
    rules --> combine
    baseline --> combine
    transformer --> combine
    combine --> ui
    combine --> history
    combine --> export

    classDef source fill:#E8F2FF,stroke:#4778A8,color:#172B3A
    classDef extract fill:#EAF6F0,stroke:#4B8A6A,color:#18382A
    classDef analyze fill:#FFF4DF,stroke:#B88428,color:#49350E
    classDef result fill:#F1ECFA,stroke:#7962A6,color:#2C2141
    class upload,folder,s3 source
    class parser,direct,ocr,normalize extract
    class rules,baseline,transformer,combine analyze
    class ui,history,export result
~~~

Pattern detectors produce exact match locations and masked evidence. Classifiers add context scores; they do not identify exact character spans. A model score is a signal for review, not proof that a document contains regulated data. The scores are not calibrated breach probabilities.

## Data handling

When run locally, the browser sends selected files to the local Streamlit process. The app extracts and scans their contents in memory. It stores scan metadata, hashes, masked finding details, and risk information in SQLite; it does not store the original document body. The redacted download is a text file, not a modified copy of the original PDF.

The optional S3 connector reads objects under a selected prefix into the local process. It does not upload, tag, delete, or change objects. Use synthetic or otherwise authorized data, and keep credentials out of the repository.

## Project structure

~~~text
aegisdata/
├── aegisdata/
│   ├── classifier.py          # TF-IDF model training and evaluation
│   ├── cli.py                 # folder, evaluation, and optional S3 commands
│   ├── config.py              # paths, limits, and supported file types
│   ├── detectors.py           # pattern rules, masking, and redaction
│   ├── extractors.py          # text extraction and optional PDF OCR
│   ├── models.py              # scan and finding data structures
│   ├── scanner.py             # detection and risk aggregation
│   ├── storage.py             # SQLite schema and queries
│   └── transformer_model.py   # optional DistilBERT inference
├── data/
│   ├── synthetic_training.csv
│   └── synthetic_multilabel.csv
├── docs/
│   ├── PROJECT_WALKTHROUGH.md
│   └── s3-read-only-policy.json
├── samples/demo_docs/         # synthetic files for trying the scanner
├── scripts/
│   ├── generate_synthetic_corpus.py
│   ├── generate_multilabel_corpus.py
│   ├── seed_local_s3.py
│   └── train_transformer.py
├── streamlit_app.py
├── requirements*.txt
└── README.md
~~~

The virtual environment, SQLite database, secrets, and trained model artifacts are excluded by .gitignore. The demo and training corpora are synthetic and are included in the repository.

## Run locally on Windows

Open this folder in VS Code, then open **Terminal → New Terminal**. These commands use PowerShell from the project root.

Create and activate a virtual environment:

~~~powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
~~~

If PowerShell blocks activation in this terminal, run:

~~~powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
~~~

Install the core dependencies and initialize the local database:

~~~powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m aegisdata.cli init-db
~~~

Scan the included examples from the command line:

~~~powershell
python -m aegisdata.cli scan-directory --path .\samples\demo_docs
~~~

Start the dashboard:

~~~powershell
python -m streamlit run .\streamlit_app.py
~~~

Open the local address printed by Streamlit, usually http://localhost:8501. In **Scan files**, select one or more documents and click **Scan selected files**. The current upload limit is 8 MiB per file. Press Ctrl+C in the server terminal to stop the app.

To use the virtual environment without activating it, prefix commands with .\.venv\Scripts\python.exe.

## Detection and model options

### Pattern rules and baseline classifier

The rule layer looks for a deliberately limited set of formats, including email addresses, US phone and SSN candidates, Luhn-valid card candidates, common token prefixes, key headers, and simple credential assignments. Rules can produce false positives and do not cover every format.

The baseline classifier uses TF-IDF features with logistic regression to estimate whether text resembles sensitive-data context. It works without downloading a language model.

To evaluate the baseline against the included synthetic corpus:

~~~powershell
python -m aegisdata.cli evaluate
~~~

The evaluation uses a held-out split of generated examples. Its results measure performance on that synthetic data only; they do not estimate real-world detection quality.

### Optional DistilBERT model

The optional multi-label classifier adds category scores for cloud credentials, payment cards, government IDs, email, phone, health information, and financial accounts. It scores text chunks and retains category scores for review. It does not provide token-level locations, so redaction spans still come from the pattern rules.

Install the ML dependencies, regenerate the deterministic corpus if desired, and train locally:

~~~powershell
python -m pip install -r requirements-ml.txt
python .\scripts\generate_multilabel_corpus.py
python .\scripts\train_transformer.py --epochs 2 --batch-size 4
~~~

The first training run downloads the public DistilBERT base weights. Training uses the included synthetic text. CPU training may take several minutes. The resulting local model is saved under models/aegisdata-distilbert/; restart the dashboard to load it. Model weights are ignored by Git, so a fresh clone starts with the baseline until the model is trained.

The corpus includes template-group labels. The training script separates groups across train, validation, and test sets to reduce near-duplicate leakage, then reports per-category precision, recall, and F1. Treat those scores as synthetic-corpus results, not as evidence of performance on customer or production data.

## OCR for scanned PDFs

Digital PDFs use direct text extraction. A page with very little extracted text is treated as possibly scanned and sent to local OCR. The app renders only sparse-text pages, up to 20 OCR pages per file by default, with a total PDF limit of 40 pages.

Install the Python packages in the project environment:

~~~powershell
python -m pip install -r requirements-ocr.txt
~~~

Tesseract is a separate application. Install it with English language data using the [Tesseract installation guide](https://tesseract-ocr.github.io/tessdoc/Installation.html), then check that the executable and language pack are visible:

~~~powershell
tesseract --version
tesseract --list-langs
~~~

The language list should include eng. If Tesseract was installed through MSYS2, open the **MSYS2 UCRT64** terminal and install the English language data package:

~~~bash
pacman -S mingw-w64-ucrt-x86_64-tesseract-data-eng
~~~

OCR quality depends on scan clarity, rotation, handwriting, and page layout. Tables and multi-column pages may be read out of order. Review OCR-derived findings before relying on them.

## Local S3 workflow without AWS

Moto can emulate the S3 API locally. This is useful for exercising the same boto3 code path without creating an AWS account or resources.

In VS Code Terminal 1, install the optional dependency and start the local server:

~~~powershell
python -m pip install -r requirements-local-s3.txt
moto_server -H 127.0.0.1 -p 5000
~~~

Leave it running. In Terminal 2, from the project root, load only the included synthetic files and scan them:

~~~powershell
python .\scripts\seed_local_s3.py
python -m aegisdata.cli scan-s3 --bucket aegisdata-demo --prefix demo/ --region us-east-1 --endpoint-url http://127.0.0.1:5000 --max-objects 25
~~~

Stop Moto with Ctrl+C. The seed script only accepts a local endpoint. This workflow uses local CPU, memory, and disk; it does not create AWS resources.

For a real S3 bucket, use a narrow prefix and a least-privilege policy based on [docs/s3-read-only-policy.json](docs/s3-read-only-policy.json). The connector needs list and read access only. The object's contents are fetched into the local process for scanning; this project does not configure automatic remediation.

## Evaluation limits

The included datasets are generated, not collected from real users. A random row split can overstate performance when examples are very similar, so the multi-label training pipeline groups variants by template. Even with grouped splits, synthetic results do not capture the variety of real documents, OCR errors, organization-specific formats, or adversarially modified inputs.

Before making performance claims, build an authorized and appropriately licensed evaluation set. Report per-category precision and recall, false positives per 1,000 documents, OCR quality by scan type, throughput, and the exact data split. Compare the rules-only, baseline-only, and combined systems.

## Future work

The next stages are intentionally more demanding than adding more regular expressions:

1. **Span-level extraction and geometry-aware redaction.** Train a token-classification model with BIO or span labels, preserve character offsets through normalization, and map OCR token boxes back to PDF coordinates. Use the resulting geometry to redact the original page while retaining a reviewable audit trail.

2. **Weak supervision and active learning.** Combine labeling functions from format checks, checksums, surrounding context, and document layout; estimate noisy-label quality; send uncertain examples to a controlled review queue; and retrain from adjudicated labels without mixing document templates across splits.

3. **Calibrated decisions under distribution shift.** Tune per-category thresholds against explicit false-positive and false-negative costs, measure calibration error, and add selective prediction or conformal risk control so the system can abstain when evidence is weak or the input differs from training data.

4. **Layout-aware document understanding.** Preserve page, line, table-cell, and bounding-box structure through OCR. Compare OCR engines and layout-aware encoders on rotated scans, multi-column pages, forms, and tables; measure both text recognition and downstream detection quality.

5. **Incremental cloud scanning at scale.** Replace prefix-wide rereads with S3 Inventory or event-driven discovery, version-aware object identities, content hashes, idempotent workers, bounded queues, retries, and backpressure. Track object versions so a rescan can distinguish changed content from a new location.

6. **Data lineage and policy evaluation.** Build a graph linking objects, detected entities, copies, and storage locations. Evaluate access and retention rules against that graph with a policy engine, then explain which source object and rule caused a finding to propagate.

7. **Privacy-preserving model development.** If training ever uses sensitive examples, investigate differential privacy with a documented privacy budget, membership-inference tests, artifact access controls, and a reproducible data-retention process.

These are research and engineering directions, not features in the current implementation. Each should be paired with a threat model and a reproducible evaluation before it is described as complete.


