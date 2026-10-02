"""
Upload original PDF bytes to Supabase Storage using the S3-compatible API.

Requires bucket + S3 access keys from the Supabase dashboard (Storage → S3 credentials).
"""
from __future__ import annotations

from contextlib import closing
import os
import re

import boto3
from botocore.config import Config

from app.core.config import get_config

def _safe_pdf_basename(filename: str) -> str:
    base = os.path.basename(filename) or "document.pdf"
    if not base.lower().endswith(".pdf"):
        base = f"{base}.pdf"
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", base)
    return safe[:200] if len(safe) > 200 else safe


def build_pdf_object_key(user_id: str, doc_id: str, filename: str) -> str:
    """S3 object key: {user_id}/{doc_id}/{sanitized.pdf}."""
    return f"{user_id}/{doc_id}/{_safe_pdf_basename(filename)}"


def is_pdf_storage_configured() -> bool:
    c = get_config()
    return bool(
        c.supabase_s3_endpoint
        and c.supabase_s3_region
        and c.supabase_s3_access_key_id
        and c.supabase_s3_secret_access_key
        and c.supabase_storage_bucket
    )


def _storage_client():
    if not is_pdf_storage_configured():
        raise RuntimeError("Supabase S3 storage is not fully configured.")

    c = get_config()
    return boto3.client(
        "s3",
        endpoint_url=c.supabase_s3_endpoint.rstrip("/"),
        aws_access_key_id=c.supabase_s3_access_key_id,
        aws_secret_access_key=c.supabase_s3_secret_access_key,
        region_name=c.supabase_s3_region,
        config=Config(
            signature_version="s3v4", s3={"addressing_style": "path"},
            connect_timeout=10, read_timeout=c.upstream_timeout_seconds,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def upload_pdf_to_supabase_storage(file_content: bytes, object_key: str) -> None:
    """Synchronous S3 operations must run in a threadpool."""
    with closing(_storage_client()) as client:
        client.put_object(Bucket=get_config().supabase_storage_bucket, Key=object_key,
                          Body=file_content, ContentType="application/pdf")


def download_pdf(object_key: str) -> bytes:
    with closing(_storage_client()) as client:
        response = client.get_object(Bucket=get_config().supabase_storage_bucket, Key=object_key)
        try:
            return response["Body"].read()
        finally:
            response["Body"].close()


def delete_pdf(object_key: str) -> None:
    with closing(_storage_client()) as client:
        client.delete_object(Bucket=get_config().supabase_storage_bucket, Key=object_key)


def signed_pdf_url(object_key: str) -> str:
    with closing(_storage_client()) as client:
        return client.generate_presigned_url("get_object", Params={
            "Bucket": get_config().supabase_storage_bucket, "Key": object_key,
            "ResponseContentType": "application/pdf", "ResponseContentDisposition": "inline",
        }, ExpiresIn=300)
