"""사진 저장소 추상화 — MinIO(self-host) 또는 Supabase Storage 자동 선택.

courtauction/store.py 와 bit/store.py 가 공유.

선택 규칙 (env):
  - MINIO_ENDPOINT 가 있으면 → MinIO (boto3 S3 호환)
  - 없으면 → 기존 Supabase Storage (supabase-py client.storage)

MinIO env:
  MINIO_ENDPOINT       내부 S3 API (예: http://192.168.x.x:9000)
  MINIO_ACCESS_KEY     (= MINIO_ROOT_USER)
  MINIO_SECRET_KEY     (= MINIO_ROOT_PASSWORD)
  STORAGE_PUBLIC_URL   공개 URL 베이스 (예: https://files.<domain>) — 반환 URL용
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

logger = logging.getLogger(__name__)


class StorageBackend(Protocol):
    def upload(self, bucket: str, key: str, blob: bytes, content_type: str) -> None: ...
    def public_url(self, bucket: str, key: str) -> str: ...


class MinioBackend:
    """boto3 S3 호환 — MinIO. upsert(overwrite)는 put_object 기본 동작."""

    def __init__(self) -> None:
        import boto3  # lazy — MinIO 안 쓰면 boto3 불필요
        from botocore.client import Config

        self.endpoint = os.environ["MINIO_ENDPOINT"].rstrip("/")
        self.public_base = (
            os.environ.get("STORAGE_PUBLIC_URL") or self.endpoint
        ).rstrip("/")
        self._s3 = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=os.environ["MINIO_ACCESS_KEY"],
            aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )

    def upload(self, bucket: str, key: str, blob: bytes,
               content_type: str = "image/jpeg") -> None:
        self._s3.put_object(
            Bucket=bucket, Key=key, Body=blob, ContentType=content_type,
        )

    def public_url(self, bucket: str, key: str) -> str:
        return f"{self.public_base}/{bucket}/{key}"


class SupabaseBackend:
    """기존 Supabase Storage — supabase-py client 재사용."""

    def __init__(self, sb_client) -> None:
        self.sb = sb_client

    def upload(self, bucket: str, key: str, blob: bytes,
               content_type: str = "image/jpeg") -> None:
        self.sb.storage.from_(bucket).upload(
            path=key, file=blob,
            file_options={"content-type": content_type, "upsert": "true"},
        )

    def public_url(self, bucket: str, key: str) -> str:
        return self.sb.storage.from_(bucket).get_public_url(key)


def make_storage(sb_client=None) -> StorageBackend:
    """MINIO_ENDPOINT 있으면 MinIO, 없으면 Supabase.

    sb_client: Supabase fallback 용 (MinIO 모드면 무시).
    """
    if os.environ.get("MINIO_ENDPOINT"):
        logger.info("storage backend: MinIO (%s)", os.environ["MINIO_ENDPOINT"])
        return MinioBackend()
    if sb_client is None:
        raise RuntimeError(
            "no MINIO_ENDPOINT and no supabase client — storage backend 없음"
        )
    logger.info("storage backend: Supabase Storage")
    return SupabaseBackend(sb_client)
