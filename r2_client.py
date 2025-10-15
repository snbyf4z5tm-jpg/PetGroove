# r2_client.py
import uuid
from typing import Optional

import boto3
from botocore.config import Config

from settings import settings

# --- R2 / S3 client ---------------------------------------------------------

# NOTE:
# - endpoint_url MUST be the S3 API endpoint (the cloudflarestorage.com host),
#   NOT the public/dev domain. Region must be "auto" and path-style is required.
_endpoint = getattr(settings, "r2_endpoint_url", None)
_BUCKET = getattr(settings, "r2_bucket", None)
if _endpoint:
    # Normalize accidental trailing slashes or bucket suffixes
    _endpoint = _endpoint.rstrip("/")
    if _BUCKET and _endpoint.endswith(f"/{_BUCKET}"):
        _endpoint = _endpoint[: - (len(_BUCKET) + 1)]

_s3 = boto3.client(
    "s3",
    endpoint_url=_endpoint,   # e.g. https://<account>.r2.cloudflarestorage.com
    aws_access_key_id=getattr(settings, "r2_access_key_id", None),
    aws_secret_access_key=getattr(settings, "r2_secret_access_key", None),
    region_name="auto",
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)

_PUBLIC_BASE = (getattr(settings, "r2_public_base", None) or "").rstrip("/")


# --- Helpers ----------------------------------------------------------------

def _safe_key(suffix: str = ".mp4") -> str:
    """Generate a unique object key under a 'renders/' prefix."""
    return f"renders/{uuid.uuid4().hex}{suffix}"


def _public_or_signed_url(key: str, expires: int = 3600) -> str:
    """
    Prefer the configured public base (custom domain / r2.dev) for read URLs.
    Fall back to a presigned GET URL if no public base is set.
    """
    if _PUBLIC_BASE:
        return f"{_PUBLIC_BASE}/{key.lstrip('/')}"
    # Fallback: presigned GET
    return _s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": _BUCKET, "Key": key},
        ExpiresIn=expires,
    )


# --- API used by the app -----------------------------------------------------

def upload_bytes_and_get_url(
    data: bytes,
    *,
    key: Optional[str] = None,
    content_type: str = "video/mp4",
    expires: int = 3600,
) -> str:
    """
    Uploads bytes to R2 and returns the URL the client should use to fetch.
    If R2_PUBLIC_BASE is set, returns a public URL (no query string).
    Otherwise returns a time-limited presigned GET URL.
    """
    if key is None:
        key = _safe_key(suffix=".mp4")

    _s3.put_object(
        Bucket=_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return _public_or_signed_url(key, expires=expires)


def upload_to_key(
    data: bytes,
    key: str,
    *,
    content_type: str = "video/mp4",
) -> None:
    """
    Low-level upload: PUT the object to a specific key. Does not return a URL.
    """
    _s3.put_object(
        Bucket=_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type,
    )


def get_object_stream(key: str):
    """
    Returns (streaming_body, content_type) for the given key.
    Useful for the /files/{key} streaming route.
    """
    obj = _s3.get_object(Bucket=_BUCKET, Key=key)
    return obj["Body"], obj.get("ContentType", "application/octet-stream")


# --- Optional convenience: explicit signed GET -------------------------------

def get_signed_get_url(key: str, *, expires: int = 3600) -> str:
    """
    Always return a presigned GET URL (ignores R2_PUBLIC_BASE).
    Handy if you need a one-off signed link.
    """
    return _s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": _BUCKET, "Key": key},
        ExpiresIn=expires,
    )
