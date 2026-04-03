"""
Upload original PDF bytes to Supabase Storage using the S3-compatible API.

Requires bucket + S3 access keys from the Supabase dashboard (Storage → S3 credentials).
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_config

logger = logging.getLogger(__name__)


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


def upload_pdf_to_supabase_storage(file_content: bytes, object_key: str) -> None:
    """
    Put PDF object into the configured bucket. Raises on failure.

    Uses synchronous boto3; call from asyncio via asyncio.to_thread().
    """
    if not is_pdf_storage_configured():
        raise RuntimeError("Supabase S3 storage is not fully configured.")

    c = get_config()
    client = boto3.client(
        "s3",
        endpoint_url=c.supabase_s3_endpoint.rstrip("/"),
        aws_access_key_id=c.supabase_s3_access_key_id,
        aws_secret_access_key=c.supabase_s3_secret_access_key,
        region_name=c.supabase_s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    client.put_object(
        Bucket=c.supabase_storage_bucket,
        Key=object_key,
        Body=file_content,
        ContentType="application/pdf",
    )


def try_upload_pdf(
    file_content: bytes,
    user_id: str,
    doc_id: str,
    filename: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    Upload PDF if S3 env is configured.

    Returns:
        (object_key, None) on success
        (None, warning_message) on skip or failure (indexing should still succeed)
    """
    if not is_pdf_storage_configured():
        logger.info(
            "Supabase PDF storage skipped: set SUPABASE_S3_ACCESS_KEY_ID, "
            "SUPABASE_S3_SECRET_ACCESS_KEY, and SUPABASE_STORAGE_BUCKET (and optionally "
            "SUPABASE_S3_ENDPOINT / SUPABASE_S3_REGION)."
        )
        return None, None

    key = build_pdf_object_key(user_id, doc_id, filename)
    try:
        upload_pdf_to_supabase_storage(file_content, key)
        logger.info("Stored original PDF in Supabase Storage: %s", key)
        return key, None
    except (ClientError, BotoCoreError, OSError) as e:
        msg = f"Could not upload PDF to storage: {e}"
        logger.warning(msg)
        return None, msg
    except Exception as e:
        msg = f"Could not upload PDF to storage: {e}"
        logger.exception(msg)
        return None, msg
