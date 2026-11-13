"""Yandex Object Storage (S3). Файлы организации лежат по пути {organization_id}/{файл}."""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

import boto3
from botocore.config import Config

from .config import settings

log = logging.getLogger(__name__)


class StorageError(Exception):
    pass


@dataclass
class StoredFile:
    name: str
    key: str
    size: int
    etag: str
    modified: datetime


def enabled() -> bool:
    return bool(settings.s3_bucket and settings.s3_access_key_id and settings.s3_secret_access_key)


@lru_cache
def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=30, retries={"max_attempts": 3}),
    )


def safe_name(filename: str) -> str:
    """Имя файла без путей: загрузка не может выйти за префикс своей организации."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip().strip(".")
    if not name:
        raise StorageError("Пустое имя файла")
    return name[:200]


def prefix(org_id: int) -> str:
    return f"{int(org_id)}/"


def key_for(org_id: int, filename: str) -> str:
    return prefix(org_id) + safe_name(filename)


def _require() -> None:
    if not enabled():
        raise StorageError("Хранилище файлов не настроено (S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY)")


async def put(org_id: int, filename: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    _require()
    key = key_for(org_id, filename)
    await asyncio.to_thread(
        _client().put_object, Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type
    )
    return key


async def list_files(org_id: int) -> list[StoredFile]:
    _require()

    def _list() -> list[StoredFile]:
        out, token = [], None
        while True:
            kw = {"Bucket": settings.s3_bucket, "Prefix": prefix(org_id)}
            if token:
                kw["ContinuationToken"] = token
            resp = _client().list_objects_v2(**kw)
            for o in resp.get("Contents", []):
                name = o["Key"][len(prefix(org_id)):]
                if name and not name.endswith("/"):  # «папки» пропускаем
                    out.append(StoredFile(name, o["Key"], o["Size"], o["ETag"].strip('"'), o["LastModified"]))
            if not resp.get("IsTruncated"):
                return out
            token = resp["NextContinuationToken"]

    return await asyncio.to_thread(_list)


async def get(key: str) -> bytes:
    _require()
    resp = await asyncio.to_thread(_client().get_object, Bucket=settings.s3_bucket, Key=key)
    return await asyncio.to_thread(resp["Body"].read)


async def delete(org_id: int, filename: str) -> None:
    _require()
    await asyncio.to_thread(_client().delete_object, Bucket=settings.s3_bucket, Key=key_for(org_id, filename))
