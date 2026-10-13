"""File naming and object storage for original 835 payloads."""

import hashlib
from datetime import date
from pathlib import Path

import boto3

from app.core.config import Settings


def sha256_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def build_stored_filename(
    pattern: str,
    *,
    original_filename: str,
    payment_date: date | None,
    control_number: str | None,
    digest: str,
) -> str:
    """Apply the configured pattern.

    The default pattern is a platform convention. It is not a claim that PMAB's
    production PLUTUS_DATE format has been confirmed.
    """
    stem = Path(original_filename).stem.replace(" ", "_")[:80] or "remittance"
    values = {
        "prefix": "PLUTUS",
        "date": payment_date.strftime("%Y%m%d") if payment_date else "DATEUNKNOWN",
        "original": stem,
        "control": (control_number or "NOCONTROL")[:40],
        "hash": digest[:12],
    }
    try:
        return pattern.format(**values)
    except KeyError as exc:
        raise ValueError(f"STORED_FILENAME_PATTERN has an unknown token: {exc}") from exc


class StorageError(Exception):
    pass


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, content: bytes) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path.resolve().as_posix()

    def get(self, uri: str) -> bytes:
        return Path(uri).read_bytes()


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        if not settings.s3_bucket:
            raise StorageError("S3_BUCKET must be set when STORAGE_BACKEND=s3. Local storage was not used as a fallback.")
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix.strip("/")
        self.kms_key_id = settings.s3_kms_key_id
        self.client = boto3.client("s3", region_name=settings.aws_region)

    def put(self, key: str, content: bytes) -> str:
        object_key = f"{self.prefix}/{key}" if self.prefix else key
        extra: dict[str, str] = {"ServerSideEncryption": "AES256"}
        if self.kms_key_id:
            extra = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self.kms_key_id}
        self.client.put_object(Bucket=self.bucket, Key=object_key, Body=content, **extra)
        return f"s3://{self.bucket}/{object_key}"

    def get(self, uri: str) -> bytes:
        if not uri.startswith("s3://"):
            raise StorageError("S3 storage received a non-S3 URI")
        _, _, remainder = uri.partition("s3://")
        bucket, _, key = remainder.partition("/")
        response = self.client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()


def get_storage(settings: Settings) -> LocalStorage | S3Storage:
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    if settings.storage_backend == "local":
        return LocalStorage(settings.local_storage_path)
    raise StorageError(f"Unknown storage backend '{settings.storage_backend}'")
