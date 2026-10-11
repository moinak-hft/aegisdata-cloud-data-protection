"""AegisData local security dashboard. Start with: streamlit run streamlit_app.py"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

import streamlit as st

from aegisdata.classifier import ContextClassifier
from aegisdata.config import APP_VERSION, MAX_FILE_BYTES
from aegisdata.detectors import redact_text
from aegisdata.scanner import scan_bytes
from aegisdata.storage import findings, recent_scans, save_report, summary


st.set_page_config(
    page_title="AegisData | Data security",
    page_icon="A",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .stApp { background: #F6F8FA; }
    [data-testid="stAppViewBlockContainer"] { max-width: 1380px; padding-top: 2rem; padding-bottom: 3rem; }
    [data-testid="stSidebar"] { background: #EEF2F5; border-right: 1px solid #DCE3E8; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #475467; }
    [data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid #DCE3E8;
        border-radius: 8px;
        padding: 1rem 1.1rem;
    }
    [data-testid="stMetricLabel"] { color: #5B6675 !important; font-size: 0.83rem; }
    [data-testid="stMetricValue"] { color: #182230 !important; font-size: 1.75rem; }
    [data-testid="stMetricDelta"] { font-size: 0.8rem; }
    h1 { color: #15212B; font-size: 2rem !important; letter-spacing: -0.025em; }
    h2, h3 { color: #1F2937; letter-spacing: -0.01em; }
    .page-kicker { color: #176B5B; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 0.5rem; }
    .brand-name { color: #14212B; font-size: 1.2rem; font-weight: 700; margin-bottom: 0; }
    .brand-caption { color: #667085; font-size: 0.78rem; margin-top: 0.1rem; }
    .section-note { color: #5B6675; font-size: 0.92rem; }
    div[data-testid="stFileUploader"] { background: #FFFFFF; border: 1px solid #DCE3E8; border-radius: 8px; padding: 0.5rem; }
    div.stButton > button[kind="primary"] { background: #176B5B; border-color: #176B5B; }
    div.stButton > button[kind="primary"]:hover { background: #115448; border-color: #115448; }
    a { color: #176B5B; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner="Loading the local classifier...")
def get_classifier() -> ContextClassifier:
    return ContextClassifier()


def csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    if not rows:
        return b""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def show_matches(reports: list[dict[str, Any]]) -> None:
    rows = []
    for report in reports:
        for match in report["matches"]:
            rows.append(
                {
                    "File": report["source"],
                    "Data type": match["category"].replace("_", " ").title(),
                    "Severity": match["severity"],
                    "Rule": match["rule_id"],
                    "Masked evidence": match["masked_evidence"],
                    "Suggested action": match["recommendation"],
                }
            )
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No exact pattern matches. Review the document score if the context model flagged it.")


PAGES = ["Overview", "Scan files", "Findings & history", "Method & limits"]
st.sidebar.markdown(
    '<p class="brand-name">AegisData</p><p class="brand-caption">Cloud data security workspace</p>',
    unsafe_allow_html=True,
)
st.sidebar.divider()
page = st.sidebar.radio("Workspace", PAGES, label_visibility="collapsed")
st.sidebar.divider()
st.sidebar.caption("LOCAL DEMO")
st.sidebar.caption("Files are scanned by this local app. Source files are left unchanged.")
st.sidebar.caption(f"Version {APP_VERSION}")

try:
    classifier = get_classifier()
except Exception as error:
    st.error(f"Could not load the local model: {error}")
    st.stop()

st.sidebar.caption(f"Model: {classifier.backend_name}")

st.markdown('<div class="page-kicker">AegisData / Security workspace</div>', unsafe_allow_html=True)
st.title(page)

if page == "Overview":
    st.markdown(
        '<p class="section-note">Find possible personal data and exposed credentials in selected files, then review and prioritize the findings.</p>',
        unsafe_allow_html=True,
    )
    stats = summary()
    metric_cols = st.columns(4)
    metric_cols[0].metric("Scans recorded", stats["scans"])
    metric_cols[1].metric("High-risk scans", stats["high_risk_scans"])
    metric_cols[2].metric("Critical scans", stats["critical_scans"])
    metric_cols[3].metric("Exact-rule findings", stats["findings"])

    st.subheader("Findings by data type")
    if stats["categories"]:
        chart_data = {
            item["category"].replace("_", " ").title(): item["count"]
            for item in stats["categories"]
        }
        st.bar_chart(chart_data, height=260, color="#318276")
        st.caption("Counts include each saved scan. Scanning a file again creates another scan record.")
    else:
        st.info("No scans yet. Open Scan files or use the sample folder command in the project README.")

    st.subheader("Recent scans")
    scans = recent_scans(limit=12)
    if scans:
        st.dataframe(
            [
                {
                    "Time (UTC)": item["scanned_at_utc"],
                    "Source": item["source"],
                    "Classification": item["sensitivity"],
                    "Risk score": item["risk_score"],
                    "Context score": item["model_probability"],
                    "Model": item["model_backend"],
                    "Model category signals": ", ".join(
                        f"{name} ({score:.2f})"
                        for name, score in sorted(
                            item["model_category_probabilities"].items(),
                            key=lambda pair: pair[1],
                            reverse=True,
                        )
                        if score >= 0.5
                    ) or "None over 0.50",
                    "Data types": ", ".join(item["categories"]) or "No exact match",
                }
                for item in scans
            ],
            use_container_width=True,
            hide_index=True,
        )

elif page == "Scan files":
    st.markdown(
        '<p class="section-note">Choose a few documents to inspect. Supported formats: TXT, Markdown, CSV, JSON, and PDF. Scanned PDF pages are OCR-processed locally when the optional OCR tools are installed.</p>',
        unsafe_allow_html=True,
    )
    st.caption(f"Maximum file size: {MAX_FILE_BYTES // (1024 * 1024)} MiB. Start with the synthetic files in samples/demo_docs.")
    uploaded_files = st.file_uploader(
        "Select files",
        type=["txt", "md", "csv", "json", "pdf"],
        accept_multiple_files=True,
        help="The contents are processed in memory. Raw file bodies are not written to the scan database.",
    )
    if st.button("Scan selected files", type="primary", disabled=not uploaded_files):
        current_reports: list[dict[str, Any]] = []
        redacted_files: dict[str, str] = {}
        progress = st.progress(0.0)
        for index, uploaded in enumerate(uploaded_files):
            try:
                report, original_text = scan_bytes(uploaded.name, uploaded.getvalue(), classifier)
                report_data = report.to_dict()
                report_data["scan_id"] = save_report(report)
                current_reports.append(report_data)
                redacted_files[uploaded.name] = redact_text(original_text, report.matches)
            except Exception as error:
                st.error(f"Could not scan {uploaded.name}: {error}")
            progress.progress((index + 1) / len(uploaded_files))
        st.session_state["last_reports"] = current_reports
        st.session_state["last_redacted"] = redacted_files

    current_reports = st.session_state.get("last_reports", [])
    if current_reports:
        st.subheader("Scan results")
        st.dataframe(
            [
                {
                    "File": item["source"],
                    "Classification": item["sensitivity"],
                    "Risk score": item["risk_score"],
                    "Context score": item["model_probability"],
                    "Model category signals": ", ".join(
                        f"{name} ({score:.2f})"
                        for name, score in sorted(
                            item["model_category_probabilities"].items(),
                            key=lambda pair: pair[1],
                            reverse=True,
                        )
                        if score >= 0.5
                    ) or "None over 0.50",
                    "Exact matches": len(item["matches"]),
                    "Data types": ", ".join(item["categories"]) or "No exact match",
                }
                for item in current_reports
            ],
            use_container_width=True,
            hide_index=True,
        )
        st.subheader("Detected patterns")
        show_matches(current_reports)
        st.subheader("Model signals")
        model_rows = []
        for report in current_reports:
            for category, probability in report["model_category_probabilities"].items():
                model_rows.append(
                    {
                        "File": report["source"],
                        "Category suggested by model": category.replace("_", " ").title(),
                        "Model score": probability,
                        "Interpretation": "Review suggestion; not an exact-value match",
                    }
                )
        if model_rows:
            st.dataframe(model_rows, use_container_width=True, hide_index=True)
        else:
            st.caption("The DistilBERT category model is not installed yet. The TF-IDF baseline and exact rules are active.")
        st.caption("Model scores are triage signals. They are not calibrated breach probabilities or proof that a file contains regulated data.")
        if st.session_state.get("last_redacted"):
            st.subheader("Redacted text copies")
            for filename, redacted_text in st.session_state["last_redacted"].items():
                output_name = f"{Path(filename).stem}.redacted.txt"
                st.download_button(
                    f"Download {output_name}",
                    data=redacted_text.encode("utf-8"),
                    file_name=output_name,
                    mime="text/plain",
                    key=f"download-{filename}",
                )

elif page == "Findings & history":
    st.markdown(
        '<p class="section-note">Review saved rule matches. Evidence shows a masked label and text offsets, never the matched value.</p>',
        unsafe_allow_html=True,
    )
    all_findings = findings(limit=1000)
    if all_findings:
        severity_options = sorted({item["severity"] for item in all_findings})
        selected_severities = st.multiselect("Severity", severity_options, default=severity_options)
        category_options = sorted({item["category"] for item in all_findings})
        selected_categories = st.multiselect("Data type", category_options, default=category_options)
        filtered = [
            item
            for item in all_findings
            if item["severity"] in selected_severities and item["category"] in selected_categories
        ]
        st.dataframe(filtered, use_container_width=True, hide_index=True)
        st.download_button(
            "Export filtered findings (CSV)",
            data=csv_bytes(filtered),
            file_name="aegisdata-findings.csv",
            mime="text/csv",
        )
    else:
        st.info("No findings saved yet. Scan the included synthetic samples to populate this page.")

    st.subheader("Scan history")
    history = recent_scans(limit=100)
    if history:
        st.dataframe(history, use_container_width=True, hide_index=True)

else:
    st.markdown(
        '<p class="section-note">A local-first learning project for data discovery and security triage.</p>',
        unsafe_allow_html=True,
    )
    st.subheader("What it does")
    st.markdown(
        """
        - Extracts text from selected local files and can OCR sparse-text PDF pages with local Tesseract.
        - Detects selected PII and credential formats with named rules.
        - Adds a TF-IDF baseline score; after local fine-tuning, it also adds DistilBERT multi-label category scores.
        - Prioritizes findings and suggests a next step.
        - Stores hashes, source metadata, risk labels, and masked finding locations in SQLite.
        """
    )
    st.subheader("What it does not do")
    st.markdown(
        """
        - It does not block sharing, change permissions, delete files, or remediate cloud objects.
        - OCR requires optional Python packages plus the separately installed Tesseract application.
        - Transformer predictions use synthetic training data and are review prompts, not production detection guarantees.
        - It is not connected to Zscaler or a live AWS account from this page.
        - Synthetic-data scores are not real-world detection guarantees.
        """
    )
    st.subheader("Try the S3 workflow locally, without AWS")
    st.write("This uses Moto, a local S3 API emulator. It does not create AWS resources or AWS charges. Docker is not required.")
    st.code(
        "# Terminal 1: install the local emulator dependency\n"
        "python -m pip install -r requirements-local-s3.txt\n\n"
        "# Keep this terminal open while Moto runs\n"
        "moto_server -H 127.0.0.1 -p 5000",
        language="powershell",
    )
    st.code(
        "# Terminal 2: upload only the project's synthetic samples to local Moto\n"
        "python .\\scripts\\seed_local_s3.py\n\n"
        "# Scan that local S3 bucket through the same boto3 connector\n"
        "python -m aegisdata.cli scan-s3 --bucket aegisdata-demo --prefix demo/ "
        "--region us-east-1 --endpoint-url http://127.0.0.1:5000 --max-objects 25",
        language="powershell",
    )
    st.caption("Stop the Moto server with Ctrl+C. The local emulator is a learning substitute, not AWS itself.")

    st.subheader("Enable the local transformer classifier")
    st.write("The transformer is optional. Install it, generate the synthetic multi-label corpus, then fine-tune DistilBERT locally. The first training run downloads pretrained weights; scanned file contents are never used for training or uploaded by the app.")
    st.code(
        "python -m pip install -r requirements-ml.txt\n"
        "python .\\scripts\\generate_multilabel_corpus.py\n"
        "python .\\scripts\\train_transformer.py",
        language="powershell",
    )
    st.caption("Restart Streamlit after training. When models/aegisdata-distilbert/config.json exists, the app loads the transformer automatically alongside the baseline.")

    st.subheader("Enable OCR for scanned PDFs")
    st.write("Install the optional Python libraries, install Tesseract OCR for Windows, and confirm it is available on PATH. Digital text pages keep using direct PDF text extraction; OCR runs only on sparse-text pages.")
    st.code(
        "python -m pip install -r requirements-ocr.txt\n"
        "tesseract --version",
        language="powershell",
    )
    st.caption("If Tesseract is installed but not on PATH, restart VS Code or add its install folder to Windows PATH. See the README for setup details and page limits.")
