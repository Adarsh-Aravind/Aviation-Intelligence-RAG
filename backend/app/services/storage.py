"""Minimal Supabase Storage client (REST via httpx) — avoids pulling in the full supabase SDK."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    pass


class FileTooLargeError(StorageError):
    pass


class TransientStorageError(StorageError):
    """Network problem or 5xx from Supabase — worth retrying later (home internet outages)."""


@dataclass(slots=True)
class DownloadResult:
    size: int
    sha256: str


class ObjectStorage(Protocol):
    @property
    def configured(self) -> bool: ...
    def create_signed_upload_url(self, path: str) -> str: ...
    def create_signed_read_url(self, path: str, expires_in: int) -> str: ...
    def download_to(self, path: str, dest: Path, max_bytes: int) -> DownloadResult: ...
    def delete(self, path: str) -> None: ...


class SupabaseStorage:
    def __init__(self, base_url: str, service_key: str, bucket: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.bucket = bucket
        self._service_key = service_key
        headers = {"apikey": service_key}
        # Legacy service_role keys are JWTs and also go in Authorization. New `sb_secret_...` keys are
        # not JWTs and must only be sent as `apikey` (the gateway maps them to the service role).
        if service_key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {service_key}"
        self._client = httpx.Client(base_url=f"{self.base_url}/storage/v1", headers=headers, timeout=timeout)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self._service_key)

    def close(self) -> None:
        self._client.close()

    def _check(self, resp: httpx.Response, action: str) -> None:
        if resp.status_code >= 500:
            raise TransientStorageError(f"storage {action} failed: {resp.status_code}")
        if resp.status_code >= 400:
            # Never log headers (they contain the service key); body is safe.
            raise StorageError(f"storage {action} failed: {resp.status_code} {resp.text[:200]}")

    def ensure_bucket(self, max_bytes: int) -> None:
        resp = self._client.get(f"/bucket/{self.bucket}")
        if resp.status_code == 200:
            return
        resp = self._client.post(
            "/bucket",
            json={
                "id": self.bucket,
                "name": self.bucket,
                "public": False,
                "file_size_limit": max_bytes,
                "allowed_mime_types": ["application/pdf"],
            },
        )
        if resp.status_code not in (200, 201, 409):
            self._check(resp, "create bucket")
        logger.info("storage bucket '%s' ready", self.bucket)

    def create_signed_upload_url(self, path: str) -> str:
        # x-upsert lets an admin retry an interrupted upload to the same path.
        resp = self._client.post(f"/object/upload/sign/{self.bucket}/{path}", headers={"x-upsert": "true"})
        self._check(resp, "sign upload")
        return f"{self.base_url}/storage/v1{resp.json()['url']}"

    def create_signed_read_url(self, path: str, expires_in: int) -> str:
        resp = self._client.post(f"/object/sign/{self.bucket}/{path}", json={"expiresIn": expires_in})
        self._check(resp, "sign read")
        return f"{self.base_url}/storage/v1{resp.json()['signedURL']}"

    def download_to(self, path: str, dest: Path, max_bytes: int) -> DownloadResult:
        """Stream an object to disk (never fully in memory), enforcing a size cap and hashing it."""
        try:
            return self._download_to(path, dest, max_bytes)
        except httpx.TransportError as exc:
            raise TransientStorageError(f"network error during download: {exc.__class__.__name__}") from exc

    def _download_to(self, path: str, dest: Path, max_bytes: int) -> DownloadResult:
        digest = hashlib.sha256()
        size = 0
        with self._client.stream("GET", f"/object/authenticated/{self.bucket}/{path}") as resp:
            if resp.status_code == 404 or resp.status_code == 400:
                raise StorageError("uploaded file not found in storage")
            self._check(resp, "download")
            with open(dest, "wb") as fh:
                for block in resp.iter_bytes(64 * 1024):
                    size += len(block)
                    if size > max_bytes:
                        raise FileTooLargeError("file exceeds the upload size limit")
                    digest.update(block)
                    fh.write(block)
        return DownloadResult(size=size, sha256=digest.hexdigest())

    def delete(self, path: str) -> None:
        resp = self._client.request("DELETE", f"/object/{self.bucket}", json={"prefixes": [path]})
        self._check(resp, "delete")
