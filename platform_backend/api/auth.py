"""
Sign-in endpoints.

    POST /api/v1/auth/login     {username, password}      -> tokens
    POST /api/v1/auth/demo      {role: claimant|reviewer} -> tokens for a fresh demo account
    POST /api/v1/auth/refresh   {refresh_token}           -> rotated tokens
    POST /api/v1/auth/logout    {refresh_token}           -> 204, the token's family revoked
    GET  /api/v1/auth/me                                  -> the current account

Every failure says the same thing — "Invalid credentials." — whether the username does not
exist, the password is wrong, or the account is a demo account. Different messages would
tell an attacker which usernames are real.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from platform_backend.db.models import User
from platform_backend.db.session import get_db
from platform_backend.security import current_principal
from platform_backend.services import auth, demo_guard
from platform_backend.services.rate_limit import enforce, rate_limits, window

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=256)


class DemoBody(BaseModel):
    role: Literal["claimant", "reviewer"]


class RefreshBody(BaseModel):
    refresh_token: str = Field(..., min_length=1, max_length=256)


def _tokens(db: Session, user: User, refresh_raw: str | None = None) -> dict:
    access, expires_in = auth.issue_access_token(user.id, user.username, user.role)
    if refresh_raw is None:
        refresh_raw, _ = auth.issue_refresh_token(db, user)
    return {
        "access_token": access, "token_type": "bearer", "expires_in": expires_in,
        "refresh_token": refresh_raw,
        "user": {"username": user.username, "role": user.role, "is_demo": user.is_demo},
    }


def _client(request: Request) -> str:
    return demo_guard.visitor_key(request.client.host if request.client else None,
                                  request.headers.get("x-forwarded-for"))


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    key = f"login:{body.username.lower()}"
    limit = int(rate_limits().get("failed_logins_per_15_minutes", 0))
    # Checked before the password is, so a locked-out username costs no hashing work.
    if limit and (wait := window.check(key, limit, 900, record=False)) is not None:
        raise HTTPException(status_code=429, detail=f"Too many failed sign-ins. Try again in {int(wait)} seconds.",
                            headers={"Retry-After": str(int(wait))})
    user = auth.authenticate(db, body.username, body.password)
    if user is None:
        window.record(key)
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    return _tokens(db, user)


@router.post("/demo")
def demo_login(body: DemoBody, request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    if not auth.demo_login_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    enforce(f"demo:{_client(request)}", "demo_logins_per_hour", 3600, "demo sign-ins")
    return _tokens(db, auth.create_demo_user(db, body.role))


@router.post("/refresh")
def refresh(body: RefreshBody, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    try:
        user, new_refresh = auth.rotate_refresh_token(db, body.refresh_token)
    except auth.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"})
    return _tokens(db, user, refresh_raw=new_refresh)


@router.post("/logout", status_code=204)
def logout(body: RefreshBody, db: Session = Depends(get_db)):
    auth.revoke_refresh_token(db, body.refresh_token)
    return Response(status_code=204)


@router.get("/me")
def me(principal: auth.Principal = Depends(current_principal)):
    return {"username": principal.username, "role": principal.role}


@router.get("/config")
def auth_config():
    """What the sign-in screen should offer. Public: it contains no secret."""
    return {"demo_login": auth.demo_login_enabled(), "demo_roles": list(auth.DEMO_ROLES)}
