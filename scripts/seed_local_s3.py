"""Copy the synthetic demo files into a local Moto S3 emulator only."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "samples" / "demo_docs"
SUPPORTED = {".txt", ".md", ".csv", ".json", ".pdf"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint-url", default="http://127.0.0.1:5000")
    parser.add_argument("--bucket", default="aegisdata-demo")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    endpoint = urlparse(args.endpoint_url)
    if endpoint.hostname not in LOCAL_HOSTS:
        parser.error("This seed script only uploads to localhost; it will not send demo files to AWS.")

    session = boto3.Session(
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name=args.region,
    )
    client = session.client(
        "s3",
        region_name=args.region,
        endpoint_url=args.endpoint_url,
        config=Config(s3={"addressing_style": "path"}),
    )

    buckets = {bucket["Name"] for bucket in client.list_buckets().get("Buckets", [])}
    if args.bucket not in buckets:
        client.create_bucket(Bucket=args.bucket)

    count = 0
    for path in sorted(SAMPLE_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        key = f"demo/{path.relative_to(SAMPLE_DIR).as_posix()}"
        client.put_object(Bucket=args.bucket, Key=key, Body=path.read_bytes())
        print(f"Uploaded to local emulator: s3://{args.bucket}/{key}")
        count += 1

    print(f"Seeded {count} synthetic file(s) at {args.endpoint_url} (local only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
