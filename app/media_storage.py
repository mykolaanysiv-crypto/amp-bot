from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import hashlib
import hmac
import mimetypes
from pathlib import Path
import os
import urllib.parse
import urllib.request
from uuid import uuid4

from sqlalchemy import select

from .config import Settings, get_settings
from .db import Database
from .model_domains import MediaAsset
from .time_utils import clock

MAX_MEDIA_BYTES = 20 * 1024 * 1024
ALLOWED_DOCUMENT_MIME = frozenset({"application/pdf", "image/jpeg", "image/png", "image/webp"})
ALLOWED_IMAGE_MIME = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})


@dataclass(slots=True)
class StoredMedia:
    path: str
    backend: str
    checksum_sha256: str
    size_bytes: int
    content_type: str
    asset_id: int | None = None
    storage_key: str | None = None


def checksum_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def sniff_mime(data: bytes, filename: str = "") -> str:
    """Small deterministic MIME sniffer; never trusts only the browser header."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    guessed, _ = mimetypes.guess_type(filename or "")
    return guessed or "application/octet-stream"


def validate_media_payload(
    data: bytes,
    *,
    filename: str,
    claimed_mime: str | None = None,
    image_only: bool = False,
    max_bytes: int = MAX_MEDIA_BYTES,
) -> str:
    if not data:
        raise ValueError("Файл порожній.")
    if len(data) > max_bytes:
        raise ValueError(f"Файл завеликий. Максимум — {max_bytes // (1024 * 1024)} МБ.")
    detected = sniff_mime(data, filename)
    if image_only and detected not in ALLOWED_IMAGE_MIME:
        raise ValueError("Вміст файлу не є підтримуваним зображенням JPG, PNG, WebP або GIF.")
    if not image_only and detected not in ALLOWED_DOCUMENT_MIME:
        raise ValueError("Дозволені PDF, JPG, PNG або WebP.")
    if claimed_mime:
        claimed = claimed_mime.lower().split(";", 1)[0].strip()
        # application/octet-stream is deliberately treated as unknown rather than contradictory.
        if claimed != "application/octet-stream" and claimed.startswith(("image/", "application/pdf")) and claimed != detected:
            raise ValueError(f"MIME файлу не відповідає його вмісту: заявлено {claimed}, визначено {detected}.")
    return detected


class MediaStorage:
    backend = "abstract"

    async def store(self, db: Database, data: bytes, *, category: str, filename: str, content_type: str) -> StoredMedia:
        raise NotImplementedError

    async def read_asset(self, db: Database, asset: MediaAsset) -> bytes | None:
        raise NotImplementedError

    async def object_exists(self, db: Database, asset: MediaAsset) -> bool:
        data = await self.read_asset(db, asset)
        return data is not None

    async def delete_asset_object(self, db: Database, asset: MediaAsset) -> None:
        raise NotImplementedError


class DatabaseMediaStorage(MediaStorage):
    backend = "database"

    async def store(self, db: Database, data: bytes, *, category: str, filename: str, content_type: str) -> StoredMedia:
        digest = checksum_bytes(data)
        async with db.session_factory() as session:
            asset = MediaAsset(
                category=category,
                filename=filename,
                content_type=content_type,
                detected_mime=content_type,
                data=data,
                size_bytes=len(data),
                checksum_sha256=digest,
                storage_backend=self.backend,
                lifecycle_state="active",
                last_verified_at=clock.storage_utc(),
            )
            session.add(asset)
            await session.flush()
            asset_id = asset.id
            await session.commit()
        return StoredMedia(f"/media/{asset_id}", self.backend, digest, len(data), content_type, asset_id=asset_id)

    async def read_asset(self, db: Database, asset: MediaAsset) -> bytes | None:
        return bytes(asset.data) if asset.data is not None else None

    async def delete_asset_object(self, db: Database, asset: MediaAsset) -> None:
        # Row deletion is performed by lifecycle administration. The DB blob lives on the row.
        return None


class LocalMediaStorage(MediaStorage):
    backend = "local"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings(require_bot_token=False)

    async def store(self, db: Database, data: bytes, *, category: str, filename: str, content_type: str) -> StoredMedia:
        from .security import media_access_level

        digest = checksum_bytes(data)
        root_name = "uploads" if media_access_level(category) == "public" else "private"
        folder = Path(self.settings.data_dir) / root_name / category
        folder.mkdir(parents=True, exist_ok=True)
        out = folder / filename
        out.write_bytes(data)
        path = f"/{root_name}/{category}/{filename}"
        return StoredMedia(path, self.backend, digest, len(data), content_type, storage_key=str(out))

    async def read_asset(self, db: Database, asset: MediaAsset) -> bytes | None:
        if not asset.storage_key:
            return None
        path = Path(asset.storage_key)
        try:
            return path.read_bytes() if path.exists() and path.is_file() else None
        except OSError:
            return None

    async def delete_asset_object(self, db: Database, asset: MediaAsset) -> None:
        if not asset.storage_key:
            return
        try:
            Path(asset.storage_key).unlink(missing_ok=True)
        except OSError:
            return


class S3CompatibleMediaStorage(MediaStorage):
    """Minimal SigV4 S3 client for AWS S3, Cloudflare R2 and Backblaze B2.

    No optional SDK is required in the production dependency set. Only PUT/GET/HEAD/DELETE
    primitives needed by AMP are implemented. Credentials are read from config and are never logged.
    """

    backend = "s3"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings(require_bot_token=False)
        self.endpoint = self.settings.s3_endpoint.rstrip("/")
        self.bucket = self.settings.s3_bucket
        self.region = self.settings.s3_region or "auto"
        self.access_key = self.settings.s3_access_key
        self.secret_key = self.settings.s3_secret_key
        if not all((self.endpoint, self.bucket, self.access_key, self.secret_key)):
            raise RuntimeError("S3 backend потребує S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY і S3_SECRET_KEY")

    def _key(self, category: str, filename: str) -> str:
        return f"amp-media/{category.strip('/').lower()}/{uuid4().hex}-{Path(filename).name}"

    def _request(self, method: str, key: str, *, body: bytes = b"", content_type: str = "application/octet-stream") -> tuple[int, bytes, dict[str, str]]:
        now = clock.storage_utc()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        encoded_key = urllib.parse.quote(key, safe="/-_.~")
        base = f"{self.endpoint}/{urllib.parse.quote(self.bucket, safe='')}/{encoded_key}"
        parsed = urllib.parse.urlparse(base)
        host = parsed.netloc
        payload_hash = hashlib.sha256(body).hexdigest()
        canonical_uri = parsed.path or "/"
        canonical_headers = (
            f"content-type:{content_type}\n"
            f"host:{host}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join([method, canonical_uri, "", canonical_headers, signed_headers, payload_hash])
        scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join([
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ])

        def sign(key_bytes: bytes, msg: str) -> bytes:
            return hmac.new(key_bytes, msg.encode(), hashlib.sha256).digest()

        k_date = sign(("AWS4" + self.secret_key).encode(), date_stamp)
        k_region = sign(k_date, self.region)
        k_service = sign(k_region, "s3")
        k_signing = sign(k_service, "aws4_request")
        signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
        authorization = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        headers = {
            "Content-Type": content_type,
            "Host": host,
            "X-Amz-Date": amz_date,
            "X-Amz-Content-Sha256": payload_hash,
            "Authorization": authorization,
        }
        req = urllib.request.Request(base, data=body if method in {"PUT", "POST"} else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return int(response.status), response.read(), dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return 404, b"", dict(exc.headers.items()) if exc.headers else {}
            detail = exc.read(512).decode("utf-8", "replace")
            raise RuntimeError(f"S3 {method} failed with HTTP {exc.code}: {detail}") from exc

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        status, _, _ = self._request("PUT", key, body=data, content_type=content_type)
        if status not in {200, 201, 204}:
            raise RuntimeError(f"S3 PUT returned HTTP {status}")

    def get_object(self, key: str, content_type: str = "application/octet-stream") -> bytes | None:
        status, data, _ = self._request("GET", key, content_type=content_type)
        return data if status == 200 else None

    def head_object(self, key: str, content_type: str = "application/octet-stream") -> bool:
        status, _, _ = self._request("HEAD", key, content_type=content_type)
        return status == 200

    def delete_object(self, key: str, content_type: str = "application/octet-stream") -> None:
        status, _, _ = self._request("DELETE", key, content_type=content_type)
        if status not in {200, 204, 404}:
            raise RuntimeError(f"S3 DELETE returned HTTP {status}")

    async def store(self, db: Database, data: bytes, *, category: str, filename: str, content_type: str) -> StoredMedia:
        digest = checksum_bytes(data)
        key = self._key(category, filename)
        self.put_object(key, data, content_type)
        try:
            async with db.session_factory() as session:
                asset = MediaAsset(
                    category=category,
                    filename=filename,
                    content_type=content_type,
                    detected_mime=content_type,
                    data=None,
                    size_bytes=len(data),
                    checksum_sha256=digest,
                    storage_backend=self.backend,
                    storage_key=key,
                    lifecycle_state="active",
                    last_verified_at=clock.storage_utc(),
                )
                session.add(asset)
                await session.flush()
                asset_id = asset.id
                await session.commit()
        except Exception:
            self.delete_object(key, content_type)
            raise
        return StoredMedia(f"/media/{asset_id}", self.backend, digest, len(data), content_type, asset_id=asset_id, storage_key=key)

    async def read_asset(self, db: Database, asset: MediaAsset) -> bytes | None:
        if not asset.storage_key:
            return None
        return self.get_object(asset.storage_key, asset.content_type or "application/octet-stream")

    async def object_exists(self, db: Database, asset: MediaAsset) -> bool:
        return bool(asset.storage_key and self.head_object(asset.storage_key, asset.content_type or "application/octet-stream"))

    async def delete_asset_object(self, db: Database, asset: MediaAsset) -> None:
        if asset.storage_key:
            self.delete_object(asset.storage_key, asset.content_type or "application/octet-stream")


def get_media_storage(name: str | None = None, settings: Settings | None = None) -> MediaStorage:
    cfg = settings or get_settings(require_bot_token=False)
    backend = (name or cfg.media_storage or "database").strip().lower()
    if backend == "database":
        return DatabaseMediaStorage()
    if backend == "local":
        return LocalMediaStorage(cfg)
    if backend in {"s3", "aws_s3", "r2", "b2"}:
        return S3CompatibleMediaStorage(cfg)
    raise RuntimeError(f"Непідтримуваний MEDIA_STORAGE={backend}")


async def read_media_asset_bytes(db: Database, asset: MediaAsset) -> bytes | None:
    backend = (asset.storage_backend or "database").lower()
    storage = get_media_storage(backend)
    data = await storage.read_asset(db, asset)
    # Safe migration fallback: switched S3 assets keep original DB bytes until a later reviewed cleanup.
    if data is None and asset.data is not None:
        return bytes(asset.data)
    return data
