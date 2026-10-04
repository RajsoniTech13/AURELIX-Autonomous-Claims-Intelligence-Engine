"""
Real access tokens for tests.

Access tokens are stateless JWTs, so a test can mint one with the same function the login
endpoint uses — no fake auth, no dependency override, no bypass flag that could ever be left
switched on in production. A test that needs a role simply carries that role's token.
"""
from __future__ import annotations

from platform_backend.services.auth import issue_access_token


def auth_headers(role: str = "reviewer", username: str | None = None, user_id: int = 1) -> dict:
    token, _ = issue_access_token(user_id, username or f"test-{role}", role)
    return {"Authorization": f"Bearer {token}"}
