"""Lean private storage (STORE-01 lean): validated API upload, one private bucket, short-lived
signed downloads. Object keys are always derived server-side; clients never choose them.
Signed URLs are bearer credentials and object keys are tenant metadata: never log either.
"""

import asyncio
import base64
import codecs
import hashlib
import tempfile
import unicodedata
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import IO, Any
from urllib.parse import quote, unquote
from uuid import UUID

from botocore.exceptions import ClientError

from app.api.identity import ApiError
from app.core.config import Settings
from app.infrastructure.storage import create_s3_client

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ALLOWED_TYPES: dict[str, tuple[str, ...]] = {
    "application/pdf": (".pdf",),
    DOCX: (".docx",),
    "text/plain": (".txt",),
}
MAX_DOWNLOAD_TTL = 300
DEFAULT_DOWNLOAD_TTL = 60
SNIFF_BYTES = 8192
SPOOL_MEMORY_BYTES = 1024 * 1024
_FORBIDDEN_NAME_CHARS = set('/\\<>:"|?*')


def normalize_mime(content_type: str | None) -> str:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime not in ALLOWED_TYPES:
        raise ApiError(
            415, "unsupported_media_type", "Chỉ hỗ trợ tệp PDF, DOCX hoặc văn bản thuần (TXT)."
        )
    return mime


def validate_file_name(raw: str | None, mime: str) -> str:
    """``X-File-Name`` is percent-encoded UTF-8 (headers are Latin-1 on the wire)."""
    invalid = ApiError(422, "invalid_file_name", "Tên tệp không hợp lệ.")
    if not raw or len(raw) > 1024:
        raise invalid
    try:
        name = unicodedata.normalize("NFC", unquote(raw, errors="strict")).strip()
    except UnicodeDecodeError:
        raise invalid from None
    if (
        not 1 <= len(name) <= 255
        or name in {".", ".."}
        or name.startswith(".")
        or any(ch in _FORBIDDEN_NAME_CHARS or unicodedata.category(ch)[0] == "C" for ch in name)
    ):
        raise invalid
    if not name.lower().endswith(ALLOWED_TYPES[mime]):
        raise ApiError(422, "file_type_mismatch", "Phần mở rộng tệp không khớp với loại tệp.")
    return name


def too_large(max_bytes: int) -> ApiError:
    return ApiError(
        413, "file_too_large", f"Tệp vượt quá giới hạn {max_bytes // (1024 * 1024)} MiB."
    )


def check_declared_size(content_length: int | None, max_bytes: int) -> None:
    if content_length is not None and content_length > max_bytes:
        raise too_large(max_bytes)


def object_key(workspace_id: UUID, document_id: UUID) -> str:
    return f"ws/{UUID(str(workspace_id))}/doc/{UUID(str(document_id))}"


@dataclass
class SpooledUpload:
    file: IO[bytes]
    size: int
    sha256: bytes
    head: bytes

    def close(self) -> None:
        self.file.close()


async def read_upload(chunks: AsyncIterator[bytes], max_bytes: int) -> SpooledUpload:
    """Stream into a spooled temp file, hashing as we go and stopping at the size limit."""
    digest = hashlib.sha256()
    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES)
    size, head = 0, b""
    try:
        async for chunk in chunks:
            if not chunk:
                continue
            size += len(chunk)
            if size > max_bytes:
                raise too_large(max_bytes)
            if len(head) < SNIFF_BYTES:
                head += chunk[: SNIFF_BYTES - len(head)]
            digest.update(chunk)
            spool.write(chunk)
        if size == 0:
            raise ApiError(422, "empty_file", "Tệp tải lên đang trống.")
    except BaseException:
        spool.close()
        raise
    spool.seek(0)
    return SpooledUpload(file=spool, size=size, sha256=digest.digest(), head=head)


def check_content(mime: str, head: bytes) -> None:
    """Cheap magic-byte check; deep parsing happens later in the sandboxed ingestion stage."""
    invalid = ApiError(422, "invalid_file_content", "Nội dung tệp không khớp với loại tệp.")
    if mime == "application/pdf" and not head.startswith(b"%PDF-"):
        raise invalid
    if mime == DOCX and not head.startswith(b"PK\x03\x04"):
        raise invalid
    if mime == "text/plain":
        if b"\x00" in head:
            raise invalid
        try:
            codecs.getincrementaldecoder("utf-8")().decode(head, final=False)
        except UnicodeDecodeError:
            raise invalid from None


def content_disposition(file_name: str) -> str:
    fallback = "".join(
        ch if ch.isascii() and ch.isprintable() and ch not in '"\\;' else "_" for ch in file_name
    )
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(file_name, safe='')}"


class ObjectTooLarge(Exception):
    """The stored object exceeds the configured limit (message is never logged)."""


class ObjectStore:
    """One private bucket. Sync methods for the worker; ``a*`` wrappers for the API."""

    def __init__(self, settings: Settings, client: Any | None = None):
        self.bucket = settings.s3_bucket
        self._settings = settings
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = create_s3_client(self._settings)
        return self._client

    def put(self, key: str, body: IO[bytes], *, mime: str, size: int, sha256: bytes) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=mime,
            ContentLength=size,
            ChecksumSHA256=base64.b64encode(sha256).decode(),
        )

    async def aput(self, key: str, body: IO[bytes], *, mime: str, size: int, sha256: bytes):
        await asyncio.to_thread(self.put, key, body, mime=mime, size=size, sha256=sha256)

    def head(self, key: str) -> dict[str, Any] | None:
        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise

    def get_bytes(self, key: str, *, max_bytes: int) -> bytes:
        """Worker-side bounded download; never reads more than ``max_bytes + 1`` bytes."""
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        try:
            data = body.read(max_bytes + 1)
        finally:
            body.close()
        if len(data) > max_bytes:
            raise ObjectTooLarge()
        return data

    def delete(self, key: str) -> None:
        """Idempotent: S3 DeleteObject succeeds for keys that no longer exist."""
        self.client.delete_object(Bucket=self.bucket, Key=key)

    async def adelete(self, key: str) -> None:
        await asyncio.to_thread(self.delete, key)

    def presign_get(
        self,
        key: str,
        *,
        file_name: str,
        mime: str,
        ttl_seconds: int = DEFAULT_DOWNLOAD_TTL,
        now: datetime | None = None,
    ) -> tuple[str, datetime]:
        ttl = max(1, min(int(ttl_seconds), MAX_DOWNLOAD_TTL))
        url = self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": content_disposition(file_name),
                "ResponseContentType": mime,
            },
            ExpiresIn=ttl,
        )
        return url, (now or datetime.now(UTC)) + timedelta(seconds=ttl)
