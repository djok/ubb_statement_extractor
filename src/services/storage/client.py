"""Google Cloud Storage client singleton."""

import logging
import os
from typing import Optional

from google.cloud import storage

logger = logging.getLogger(__name__)


class GCSClient:
    """Singleton Google Cloud Storage client."""

    _instance: Optional["GCSClient"] = None

    def __new__(cls) -> "GCSClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.bucket_name = os.getenv("GCS_BUCKET", "ubb-statements")
        self.client = storage.Client()
        self.bucket = self.client.bucket(self.bucket_name)
        self._initialized = True

        logger.info(f"GCS client initialized for bucket: {self.bucket_name}")

    def blob_exists(self, path: str) -> bool:
        """Check if a blob exists at the given path."""
        blob = self.bucket.blob(path)
        return blob.exists()

    def upload_bytes(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Upload bytes to GCS and return the gs:// URI."""
        blob = self.bucket.blob(path)
        blob.upload_from_string(data, content_type=content_type)
        logger.info(f"Uploaded {len(data)} bytes to gs://{self.bucket_name}/{path}")
        return f"gs://{self.bucket_name}/{path}"

    def upload_string(self, path: str, data: str, content_type: str = "application/json") -> str:
        """Upload string data to GCS and return the gs:// URI."""
        return self.upload_bytes(path, data.encode("utf-8"), content_type)

    def download_bytes(self, path: str) -> bytes:
        """Download blob content as bytes."""
        blob = self.bucket.blob(path)
        return blob.download_as_bytes()

    def download_string(self, path: str) -> str:
        """Download blob content as string."""
        return self.download_bytes(path).decode("utf-8")

    def get_signed_url(self, path: str, expiration_minutes: int = 15) -> str:
        """Generate a signed URL for downloading the blob."""
        from datetime import timedelta

        blob = self.bucket.blob(path)
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=expiration_minutes),
            method="GET",
        )
        return url

    def list_blobs(self, prefix: str) -> list[str]:
        """List all blob paths with the given prefix."""
        blobs = self.client.list_blobs(self.bucket_name, prefix=prefix)
        return [blob.name for blob in blobs]

    def delete_blob(self, path: str) -> bool:
        """Delete a blob at the given path. Returns True if deleted."""
        blob = self.bucket.blob(path)
        if blob.exists():
            blob.delete()
            logger.info(f"Deleted gs://{self.bucket_name}/{path}")
            return True
        return False
