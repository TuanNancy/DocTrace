"""Exercise storage helpers with real boto3 clients, without network requests."""
from io import BytesIO
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from botocore.stub import Stubber

from app.core.config import AppConfig
from app.services import supabase_pdf_storage as storage

PDF = b"%PDF-1.4\nfixture"
KEY = "owner/document/sample.pdf"
PARAMS = {"Bucket": "pdfs", "Key": KEY}


@pytest.fixture
def s3(monkeypatch):
    config = AppConfig(
        supabase_s3_endpoint="https://storage.example.test",
        supabase_s3_region="us-east-1",
        supabase_s3_access_key_id="test-access-key",
        supabase_s3_secret_access_key="test-secret-key",
        supabase_storage_bucket="pdfs",
    )
    monkeypatch.setattr(storage, "get_config", lambda: config)
    client = storage._storage_client()
    close = Mock(wraps=client.close)
    monkeypatch.setattr(client, "close", close)
    monkeypatch.setattr(storage, "_storage_client", lambda: client)
    try:
        with Stubber(client) as stubber:
            yield stubber, close
    finally:
        client.close()


def test_upload_uses_real_client_and_closes_it(s3):
    stubber, close = s3
    stubber.add_response("put_object", {}, {**PARAMS, "Body": PDF, "ContentType": "application/pdf"})
    storage.upload_pdf_to_supabase_storage(PDF, KEY)
    stubber.assert_no_pending_responses()
    close.assert_called_once()


def test_download_returns_bytes_and_closes_body_and_client(s3):
    stubber, close = s3
    body = BytesIO(PDF)
    stubber.add_response("get_object", {"Body": StreamingBody(body, len(PDF))}, PARAMS)
    assert storage.download_pdf(KEY) == PDF
    assert body.closed
    stubber.assert_no_pending_responses()
    close.assert_called_once()


def test_delete_uses_real_client_and_closes_it(s3):
    stubber, close = s3
    stubber.add_response("delete_object", {}, PARAMS)
    storage.delete_pdf(KEY)
    stubber.assert_no_pending_responses()
    close.assert_called_once()


def test_signed_link_has_pdf_overrides_and_five_minute_expiry(s3):
    _, close = s3
    url = urlparse(storage.signed_pdf_url(KEY))
    query = parse_qs(url.query)
    assert url.netloc == "storage.example.test"
    assert url.path == f"/pdfs/{KEY}"
    assert query["X-Amz-Expires"] == ["300"]
    assert query["response-content-type"] == ["application/pdf"]
    assert query["response-content-disposition"] == ["inline"]
    assert query["X-Amz-Signature"]
    close.assert_called_once()


@pytest.mark.parametrize("operation,helper,args", [
    ("put_object", storage.upload_pdf_to_supabase_storage, (PDF, KEY)),
    ("get_object", storage.download_pdf, (KEY,)),
    ("delete_object", storage.delete_pdf, (KEY,)),
])
def test_remote_errors_propagate_and_still_close_client(s3, operation, helper, args):
    stubber, close = s3
    stubber.add_client_error(operation, service_error_code="AccessDenied", http_status_code=403)
    with pytest.raises(ClientError, match="AccessDenied"):
        helper(*args)
    stubber.assert_no_pending_responses()
    close.assert_called_once()


def test_download_read_failure_closes_body_and_client(s3):
    class BrokenBody(BytesIO):
        def read(self, *args):
            raise OSError("Read interrupted")

    stubber, close = s3
    body = BrokenBody(PDF)
    stubber.add_response("get_object", {"Body": StreamingBody(body, len(PDF))}, PARAMS)
    with pytest.raises(OSError, match="Read interrupted"):
        storage.download_pdf(KEY)
    assert body.closed
    stubber.assert_no_pending_responses()
    close.assert_called_once()
