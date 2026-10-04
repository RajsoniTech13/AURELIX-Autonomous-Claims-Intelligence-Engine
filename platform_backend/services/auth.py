"""
Authentication: who is calling, proven by a token.

**Two tokens, two jobs.**

* The **access token** is a JWT (HS256), valid for 15 minutes, sent as
  `Authorization: Bearer ...` on every request. It is *stateless*: verifying it needs the
  signing key, not a database read, so every request does not cost a query. The price is that
  it cannot be revoked early — which is why it lives only 15 minutes.
* The **refresh token** is an opaque random string, valid for 7 days, stored server-side
  only as a SHA-256 hash. It is exchanged for a new access token, and **rotated on every use**:
  the old one is revoked and a new one issued in the same family. Presenting an
  already-rotated token means someone else holds a copy, so the whole family is revoked.

**Why tokens in the response body rather than httpOnly cookies.** The frontend (Vercel) and
the API (Render) are different sites, so a refresh cookie would be a third-party cookie, which
Safari blocks outright and other browsers are phasing out. Cookies would be the stronger design
on a shared domain (`api.aurelix.space`), and `docs/SECURITY.md` says so. Until then the access
token stays in memory and the refresh token in browser storage, with rotation and reuse
detection limiting what a stolen one is worth.

**Passwords** are hashed with Argon2id at the OWASP minimum (19 MiB, 2 iterations, 1 lane) —
argon2-cffi's default is 64 MiB per hash, too much to spend per login on a 512 MB instance.
Demo accounts have no password and cannot use the password login at all.

**The signing key** comes from `AURELIX_JWT_SECRET`. Without one, a random key is generated
per process: tokens stop working at the next restart and everyone signs in again, which is a
safe failure — the alternative, a default key in the repository, would let anyone forge a token.
"""
from __future__ import annotations

import datetime
import hashlib
import logging
import os
import secrets
import uuid
from dataclasses import dataclass
from typing import List, Optional, Tuple

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from platform_backend.db.models import RefreshToken, User

logger = logging.getLogger("aurelix.auth")

ROLES = ("claimant", "reviewer", "admin")
REVIEW_ROLES = frozenset({"reviewer", "admin"})
DEMO_ROLES = ("claimant", "reviewer")

ALGORITHM = "HS256"
ISSUER = "aurelix"
ACCESS_TOKEN_SECONDS = int(os.getenv("ACCESS_TOKEN_MINUTES", "15")) * 60
REFRESH_TOKEN_SECONDS = int(os.getenv("REFRESH_TOKEN_DAYS", "7")) * 86400

_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
# Verified against when a username does not exist, so "no such user" and "wrong password"
# take the same time and an attacker cannot enumerate accounts by timing the response.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

_generated_secret: Optional[str] = None


class AuthError(Exception):
    """A credential or token was rejected. The message is safe to show the caller."""


@dataclass(frozen=True)
class Principal:
    """The verified caller of one request."""
    user_id: int
    username: str
    role: str

    @property
    def is_reviewer(self) -> bool:
        return self.role in REVIEW_ROLES


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


# ─── Keys ───────────────────────────────────────────────────────────────────

def jwt_secret() -> str:
    global _generated_secret
    configured = os.getenv("AURELIX_JWT_SECRET", "")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("AURELIX_JWT_SECRET must be at least 32 characters")
        return configured
    if _generated_secret is None:
        _generated_secret = secrets.token_urlsafe(48)
        logger.warning("[Auth] AURELIX_JWT_SECRET is not set; using a random per-process key. "
                       "Sessions will not survive a restart.")
    return _generated_secret


# ─── Passwords ──────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("passwords must be at least 12 characters")
    return _hasher.hash(password)


def verify_password(password_hash: Optional[str], password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def authenticate(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        verify_password(None, password)          # same work as a real check
        return None
    if not user.is_active or user.is_demo or not verify_password(user.password_hash, password):
        return None
    return user


# ─── Access tokens ──────────────────────────────────────────────────────────

def issue_access_token(user_id: int, username: str, role: str) -> Tuple[str, int]:
    now = int(_now().replace(tzinfo=datetime.timezone.utc).timestamp())
    payload = {
        "iss": ISSUER, "sub": str(user_id), "name": username, "role": role,
        "typ": "access", "iat": now, "exp": now + ACCESS_TOKEN_SECONDS,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, jwt_secret(), algorithm=ALGORITHM), ACCESS_TOKEN_SECONDS


def decode_access_token(token: str) -> Principal:
    """
    Verify signature, expiry, issuer and type. `algorithms` is pinned: accepting whatever
    algorithm the token header names is how `alg: none` forgeries get through.
    """
    try:
        payload = jwt.decode(
            token, jwt_secret(), algorithms=[ALGORITHM], issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "role", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Your session has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid credentials.") from exc
    if payload.get("typ") != "access" or payload.get("role") not in ROLES:
        raise AuthError("Invalid credentials.")
    return Principal(user_id=int(payload["sub"]), username=str(payload.get("name", "")),
                     role=str(payload["role"]))


# ─── Refresh tokens ─────────────────────────────────────────────────────────

def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_refresh_token(db: Session, user: User, family_id: Optional[str] = None) -> Tuple[str, RefreshToken]:
    raw = secrets.token_urlsafe(32)
    row = RefreshToken(
        user_id=user.id, token_hash=_digest(raw), family_id=family_id or str(uuid.uuid4()),
        expires_at=_now() + datetime.timedelta(seconds=REFRESH_TOKEN_SECONDS),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return raw, row


def _revoke_family(db: Session, family_id: str) -> None:
    now = _now()
    db.query(RefreshToken).filter(
        RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None),
    ).update({RefreshToken.revoked_at: now}, synchronize_session=False)
    db.commit()


def rotate_refresh_token(db: Session, raw: str) -> Tuple[User, str]:
    """
    Exchange a refresh token for a new one. Raises AuthError on any problem, and on reuse of
    an already-rotated token revokes the entire family before raising.
    """
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == _digest(raw or "")).first()
    if row is None:
        raise AuthError("Invalid credentials.")
    if row.revoked_at is not None:
        # Rotated or revoked already: either a replay by an attacker, or by the user after an
        # attacker rotated first. There is no telling which, so neither keeps a session.
        _revoke_family(db, row.family_id)
        logger.warning("[Auth] refresh token reuse detected; family %s revoked", row.family_id)
        raise AuthError("Your session was ended. Please sign in again.")
    if row.expires_at <= _now():
        raise AuthError("Your session has expired.")
    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None or not user.is_active:
        _revoke_family(db, row.family_id)
        raise AuthError("Invalid credentials.")

    new_raw, new_row = issue_refresh_token(db, user, family_id=row.family_id)
    row.revoked_at = _now()
    row.replaced_by_id = new_row.id
    db.commit()
    return user, new_raw


def revoke_refresh_token(db: Session, raw: str) -> None:
    """Sign out: end this token's whole family. Unknown tokens are ignored, not reported."""
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == _digest(raw or "")).first()
    if row is not None:
        _revoke_family(db, row.family_id)


# ─── Accounts ───────────────────────────────────────────────────────────────

def demo_login_enabled() -> bool:
    """On unless switched off: this deployment is a public demonstration."""
    return os.getenv("AURELIX_DEMO_LOGIN", "1").strip().lower() not in {"0", "false", "no", "off"}


def create_demo_user(db: Session, role: str) -> User:
    """
    A fresh account per demo visitor, so two visitors trying the claimant view never see
    each other's claims. No password: it cannot be signed into again once its session ends.
    """
    if role not in DEMO_ROLES:
        raise ValueError(f"demo role must be one of {DEMO_ROLES}")
    for _ in range(5):
        user = User(username=f"demo-{role}-{secrets.token_hex(4)}", role=role, is_demo=True)
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        db.refresh(user)
        return user
    raise RuntimeError("could not allocate a demo username")


def parse_seed_users(spec: str) -> List[Tuple[str, str, str]]:
    """
    `AURELIX_SEED_USERS="alice:reviewer:<password>;bob:admin:<password>"`. Passwords may
    contain ':'; only the first two separators split.
    """
    users = []
    for entry in [e.strip() for e in (spec or "").split(";") if e.strip()]:
        parts = entry.split(":", 2)
        if len(parts) != 3 or parts[1] not in ROLES or not parts[0]:
            raise ValueError("each AURELIX_SEED_USERS entry must be username:role:password")
        users.append((parts[0], parts[1], parts[2]))
    return users


def seed_users(db: Session, spec: Optional[str] = None) -> int:
    """Create or update the configured accounts. Idempotent; called at startup."""
    count = 0
    for username, role, password in parse_seed_users(spec if spec is not None else os.getenv("AURELIX_SEED_USERS", "")):
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            user = User(username=username, role=role, is_demo=False)
            db.add(user)
        if not verify_password(user.password_hash, password):
            user.password_hash = hash_password(password)
        user.role = role
        user.is_active = True
        count += 1
    db.commit()
    return count
