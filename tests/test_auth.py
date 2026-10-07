"""
Authentication and authorisation.

Before Phase 7, `user_id` was a form field: anyone could submit as anyone and read any claim
by id, and every photograph was served to anyone holding its URL. These tests pin the
replacement, against the real app and real tokens:

* no token → 401; a forged, expired, `alg: none` or wrong-type token → 401;
* the wrong role → 403; another claimant's claim, job or explanation → 404;
* photographs only through signed, expiring URLs, minted only for a caller who may read them;
* refresh tokens rotate, a reused one revokes its whole family, sign-out revokes too;
* passwords: Argon2id, one message for every failure, brute force rate-limited;
* the demo capacity guard can no longer be bypassed through `/api/v1/claims`.
"""
from __future__ import annotations

import io
import json
import time

import jwt
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from platform_backend.security import sign_asset
from platform_backend.services import auth
from tests.auth_helpers import auth_headers
from tests.test_backend_pipeline import GeminiSpy


@pytest.fixture
def api(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from platform_backend.db import session as session_module
    from platform_backend.db.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Testing = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(session_module, "engine", engine)
    monkeypatch.setattr(session_module, "SessionLocal", Testing)
    from platform_backend.services import jobs as job_service
    monkeypatch.setattr(job_service, "SessionLocal", Testing)
    monkeypatch.setattr("agent_core.agents.perception.call_gemini_multimodal", GeminiSpy())
    monkeypatch.setenv("AURELIX_SEED_USERS", "rita:reviewer:correct-horse-battery;adam:admin:another-long-password")

    from platform_backend.main import app

    def override():
        db = Testing()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[session_module.get_db] = override
    with TestClient(app) as client:          # anonymous: each test chooses its own headers
        client.Testing = Testing  # type: ignore[attr-defined]
        yield client
    app.dependency_overrides.clear()
    job_service.shutdown(wait=True)


def jpeg() -> bytes:
    arr = np.random.default_rng(0).integers(40, 215, (620, 900, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, "JPEG", quality=92)
    return buf.getvalue()


def submit(client, headers, user_id="user_002"):
    response = client.post(
        "/claims/submit-multimodal-stream", headers=headers,
        data={"user_id": user_id, "user_claim": "The front bumper is dented.", "claim_object": "car"},
        files=[("files", ("a.jpg", jpeg(), "image/jpeg"))],
    )
    assert response.status_code == 200, response.text
    return next(json.loads(l[6:])["claim"] for l in response.text.splitlines()
                if l.startswith("data: ") and '"done"' in l)


ALICE = auth_headers("claimant", "alice", user_id=101)
BOB = auth_headers("claimant", "bob", user_id=102)
REVIEWER = auth_headers("reviewer", "rita", user_id=201)


# ─── 401: no token, bad token ───────────────────────────────────────────────

PROTECTED = [
    ("get", "/claims"), ("get", "/claims/1"), ("get", "/queue"), ("get", "/analytics"),
    ("post", "/queue/1/verdict"), ("post", "/claims/submit-multimodal-stream"),
    ("get", "/api/v1/claims"), ("get", "/api/v1/claims/1"), ("get", "/api/v1/claims/1/explanation"),
    ("get", "/api/v1/jobs/x"), ("post", "/api/v1/claims"), ("post", "/api/v1/copilot/ask"),
    ("get", "/api/v1/metrics/llm"), ("get", "/api/v1/auth/me"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_every_protected_route_refuses_an_anonymous_caller(api, method, path):
    response = getattr(api, method)(path)
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.parametrize("path", ["/health", "/ready", "/demo/status", "/api/v1/auth/config", "/"])
def test_public_routes_stay_public(api, path):
    assert api.get(path).status_code == 200


def _token(**overrides) -> str:
    now = int(time.time())
    payload = {"iss": "aurelix", "sub": "101", "name": "alice", "role": "claimant", "typ": "access",
               "iat": now, "exp": now + 600}
    payload.update(overrides)
    return jwt.encode(payload, auth.jwt_secret(), algorithm="HS256")


@pytest.mark.parametrize("token", [
    "not-a-jwt",
    _token(exp=int(time.time()) - 5),                       # expired
    _token(typ="refresh"),                                  # wrong type
    _token(role="superuser"),                               # unknown role
    _token(iss="someone-else"),                             # wrong issuer
    jwt.encode({"sub": "101", "role": "admin", "typ": "access", "iss": "aurelix",
                "iat": int(time.time()), "exp": int(time.time()) + 600},
               "a-different-secret-that-is-long-enough", algorithm="HS256"),   # forged
])
def test_a_bad_token_is_401(api, token):
    assert api.get("/claims", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_an_unsigned_alg_none_token_is_rejected(api):
    """The classic forgery: a token that declares no algorithm and carries no signature."""
    import base64
    def b64(d): return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    forged = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': '1', 'role': 'admin', 'typ': 'access', 'iss': 'aurelix', 'iat': 1, 'exp': 9999999999})}."
    assert api.get("/queue", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_an_expired_session_says_so(api):
    response = api.get("/claims", headers={"Authorization": f"Bearer {_token(exp=int(time.time()) - 5)}"})
    assert response.json()["detail"] == "Your session has expired."


# ─── 403: wrong role ────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,body", [
    ("get", "/queue", None), ("get", "/analytics", None),
    ("post", "/queue/1/verdict", {"verdict": "approved", "notes": ""}),
    ("post", "/api/v1/copilot/ask", {"question": "Is rust covered?"}),
    ("get", "/api/v1/metrics/llm", None),
])
def test_a_claimant_cannot_use_reviewer_tools(api, method, path, body):
    kwargs = {"headers": ALICE}
    if body is not None:
        kwargs["json"] = body
    assert getattr(api, method)(path, **kwargs).status_code == 403


def test_the_legacy_server_path_submission_is_admin_only(api):
    body = {"user_id": "u", "image_paths": "tests/fixtures/images/car_damage.jpg",
            "user_claim": "x", "claim_object": "car"}
    assert api.post("/claims/submit", json=body, headers=REVIEWER).status_code == 403


# ─── Ownership ──────────────────────────────────────────────────────────────

def test_a_claimant_always_submits_as_themselves(api):
    claim = submit(api, ALICE, user_id="user_002")         # tries to claim as someone else
    assert claim["user_id"] == "alice"


def test_a_reviewer_may_submit_on_a_policyholders_behalf(api):
    assert submit(api, REVIEWER, user_id="user_002")["user_id"] == "user_002"


def test_another_claimants_claim_does_not_exist_for_you(api):
    claim = submit(api, ALICE)
    for path in (f"/claims/{claim['id']}", f"/api/v1/claims/{claim['id']}",
                 f"/api/v1/claims/{claim['id']}/explanation"):
        assert api.get(path, headers=BOB).status_code == 404, path      # 404, not 403
        assert api.get(path, headers=ALICE).status_code == 200, path
        assert api.get(path, headers=REVIEWER).status_code == 200, path
    assert api.get("/claims", headers=BOB).json() == []
    assert api.get("/api/v1/claims", headers=BOB).json()["items"] == []
    assert [c["id"] for c in api.get("/claims", headers=ALICE).json()] == [claim["id"]]


def test_another_claimants_job_does_not_exist_for_you(api):
    response = api.post("/api/v1/claims", headers=ALICE,
                        data={"user_claim": "The front bumper is dented.", "claim_object": "car"},
                        files=[("files", ("a.jpg", jpeg(), "image/jpeg"))])
    job_id = response.json()["job_id"]
    assert api.get(f"/api/v1/jobs/{job_id}", headers=BOB).status_code == 404
    assert api.get(f"/api/v1/jobs/{job_id}/stream", headers=BOB).status_code == 404
    assert api.get(f"/api/v1/jobs/{job_id}", headers=ALICE).status_code == 200


def test_a_verdict_records_which_reviewer_made_it(api):
    claim = submit(api, REVIEWER)
    api.post(f"/queue/{claim['id']}/verdict", headers=REVIEWER, json={"verdict": "approved", "notes": "ok"})
    logs = api.get(f"/claims/{claim['id']}", headers=REVIEWER).json()["audit_logs"]
    assert any("rita" in (l.get("reasoning") or "") for l in logs)


# ─── Photographs ────────────────────────────────────────────────────────────

def test_photographs_are_served_only_by_a_signed_url_from_the_claim(api):
    claim = submit(api, ALICE)
    path = claim["image_paths"].split(";")[0]
    detail = api.get(f"/claims/{claim['id']}", headers=ALICE).json()
    signed = detail["asset_urls"][path]

    assert api.get(f"/{signed}").status_code == 200                        # the claim's owner
    assert api.get(f"/{path}").status_code == 403                          # no signature
    tampered = signed[:-4] + ("0000" if not signed.endswith("0000") else "1111")
    assert api.get(f"/{tampered}").status_code == 403                      # forged signature
    other = path.replace(path.split("/")[1][:4], "ffff")
    assert api.get(f"/{other}?{signed.split('?')[1]}").status_code == 403  # another file


def test_an_expired_photograph_link_stops_working(api):
    claim = submit(api, ALICE)
    path = claim["image_paths"].split(";")[0]
    assert api.get("/" + sign_asset(path, ttl_seconds=-1)).status_code == 403


def test_photographs_are_not_cached_by_shared_caches(api):
    claim = submit(api, ALICE)
    path = claim["image_paths"].split(";")[0]
    response = api.get("/" + sign_asset(path))
    assert response.headers["cache-control"].startswith("private")


# ─── Sign-in ────────────────────────────────────────────────────────────────

def test_a_seeded_account_signs_in_and_reaches_its_role(api):
    tokens = api.post("/api/v1/auth/login", json={"username": "rita", "password": "correct-horse-battery"}).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert tokens["user"] == {"username": "rita", "role": "reviewer", "is_demo": False}
    assert api.get("/queue", headers=headers).status_code == 200
    assert api.get("/api/v1/auth/me", headers=headers).json() == {"username": "rita", "role": "reviewer"}


def test_every_sign_in_failure_looks_the_same(api):
    wrong = api.post("/api/v1/auth/login", json={"username": "rita", "password": "wrong-password-here"})
    unknown = api.post("/api/v1/auth/login", json={"username": "nobody", "password": "wrong-password-here"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid credentials."}


def test_repeated_failed_sign_ins_are_rate_limited(api):
    for _ in range(5):
        api.post("/api/v1/auth/login", json={"username": "rita", "password": "guess"})
    locked = api.post("/api/v1/auth/login", json={"username": "rita", "password": "correct-horse-battery"})
    assert locked.status_code == 429 and "Retry-After" in locked.headers


def test_passwords_are_stored_as_argon2id_never_plain(api):
    from platform_backend.db.models import User
    db = api.Testing()
    try:
        user = db.query(User).filter(User.username == "rita").first()
    finally:
        db.close()
    assert user.password_hash.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert "correct-horse-battery" not in user.password_hash


def test_seed_passwords_must_be_long():
    with pytest.raises(ValueError):
        auth.hash_password("short")


def test_a_short_signing_key_is_refused(monkeypatch):
    monkeypatch.setenv("AURELIX_JWT_SECRET", "too-short")
    with pytest.raises(RuntimeError):
        auth.jwt_secret()


# ─── Refresh tokens ─────────────────────────────────────────────────────────

def _login(api):
    return api.post("/api/v1/auth/login", json={"username": "rita", "password": "correct-horse-battery"}).json()


def test_refresh_rotates_the_token(api):
    first = _login(api)
    second = api.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}).json()
    assert second["refresh_token"] != first["refresh_token"]
    assert api.get("/queue", headers={"Authorization": f"Bearer {second['access_token']}"}).status_code == 200


def test_reusing_a_rotated_refresh_token_ends_the_whole_session(api):
    first = _login(api)
    second = api.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}).json()
    # Someone replays the old token: refused, and the legitimate new one dies with it.
    replay = api.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401
    assert api.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 401


def test_sign_out_revokes_the_refresh_token(api):
    tokens = _login(api)
    assert api.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}).status_code == 204
    assert api.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_refresh_tokens_are_stored_hashed(api):
    from platform_backend.db.models import RefreshToken
    tokens = _login(api)
    db = api.Testing()
    try:
        stored = [r.token_hash for r in db.query(RefreshToken).all()]
    finally:
        db.close()
    assert tokens["refresh_token"] not in stored and all(len(h) == 64 for h in stored)


# ─── Demo sign-in ───────────────────────────────────────────────────────────

def test_each_demo_visitor_gets_their_own_claimant(api):
    a = api.post("/api/v1/auth/demo", json={"role": "claimant"}).json()
    b = api.post("/api/v1/auth/demo", json={"role": "claimant"}).json()
    assert a["user"]["username"] != b["user"]["username"]
    assert a["user"]["is_demo"] is True and a["user"]["role"] == "claimant"
    claim = submit(api, {"Authorization": f"Bearer {a['access_token']}"})
    assert api.get(f"/claims/{claim['id']}", headers={"Authorization": f"Bearer {b['access_token']}"}).status_code == 404


def test_a_demo_account_cannot_be_signed_into_with_a_password(api):
    demo = api.post("/api/v1/auth/demo", json={"role": "reviewer"}).json()
    response = api.post("/api/v1/auth/login", json={"username": demo["user"]["username"], "password": ""})
    assert response.status_code in (401, 422)


def test_admin_is_not_a_demo_role(api):
    assert api.post("/api/v1/auth/demo", json={"role": "admin"}).status_code == 422


def test_a_too_short_signing_key_is_reported_and_its_500_reaches_the_browser(api, monkeypatch):
    # Production regression: a short AURELIX_JWT_SECRET made every sign-in crash while
    # /ready said "ok", and the bare 500 had no CORS header, so the page saw "Failed to fetch".
    monkeypatch.setenv("AURELIX_JWT_SECRET", "shorter-than-32-characters")
    ready = api.get("/ready").json()
    assert ready["ready"] is False and ready["checks"]["signing_key"] == "too_short"

    response = api.post("/api/v1/auth/demo", json={"role": "claimant"},
                        headers={"Origin": "https://www.aurelix.space"})
    assert response.status_code == 500
    assert response.json() == {"detail": "The server hit an unexpected error."}
    assert "access-control-allow-origin" in response.headers
    assert "shorter-than" not in response.text


def test_ready_reports_the_signing_key_state_without_revealing_it(api, monkeypatch):
    monkeypatch.delenv("AURELIX_JWT_SECRET", raising=False)
    assert api.get("/ready").json()["checks"]["signing_key"] == "generated"
    monkeypatch.setenv("AURELIX_JWT_SECRET", "k" * 40)
    body = api.get("/ready").json()
    assert body["checks"]["signing_key"] == "configured" and body["ready"] is True
    assert "k" * 40 not in str(body)


def test_demo_sign_in_can_be_switched_off(api, monkeypatch):
    monkeypatch.setenv("AURELIX_DEMO_LOGIN", "0")
    assert api.post("/api/v1/auth/demo", json={"role": "claimant"}).status_code == 404
    assert api.get("/api/v1/auth/config").json()["demo_login"] is False


# ─── Limits ─────────────────────────────────────────────────────────────────

def test_claim_submissions_are_rate_limited_per_account(api, monkeypatch):
    monkeypatch.setattr("platform_backend.services.rate_limit.rate_limits",
                        lambda: {"claim_submissions_per_hour": 1})
    submit(api, ALICE)
    response = api.post("/claims/submit-multimodal-stream", headers=ALICE,
                        data={"user_claim": "x", "claim_object": "car"},
                        files=[("files", ("a.jpg", jpeg(), "image/jpeg"))])
    assert response.status_code == 429
    submit(api, BOB)                                    # a different account is unaffected


def test_the_v1_route_can_no_longer_bypass_the_demo_cap(api, monkeypatch):
    from platform_backend.services import demo_guard
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PER_IP_DAILY", "1")
    demo_guard._spent.clear()
    form = {"user_claim": "The front bumper is dented.", "claim_object": "car"}
    first = api.post("/api/v1/claims", headers=ALICE, data=form, files=[("files", ("a.jpg", jpeg(), "image/jpeg"))])
    second = api.post("/api/v1/claims", headers=ALICE, data=form, files=[("files", ("a.jpg", jpeg(), "image/jpeg"))])
    demo_guard._spent.clear()
    assert first.status_code == 202 and second.status_code == 429


def test_a_rejected_upload_does_not_use_up_a_demo_analysis(api, monkeypatch):
    from platform_backend.services import demo_guard
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PER_IP_DAILY", "1")
    demo_guard._spent.clear()
    bad = api.post("/claims/submit-multimodal-stream", headers=ALICE,
                   data={"user_claim": "x", "claim_object": "car"},
                   files=[("files", ("a.txt", b"not an image", "image/jpeg"))])
    assert bad.status_code == 400
    submit(api, ALICE)                                   # the one allowed analysis is still there
    demo_guard._spent.clear()


# ─── Headers ────────────────────────────────────────────────────────────────

def test_security_headers_are_on_every_response(api):
    headers = api.get("/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in headers["content-security-policy"]
    assert headers["strict-transport-security"].startswith("max-age=")


def test_token_responses_are_never_cached(api):
    assert _login.__name__  # keep the helper referenced
    response = api.post("/api/v1/auth/login", json={"username": "rita", "password": "correct-horse-battery"})
    assert response.headers["cache-control"] == "no-store"
