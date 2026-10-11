"""Runtime limits and paths for the AegisData prototype."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
TRAINING_DATA_PATH = DATA_DIR / "synthetic_training.csv"
DEFAULT_DB_PATH = Path(os.getenv("AEGIS_DB_PATH", str(DATA_DIR / "aegisdata.db")))

MAX_FILE_BYTES = int(os.getenv("AEGIS_MAX_FILE_BYTES", str(8 * 1024 * 1024)))
MAX_PDF_PAGES = int(os.getenv("AEGIS_MAX_PDF_PAGES", "40"))
MAX_OCR_PAGES = int(os.getenv("AEGIS_MAX_OCR_PAGES", "20"))
OCR_LANGUAGE = os.getenv("AEGIS_OCR_LANGUAGE", "eng")
OCR_DPI = int(os.getenv("AEGIS_OCR_DPI", "220"))
MAX_TRANSFORMER_CHUNKS = int(os.getenv("AEGIS_MAX_TRANSFORMER_CHUNKS", "128"))
TRANSFORMER_MODEL_DIR = Path(
    os.getenv("AEGIS_TRANSFORMER_MODEL_DIR", str(PROJECT_ROOT / "models" / "aegisdata-distilbert"))
)
SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".pdf"}

APP_NAME = "AegisData"
APP_VERSION = "0.2.0"
