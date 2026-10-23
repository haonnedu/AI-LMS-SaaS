"""Upload validation, key derivation, hashing and S3 calls (botocore Stubber, no network)."""

import base64
import hashlib
import io
from datetime import UTC, datetime
from urllib.parse import parse_qs, quote, urlsplit
from uuid import uuid4

import boto3
import pytest
from botocore.config import Config
from botocore.stub import ANY, Stubber

from app.api.identity import ApiError
from app.core.config import Settings
from app.services import storage


def s3_client():
    return boto3.client(
        "s3",
        region_name="us-east-1",
        endpoint_url="http://127.0.0.1:9000",
        aws_access_key_id="test-access",
        aws_secret_access_key="test-secret",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


@pytest.fixture
def store():
    client = s3_client()
    settings = Settings(_env_file=None, s3_bucket="eduvia-test")
    with Stubber(client) as stub:
        yield storage.ObjectStore(settings, client=client), stub
        stub.assert_no_pending_responses()


@pytest.mark.parametrize(
    "header,expected",
    [
        ("application/pdf", "application/pdf"),
        ("Application/PDF; charset=binary", "application/pdf"),
        ("text/plain; charset=utf-8", "text/plain"),
        (storage.DOCX, storage.DOCX),
    ],
)
def test_allowed_mime(header, expected):
    assert storage.normalize_mime(header) == expected


@pytest.mark.parametrize("header", [None, "", "image/png", "application/zip", "text/html"])
def test_rejected_mime(header):
    with pytest.raises(ApiError) as error:
        storage.normalize_mime(header)
    assert (error.value.status, error.value.code) == (415, "unsupported_media_type")


def test_percent_encoded_vietnamese_file_name():
    raw = quote("Giáo án Toán 10.pdf")
    assert storage.validate_file_name(raw, "application/pdf") == "Giáo án Toán 10.pdf"


@pytest.mark.parametrize(
    "raw",
    [None, "", "../etc/passwd.pdf", "a/b.pdf", "a\\b.pdf", ".hidden.pdf", "a%00.pdf", "%FF.pdf"],
)
def test_invalid_file_names(raw):
    with pytest.raises(ApiError) as error:
        storage.validate_file_name(raw, "application/pdf")
    assert error.value.code == "invalid_file_name"


def test_extension_must_match_type():
    with pytest.raises(ApiError) as error:
        storage.validate_file_name("notes.exe", "text/plain")
    assert error.value.code == "file_type_mismatch"


def test_declared_size_limit():
    storage.check_declared_size(None, 100)
    storage.check_declared_size(100, 100)
    with pytest.raises(ApiError) as error:
        storage.check_declared_size(101, 100)
    assert (error.value.status, error.value.code) == (413, "file_too_large")


def test_object_key_is_server_derived():
    workspace, document = uuid4(), uuid4()
    assert storage.object_key(workspace, document) == f"ws/{workspace}/doc/{document}"
    with pytest.raises(ValueError):
        storage.object_key("../other", document)


async def chunks(*parts):
    for part in parts:
        yield part


async def test_streaming_sha256_and_size():
    upload = await storage.read_upload(chunks(b"%PDF-", b"", b"1.7 body"), 1024)
    try:
        assert upload.size == 13
        assert upload.sha256 == hashlib.sha256(b"%PDF-1.7 body").digest()
        assert upload.head == b"%PDF-1.7 body"
        assert upload.file.read() == b"%PDF-1.7 body"
    finally:
        upload.close()


async def test_streaming_limit_and_empty_body():
    with pytest.raises(ApiError) as error:
        await storage.read_upload(chunks(b"x" * 600, b"x" * 600), 1024)
    assert error.value.status == 413
    with pytest.raises(ApiError) as error:
        await storage.read_upload(chunks(), 1024)
    assert error.value.code == "empty_file"


@pytest.mark.parametrize(
    "mime,head,ok",
    [
        ("application/pdf", b"%PDF-1.4", True),
        ("application/pdf", b"MZ\x90", False),
        (storage.DOCX, b"PK\x03\x04", True),
        (storage.DOCX, b"%PDF", False),
        ("text/plain", "Xin chào".encode(), True),
        ("text/plain", "Xin chào".encode()[:-1], True),  # truncated sniff window
        ("text/plain", b"\x00\x01", False),
        ("text/plain", b"\xff\xfe", False),
    ],
)
def test_magic_bytes(mime, head, ok):
    if ok:
        storage.check_content(mime, head)
    else:
        with pytest.raises(ApiError):
            storage.check_content(mime, head)


def test_put_object_with_checksum(store):
    object_store, stub = store
    body = b"%PDF-1.7"
    digest = hashlib.sha256(body).digest()
    stub.add_response(
        "put_object",
        {},
        {
            "Bucket": "eduvia-test",
            "Key": "ws/a/doc/b",
            "Body": ANY,
            "ContentType": "application/pdf",
            "ContentLength": len(body),
            "ChecksumSHA256": base64.b64encode(digest).decode(),
        },
    )
    object_store.put(
        "ws/a/doc/b", io.BytesIO(body), mime="application/pdf", size=len(body), sha256=digest
    )


async def test_async_put_runs_in_thread(store):
    object_store, stub = store
    stub.add_response("put_object", {}, None)
    body = b"hello"
    await object_store.aput(
        "k", io.BytesIO(body), mime="text/plain", size=5, sha256=hashlib.sha256(body).digest()
    )


def test_head_missing_and_delete(store):
    object_store, stub = store
    stub.add_client_error("head_object", service_error_code="404", http_status_code=404)
    stub.add_response("head_object", {"ContentLength": 5}, {"Bucket": "eduvia-test", "Key": "k"})
    stub.add_response("delete_object", {}, {"Bucket": "eduvia-test", "Key": "k"})
    assert object_store.head("k") is None
    assert object_store.head("k")["ContentLength"] == 5
    object_store.delete("k")


def test_head_other_errors_propagate(store):
    from botocore.exceptions import ClientError

    object_store, stub = store
    stub.add_client_error("head_object", service_error_code="AccessDenied", http_status_code=403)
    with pytest.raises(ClientError):
        object_store.head("k")


def test_presigned_download_is_short_lived_attachment():
    settings = Settings(_env_file=None, s3_bucket="eduvia-test")
    object_store = storage.ObjectStore(settings, client=s3_client())
    now = datetime(2026, 10, 23, tzinfo=UTC)
    url, expires = object_store.presign_get(
        "ws/a/doc/b", file_name="Đề kiểm tra.pdf", mime="application/pdf", now=now
    )
    query = parse_qs(urlsplit(url).query)
    assert query["X-Amz-Expires"] == ["60"]
    assert (expires - now).total_seconds() == 60
    disposition = query["response-content-disposition"][0]
    assert disposition.startswith("attachment;") and "UTF-8''" in disposition
    assert query["response-content-type"] == ["application/pdf"]
    url, expires = object_store.presign_get(
        "k", file_name="a.pdf", mime="application/pdf", ttl_seconds=3600, now=now
    )
    assert parse_qs(urlsplit(url).query)["X-Amz-Expires"] == ["300"]
    assert (expires - now).total_seconds() == 300


def test_content_disposition_ascii_fallback():
    value = storage.content_disposition('Bài "1";.pdf')
    assert value.startswith('attachment; filename="B_i _1__.pdf"')
    assert "filename*=UTF-8''B%C3%A0i%20%221%22%3B.pdf" in value


def test_upload_limit_setting_bounds():
    from pydantic import ValidationError

    assert Settings(_env_file=None).upload_max_bytes == 25 * 1024 * 1024
    for value in (1024, 101 * 1024 * 1024):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, upload_max_bytes=value)
