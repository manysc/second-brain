"""S3-compatible object storage access (targets a self-hosted SeaweedFS gateway)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import boto3
from botocore.config import Config


@dataclass(frozen=True)
class S3Config:
    bucket: str
    prefix: str
    endpoint_url: str
    region: str


def _config() -> S3Config:
    bucket = os.environ.get("S3_BUCKET")
    endpoint_url = os.environ.get("S3_ENDPOINT_URL")
    if not bucket:
        raise RuntimeError("S3_BUCKET environment variable is required")
    if not endpoint_url:
        raise RuntimeError("S3_ENDPOINT_URL environment variable is required")
    return S3Config(
        bucket=bucket,
        prefix=os.environ.get("S3_PREFIX", ""),
        endpoint_url=endpoint_url,
        region=os.environ.get("S3_REGION", "us-east-1"),
    )


@lru_cache(maxsize=1)
def _get_client(endpoint_url: str, region: str):
    # SeaweedFS's S3 gateway only supports path-style bucket addressing.
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        config=Config(
            s3={"addressing_style": "path"},
            retries={"max_attempts": 8, "mode": "standard"},
            connect_timeout=5,
            read_timeout=30,
        ),
    )


def list_extract_keys() -> list[str]:
    config = _config()
    client = _get_client(config.endpoint_url, config.region)
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=config.bucket, Prefix=config.prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".json"):
                keys.append(key)
    return sorted(keys)


def fetch_object_text(key: str) -> str:
    config = _config()
    client = _get_client(config.endpoint_url, config.region)
    response = client.get_object(Bucket=config.bucket, Key=key)
    return response["Body"].read().decode("utf8")


def clear_client_cache() -> None:
    _get_client.cache_clear()
