"""Text extraction for small, explicitly supported file types."""

from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import shutil

from pypdf import PdfReader

from aegisdata.config import MAX_OCR_PAGES, MAX_PDF_PAGES, OCR_DPI, OCR_LANGUAGE, SUPPORTED_EXTENSIONS


def _ocr_pdf_pages(content: bytes, pages_to_ocr: list[int], page_count: int) -> dict[int, str]:
    """OCR only selected sparse-text pages; all processing stays in this process."""
    try:
        import pypdfium2 as pdfium
        import pytesseract
    except ImportError as error:
        raise RuntimeError(
            "This PDF appears to contain scanned pages. Install optional OCR dependencies with "
            "`python -m pip install -r requirements-ocr.txt`, then install the Tesseract OCR "
            "application and make sure `tesseract --version` works in the VS Code terminal."
        ) from error

    configured_executable = os.getenv("AEGIS_TESSERACT_CMD")
    if configured_executable:
        if not Path(configured_executable).is_file():
            raise RuntimeError(
                "AEGIS_TESSERACT_CMD does not point to a file. Set it to the full path of tesseract.exe."
            )
        pytesseract.pytesseract.tesseract_cmd = configured_executable
    elif not shutil.which("tesseract"):
        raise RuntimeError(
            "Scanned PDF detected, but the Tesseract application is not on PATH. Install Tesseract OCR, "
            "restart VS Code, and confirm `tesseract --version` works."
        )
    if len(pages_to_ocr) > MAX_OCR_PAGES:
        raise RuntimeError(
            f"PDF needs OCR on {len(pages_to_ocr)} pages; the per-file OCR limit is {MAX_OCR_PAGES}. "
            "Increase AEGIS_MAX_OCR_PAGES if you intentionally want to process more pages."
        )

    pdf = pdfium.PdfDocument(BytesIO(content))
    if len(pdf) != page_count:
        raise RuntimeError("PDF page count changed while preparing OCR; scan stopped safely.")

    recognized: dict[int, str] = {}
    scale = OCR_DPI / 72.0
    for page_index in pages_to_ocr:
        page = pdf[page_index]
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil()
        recognized[page_index] = pytesseract.image_to_string(
            image,
            lang=OCR_LANGUAGE,
            config="--psm 6",
        ).strip()
        image.close()
        page.close()
    pdf.close()
    return recognized


def extract_text(filename: str, content: bytes) -> str:
    """Extract text without writing the file to disk."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type {suffix or '(no extension)'}.")
    if suffix != ".pdf":
        return content.decode("utf-8", errors="replace")

    reader = PdfReader(BytesIO(content), strict=False)
    if reader.is_encrypted:
        raise ValueError("Password-protected PDFs are not supported in this prototype.")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValueError(f"PDF has {len(reader.pages)} pages; limit is {MAX_PDF_PAGES}.")
    pages = [page.extract_text() or "" for page in reader.pages]
    # A mostly blank extraction usually means the page is a scan. OCR just those
    # pages; text extraction remains the fast path for ordinary digital PDFs.
    sparse_pages = [index for index, text in enumerate(pages) if len(text.strip()) < 24]
    if sparse_pages:
        ocr_text = _ocr_pdf_pages(content, sparse_pages, len(reader.pages))
        for index, text in ocr_text.items():
            if text:
                pages[index] = text
    return "\n\n".join(f"[PAGE {index + 1}]\n{text}" for index, text in enumerate(pages) if text.strip())
