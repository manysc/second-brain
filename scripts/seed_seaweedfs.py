"""Dev bootstrap: create the configured bucket and upload the sample meeting extract files.

Usage (from repo root, with the seaweedfs docker-compose service running):
    python scripts/seed_seaweedfs.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
load_dotenv(REPO_ROOT / "backend" / ".env")
FILES_TO_SEED = [
    "meeting-extract.json",
    "MS-PS_1-1_Meeting-Extract_082126.json",
    "MS-PS_1-1_Meeting-Extract_082726.json",
]


def _client():
    endpoint_url = os.environ.get("S3_ENDPOINT_URL", "http://localhost:8333")
    region = os.environ.get("S3_REGION", "us-east-1")
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        config=Config(s3={"addressing_style": "path"}),
    )


def _ensure_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)


def main() -> None:
    bucket = os.environ.get("S3_BUCKET", "second-brain")
    prefix = os.environ.get("S3_PREFIX", "")
    client = _client()
    _ensure_bucket(client, bucket)

    for filename in FILES_TO_SEED:
        source = DATA_DIR / filename
        if not source.exists():
            print(f"skip (not found): {source}", file=sys.stderr)
            continue
        key = f"{prefix}{filename}"
        client.upload_file(str(source), bucket, key)
        print(f"uploaded s3://{bucket}/{key}")


if __name__ == "__main__":
    main()
