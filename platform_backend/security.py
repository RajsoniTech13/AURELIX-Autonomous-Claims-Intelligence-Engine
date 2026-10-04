"""
Authorisation: what the verified caller may do.

Every route declares its rule with one dependency, so the rule is visible where the route is:

    principal: Principal = Depends(current_principal)   # any signed-in account
    principal: Principal = Depends(require_reviewer)    # reviewer or admin only

| resource                               | claimant          | reviewer / admin |
|----------------------------------------|-------------------|------------------|
| submit a claim                         | as themselves     | on anyone's behalf |
| read a claim, its job, its explanation | their own only    | all              |
| review queue, verdicts, analytics      | no (403)          | yes              |
| Policy Copilot, LLM metrics            | no (403)          | yes              |
| claim photographs and documents        | via signed URL from a claim they may read |  |

**Another claimant's claim is a 404, not a 403.** A 403 would confirm that claim 42 exists
and belongs to someone else; a 404 says nothing at all.

**Photographs are served by signed, expiring URLs.** An `<img>` tag cannot send an
`Authorization` header, so the claim response carries URLs signed with HMAC-SHA256 over the
file name and an expiry. A URL is only ever minted after the ownership check passes, so
holding one proves the holder was allowed to see that claim within the last few minutes.
UUID file names alone were obscurity, not access control.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Dict, Iterable, Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_backend.services.auth import AuthError, Principal, decode_access_token, jwt_secret

_bearer = HTTPBearer(auto_error=False)

ASSET_URL_SECONDS = int(os.getenv("ASSET_URL_SECONDS", "900"))
UPLOAD_PREFIX = "uploads/"


def _unauthorised(message: str) -> HTTPException:
    return HTTPException(status_code=401, detail=message, headers={"WWW-Authenticate": "Bearer"})


def current_principal(credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorised("Sign in to continue.")
    try:
        return decode_access_token(credentials.credentials)
    except AuthError as exc:
        raise _unauthorised(str(exc))


def require_roles(*roles: str):
    allowed = frozenset(roles)

    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(status_code=403, detail="Your role does not have access to this.")
        return principal

    return dependency


require_reviewer = require_roles("reviewer", "admin")
require_admin = require_roles("admin")


def can_read(principal: Principal, owner_user_id: Optional[str]) -> bool:
    return principal.is_reviewer or (owner_user_id is not None and owner_user_id == principal.username)


def ensure_can_read(principal: Principal, owner_user_id: Optional[str], what: str = "Claim") -> None:
    if not can_read(principal, owner_user_id):
        raise HTTPException(status_code=404, detail=f"{what} not found")


def submitter_id(principal: Principal, requested: Optional[str]) -> str:
    """
    Whose claim this is. A claimant always submits as themselves — the form field is
    ignored, because trusting it is what let anyone submit as anyone. A reviewer may submit
    on behalf of a policyholder id, which is how the demo still exercises claim history.
    """
    if principal.is_reviewer and requested and requested.strip():
        return requested.strip()[:50]
    return principal.username


# ─── Signed asset URLs ──────────────────────────────────────────────────────

def _asset_key() -> bytes:
    # Derived, not reused: the token-signing key never signs anything but tokens.
    return hmac.new(jwt_secret().encode(), b"aurelix-asset-url-v1", hashlib.sha256).digest()


def _signature(name: str, expires: int) -> str:
    return hmac.new(_asset_key(), f"{name}:{expires}".encode(), hashlib.sha256).hexdigest()


def sign_asset(path: str, ttl_seconds: Optional[int] = None) -> Optional[str]:
    """`uploads/<name>` → `uploads/<name>?exp=...&sig=...`, or None for anything else."""
    if not path or not path.startswith(UPLOAD_PREFIX):
        return None
    name = path[len(UPLOAD_PREFIX):]
    if not name or "/" in name or "\\" in name:
        return None
    expires = int(time.time()) + int(ttl_seconds or ASSET_URL_SECONDS)
    return f"{path}?exp={expires}&sig={_signature(name, expires)}"


def verify_asset(name: str, expires: Optional[str], signature: Optional[str]) -> bool:
    try:
        exp = int(expires or "")
    except ValueError:
        return False
    if exp < int(time.time()) or not signature:
        return False
    return hmac.compare_digest(_signature(name, exp), signature)


def signed_assets(paths: Iterable[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for path in paths:
        url = sign_asset(path)
        if url:
            out[path] = url
    return out
