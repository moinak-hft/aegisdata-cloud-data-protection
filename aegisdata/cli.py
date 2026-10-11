"""Command-line workflows for local folders, evaluation, and optional S3."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aegisdata.classifier import ContextClassifier, evaluate
from aegisdata.config import MAX_FILE_BYTES, SUPPORTED_EXTENSIONS
from aegisdata.scanner import scan_bytes
from aegisdata.storage import initialize, save_report


def _scan_directory(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        print(f"Path does not exist: {root}", file=sys.stderr)
        return 2
    paths = [root] if root.is_file() else sorted(root.rglob("*"))
    candidates = [path for path in paths if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS]
    classifier = ContextClassifier()
    initialize()
    completed = 0
    skipped = 0
    for path in candidates:
        if path.stat().st_size > MAX_FILE_BYTES:
            print(f"SKIP too large ({path.stat().st_size} bytes): {path.name}")
            skipped += 1
            continue
        try:
            content = path.read_bytes()
            source = path.name if root.is_file() else path.relative_to(root).as_posix()
            report, _ = scan_bytes(path.name, content, classifier, source=source)
            scan_id = save_report(report)
            print(
                f"{report.sensitivity:8} risk={report.risk_score:3} "
                f"matches={len(report.matches):3} scan_id={scan_id:4} {source}"
            )
            completed += 1
        except Exception as error:  # Keep a batch scan moving when one file is malformed.
            print(f"ERROR {path.name}: {error}", file=sys.stderr)
            skipped += 1
    print(f"Completed {completed} file(s); skipped {skipped}; SQLite history is in data/aegisdata.db.")
    return 0 if completed else 1


def _scan_s3(args: argparse.Namespace) -> int:
    try:
        import boto3
    except ImportError:
        print("Install the optional AWS SDK with: python -m pip install boto3", file=sys.stderr)
        return 2

    if args.endpoint_url and args.profile:
        print("Use the local endpoint without --profile; the emulator uses dummy local credentials.", file=sys.stderr)
        return 2
    if args.endpoint_url:
        session = boto3.Session(
            aws_access_key_id="test",
            aws_secret_access_key="test",
            region_name=args.region or "us-east-1",
        )
        from botocore.config import Config

        client = session.client(
            "s3",
            region_name=args.region or "us-east-1",
            endpoint_url=args.endpoint_url,
            config=Config(s3={"addressing_style": "path"}),
        )
    else:
        session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
        client = session.client("s3", region_name=args.region)
    paginator = client.get_paginator("list_objects_v2")
    classifier = ContextClassifier()
    initialize()
    completed = 0
    skipped = 0
    listed = 0
    try:
        for page in paginator.paginate(Bucket=args.bucket, Prefix=args.prefix):
            for item in page.get("Contents", []):
                listed += 1
                if listed > args.max_objects:
                    print(f"Reached --max-objects={args.max_objects}; stopping.")
                    break
                key = item["Key"]
                suffix = Path(key).suffix.lower()
                if suffix not in SUPPORTED_EXTENSIONS:
                    skipped += 1
                    continue
                if item.get("Size", 0) > MAX_FILE_BYTES:
                    print(f"SKIP too large ({item['Size']} bytes): s3://{args.bucket}/{key}")
                    skipped += 1
                    continue
                try:
                    response = client.get_object(Bucket=args.bucket, Key=key)
                    try:
                        content = response["Body"].read(MAX_FILE_BYTES + 1)
                    finally:
                        response["Body"].close()
                    source = f"s3://{args.bucket}/{key}"
                    report, _ = scan_bytes(Path(key).name, content, classifier, source=source)
                    scan_id = save_report(report)
                    print(
                        f"{report.sensitivity:8} risk={report.risk_score:3} "
                        f"matches={len(report.matches):3} scan_id={scan_id:4} {source}"
                    )
                    completed += 1
                except Exception as error:
                    print(f"ERROR s3://{args.bucket}/{key}: {error}", file=sys.stderr)
                    skipped += 1
            if listed > args.max_objects:
                break
    except Exception as error:
        print(f"S3 scan stopped: {error}", file=sys.stderr)
        return 2
    print(f"Completed {completed} object(s); skipped {skipped}; S3 was read only.")
    return 0 if completed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegisdata", description="Local-first AI-assisted data discovery demo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Create the local SQLite schema")

    scan_directory = subparsers.add_parser("scan-directory", help="Scan supported files in a chosen folder")
    scan_directory.add_argument("--path", required=True, help="One file or a directory to scan")

    scan_s3 = subparsers.add_parser("scan-s3", help="Read and scan supported objects from an S3 prefix")
    scan_s3.add_argument("--bucket", required=True)
    scan_s3.add_argument("--prefix", default="", help="Limit the scan to this object-key prefix")
    scan_s3.add_argument("--region", default=None)
    scan_s3.add_argument("--profile", default=None, help="Optional named AWS profile")
    scan_s3.add_argument("--endpoint-url", default=None, help="S3-compatible endpoint, e.g. local Moto")
    scan_s3.add_argument("--max-objects", type=int, default=100)

    subparsers.add_parser("evaluate", help="Evaluate the classifier on a synthetic holdout set")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "init-db":
        initialize()
        print("SQLite database initialized at data/aegisdata.db (or AEGIS_DB_PATH if set).")
        return 0
    if args.command == "scan-directory":
        return _scan_directory(args)
    if args.command == "scan-s3":
        if args.max_objects < 1:
            print("--max-objects must be at least 1.", file=sys.stderr)
            return 2
        return _scan_s3(args)
    if args.command == "evaluate":
        report = evaluate()
        print(json.dumps(report, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
