import hashlib
import hmac
from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from app.core.config import get_settings


def verify_github_signature(payload: bytes, signature_header: str | None, secret: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature.

    GitHub sends header: X-Hub-Signature-256: sha256=<hex>
    """
    if not signature_header or not secret:
        return False

    try:
        scheme, signature = signature_header.split("=", 1)
    except ValueError:
        return False

    if scheme.lower() != "sha256":
        return False

    expected = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


async def require_github_signature(
    request: Request,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> bytes:
    """FastAPI dependency: verify signature and return raw body.

    Raises 401 if missing or invalid.
    """
    body = await request.body()
    settings = get_settings()
    secret = settings.github_webhook_secret

    if not verify_github_signature(body, x_hub_signature_256, secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing GitHub webhook signature",
        )
    return body
