#!/usr/bin/env python3
"""
Back up every object in the SeaweedFS "second-brain" S3 bucket to a
local timestamped tar.gz archive under backups/s3/.

Usage:
    python scripts/backup_s3_bucket.py            # run once and exit
    python scripts/backup_s3_bucket.py --loop      # run forever, repeating the
                                                    # backup every
                                                    # S3_BACKUP_INTERVAL_DAYS
                                                    # (default: 30 days)

This script is intentionally standalone (only depends on boto3 + stdlib) so
it can run in a minimal container without pulling in the rest of the
personal_expenses_app package.

Configuration (env vars):
    S3_CONFIG_PATH          Path to s3.json (default: <repo>/s3.json)
    S3_ENDPOINT_URL         Optional override for the endpoint_url in s3.json
                            (e.g. http://localhost:8333 for local/host dev)
    S3_BACKUP_INTERVAL_DAYS How often to back up when --loop is used (default: 30)
    S3_BACKUP_DIR           Where to write backup archives
                            (default: <repo>/backups/s3)
"""

import argparse
import io
import json
import os
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3

_repo_root = Path(__file__).parent.parent


def _load_s3_config() -> dict:
    config_path = Path(os.environ.get("S3_CONFIG_PATH", str(_repo_root / "s3.json")))
    if not config_path.is_file():
        raise FileNotFoundError(f"S3 config file not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    endpoint_override = os.environ.get("S3_ENDPOINT_URL")
    if endpoint_override:
        config["endpoint_url"] = endpoint_override
    return config


def _get_client(config: dict):
    return boto3.client(
        "s3",
        endpoint_url=config["endpoint_url"],
        aws_access_key_id=config["access_key"],
        aws_secret_access_key=config["secret_key"],
        region_name=config.get("region", "us-east-1"),
    )


def _list_all_keys(client, bucket: str) -> list[str]:
    keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def run_backup() -> Path:
    """Download every object in the bucket into a single timestamped tar.gz archive."""
    config = _load_s3_config()
    bucket = config["bucket"]
    client = _get_client(config)

    backup_dir = Path(os.environ.get("S3_BACKUP_DIR", str(_repo_root / "backups" / "s3")))
    backup_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    archive_path = backup_dir / f"{bucket}_{timestamp}.tar.gz"

    keys = _list_all_keys(client, bucket)
    print(f"[{timestamp}] Backing up {len(keys)} object(s) from bucket '{bucket}' to {archive_path}")

    with tarfile.open(archive_path, "w:gz") as tar:
        for key in keys:
            obj = client.get_object(Bucket=bucket, Key=key)
            data = obj["Body"].read()
            info = tarfile.TarInfo(name=key)
            info.size = len(data)
            info.mtime = int(now.timestamp())
            tar.addfile(info, io.BytesIO(data))

    size_mb = archive_path.stat().st_size / (1024 * 1024)
    print(f"Backup complete: {archive_path} ({size_mb:.2f} MB, {len(keys)} object(s))")
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run forever, repeating the backup every S3_BACKUP_INTERVAL_DAYS.",
    )
    args = parser.parse_args()

    if not args.loop:
        run_backup()
        return 0

    interval_days = float(os.environ.get("S3_BACKUP_INTERVAL_DAYS", "30"))
    print(f"Starting periodic S3 backup loop (every {interval_days} day(s)). Press Ctrl+C to stop.")
    while True:
        try:
            run_backup()
        except Exception as exc:
            print(f"Backup failed: {exc}", file=sys.stderr)
        time.sleep(interval_days * 86400)


if __name__ == "__main__":
    raise SystemExit(main())
