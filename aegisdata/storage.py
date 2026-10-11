"""SQLite storage for scan metadata and masked findings (never raw file bodies)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from aegisdata.config import DEFAULT_DB_PATH
from aegisdata.models import ScanReport


def _connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def _connection(db_path: Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    connection = _connect(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize(db_path: Path = DEFAULT_DB_PATH) -> None:
    with _connection(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS scan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scanned_at_utc TEXT NOT NULL,
                source TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                byte_count INTEGER NOT NULL,
                sensitivity TEXT NOT NULL,
                model_probability REAL NOT NULL,
                model_backend TEXT NOT NULL DEFAULT 'TF-IDF + logistic-regression baseline',
                model_category_probabilities_json TEXT NOT NULL DEFAULT '{}',
                risk_score INTEGER NOT NULL,
                categories_json TEXT NOT NULL,
                recommendation TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
                category TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                severity TEXT NOT NULL,
                confidence REAL NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                masked_evidence TEXT NOT NULL,
                recommendation TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_scan_runs_scanned_at
                ON scan_runs(scanned_at_utc DESC);
            CREATE INDEX IF NOT EXISTS idx_findings_scan_id
                ON findings(scan_id);
            CREATE INDEX IF NOT EXISTS idx_findings_category
                ON findings(category);
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(scan_runs)")}
        if "model_backend" not in columns:
            connection.execute(
                "ALTER TABLE scan_runs ADD COLUMN model_backend TEXT NOT NULL "
                "DEFAULT 'TF-IDF + logistic-regression baseline'"
            )
        if "model_category_probabilities_json" not in columns:
            connection.execute(
                "ALTER TABLE scan_runs ADD COLUMN model_category_probabilities_json TEXT NOT NULL DEFAULT '{}'"
            )


def save_report(report: ScanReport, db_path: Path = DEFAULT_DB_PATH) -> int:
    initialize(db_path)
    with _connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO scan_runs (
                scanned_at_utc, source, sha256, byte_count, sensitivity,
                model_probability, model_backend, model_category_probabilities_json,
                risk_score, categories_json, recommendation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.scanned_at_utc,
                report.source,
                report.sha256,
                report.byte_count,
                report.sensitivity,
                report.model_probability,
                report.model_backend,
                json.dumps(dict(report.model_category_probabilities)),
                report.risk_score,
                json.dumps(report.categories),
                report.recommendation,
            ),
        )
        scan_id = int(cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO findings (
                scan_id, category, rule_id, severity, confidence,
                start_offset, end_offset, masked_evidence, recommendation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    scan_id,
                    match.category,
                    match.rule_id,
                    match.severity,
                    match.confidence,
                    match.start,
                    match.end,
                    match.masked_evidence,
                    match.recommendation,
                )
                for match in report.matches
            ],
        )
        return scan_id


def recent_scans(limit: int = 50, db_path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    initialize(db_path)
    with _connection(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["categories"] = json.loads(item.pop("categories_json"))
        item["model_category_probabilities"] = json.loads(
            item.pop("model_category_probabilities_json", "{}")
        )
        result.append(item)
    return result


def findings(limit: int = 250, db_path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    initialize(db_path)
    with _connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT f.id, f.scan_id, s.scanned_at_utc, s.source, s.sha256,
                   f.category, f.rule_id, f.severity, f.confidence,
                   f.masked_evidence, f.recommendation
            FROM findings AS f
            JOIN scan_runs AS s ON s.id = f.scan_id
            ORDER BY f.id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 1000)),),
        ).fetchall()
    return [dict(row) for row in rows]


def summary(db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    initialize(db_path)
    with _connection(db_path) as connection:
        counts = connection.execute(
            """
            SELECT COUNT(*) AS scans,
                   SUM(CASE WHEN sensitivity IN ('Critical', 'High') THEN 1 ELSE 0 END) AS high_risk_scans,
                   SUM(CASE WHEN sensitivity = 'Critical' THEN 1 ELSE 0 END) AS critical_scans
            FROM scan_runs
            """
        ).fetchone()
        finding_count = connection.execute("SELECT COUNT(*) AS total FROM findings").fetchone()
        categories = connection.execute(
            "SELECT category, COUNT(*) AS total FROM findings GROUP BY category ORDER BY total DESC"
        ).fetchall()
    return {
        "scans": int(counts["scans"] or 0),
        "high_risk_scans": int(counts["high_risk_scans"] or 0),
        "critical_scans": int(counts["critical_scans"] or 0),
        "findings": int(finding_count["total"] or 0),
        "categories": [{"category": row["category"], "count": row["total"]} for row in categories],
    }
