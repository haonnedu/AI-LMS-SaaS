"""Synchronous S3 factory for workers; no public upload/download API is exposed."""

import boto3
from botocore.config import Config

from app.core.config import Settings


def create_s3_client(settings: Settings):
    """Caller owns client.close(); use a thread pool if called from async code."""
    options = {
        "region_name": settings.s3_region,
        "endpoint_url": settings.s3_endpoint_url,
        "config": Config(
            signature_version="s3v4",
            connect_timeout=3,
            read_timeout=10,
            retries={"mode": "standard", "max_attempts": 2},
            s3={"addressing_style": "path"},
        ),
    }
    if settings.s3_access_key_id and settings.s3_secret_access_key:
        options["aws_access_key_id"] = settings.s3_access_key_id.get_secret_value()
        options["aws_secret_access_key"] = settings.s3_secret_access_key.get_secret_value()
    return boto3.client("s3", **options)
