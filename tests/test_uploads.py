"""
The upload edge: caps, content sniffing, and the promise that evidence can be looked at.

Two classes of regression are guarded here.

**The one that was a bug.** `image_paths` recorded `uploads/<the client's filename>` for an
image that was never written anywhere. Every `<img>` on the review screen 404'd, so the
single piece of evidence a verdict rests on was the one thing a reviewer could not see. The
tests below assert the recorded path resolves to actual bytes over HTTP.

**The ones that were an open door.** No size cap, no count cap, and a filename taken from
the client. All three are cheap to exploit and cheap to close.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.test_backend_pipeline import GeminiSpy


def _png(size=(64, 64), colour=(180, 40, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """
    A client on a throwaway database, with perception stubbed.

    The spy matters: these tests are about the HTTP edge, and a real model call would make
    them cost quota, take fifteen seconds, and fail for reasons that have nothing to do
    with uploads.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from platform_backend.db import session as session_module
    from platform_backend.db.models import Base

    engine = create_engine(
        f"sqlite:///{tmp_path / 'uploads_test.db'}", connect_args={"check_same_thread": False},
    )
    Testing = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(session_module, "engine", engine)
    monkeypatch.setattr(session_module, "SessionLocal", Testing)

    from platform_backend.services import jobs as job_service
    monkeypatch.setattr(job_service, "SessionLocal", Testing)
    monkeypatch.setattr("agent_core.agents.perception.call_gemini_multimodal", GeminiSpy())

    from platform_backend.api import v1
    from platform_backend.main import app

    def _override():
        db = Testing()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[session_module.get_db] = _override
    monkeypatch.setattr(v1.job_service, "SessionLocal", Testing)

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    job_service.shutdown(wait=True)


def _submit(client, files, **form):
    payload = {
        "user_id": "user_002",
        "user_claim": "Rear bumper dented while reversing.",
        "claim_object": "car",
        **form,
    }
    return client.post("/claims/submit-multimodal", data=payload, files=files)


# ─── The evidence is actually there ─────────────────────────────────────────

def test_the_stored_path_resolves_to_the_bytes_that_were_uploaded(client):
    """
    The whole point. Submit an image, take the path off the claim, fetch it back.

    This is what the review screen does, and until now it got a 404 every time.
    """
    raw = _png()
    res = _submit(client, [("files", ("evidence.png", raw, "image/png"))])
    assert res.status_code == 200, res.text

    paths = res.json()["image_paths"].split(";")
    assert len(paths) == 1
    assert paths[0].startswith("uploads/")

    fetched = client.get(f"/{paths[0]}")
    assert fetched.status_code == 200
    assert fetched.content == raw


def test_the_client_filename_never_reaches_the_filesystem(client):
    """
    A caller who controls the stored name controls the path. `../../` is the oldest trick
    there is, and the previous code wrote the client's filename straight into `image_paths`.
    """
    hostile = "../../../etc/passwd.png"
    res = _submit(client, [("files", (hostile, _png(), "image/png"))])
    assert res.status_code == 200, res.text

    stored = res.json()["image_paths"]
    assert ".." not in stored
    assert "passwd" not in stored
    assert stored.startswith("uploads/")


def test_several_images_are_all_persisted_in_order(client):
    files = [
        ("files", (f"shot_{i}.png", _png(colour=(i * 40, 20, 20)), "image/png"))
        for i in range(3)
    ]
    res = _submit(client, files)
    assert res.status_code == 200, res.text

    paths = res.json()["image_paths"].split(";")
    assert len(paths) == 3
    assert len(set(paths)) == 3, "each upload must get its own name"
    for p in paths:
        assert client.get(f"/{p}").status_code == 200


def test_a_claim_with_no_files_records_none_rather_than_an_empty_path(client):
    res = _submit(client, [])
    assert res.status_code == 200, res.text
    assert res.json()["image_paths"] == "none"


# ─── The caps ───────────────────────────────────────────────────────────────

def test_too_many_files_is_rejected_before_anything_is_analysed(client, monkeypatch):
    from platform_backend.config import settings
    monkeypatch.setattr(settings, "MAX_UPLOAD_FILES", 2)

    files = [("files", (f"s{i}.png", _png(), "image/png")) for i in range(3)]
    res = _submit(client, files)
    assert res.status_code == 413
    assert "at most 2" in res.json()["detail"].lower()


def test_an_oversized_image_is_rejected(client, monkeypatch):
    from platform_backend.config import settings
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 1024)

    res = _submit(client, [("files", ("big.png", _png(size=(512, 512)), "image/png"))])
    assert res.status_code == 413
    assert "limit" in res.json()["detail"].lower()


def test_a_non_image_is_a_400_not_a_500(client):
    """
    A client error must read as one. The old path let Pillow's exception escape into a
    generic handler, and a user who attached a PDF got "Agent orchestrator failed".
    """
    res = _submit(client, [("files", ("notes.txt", b"this is not an image", "image/png"))])
    assert res.status_code == 400
    assert "readable image" in res.json()["detail"]


def test_an_empty_file_is_rejected(client):
    res = _submit(client, [("files", ("empty.png", b"", "image/png"))])
    assert res.status_code == 400


def test_the_declared_content_type_is_not_trusted(client):
    """
    Content-Type is a claim by the client, not a fact. The stored extension comes from what
    Pillow decoded, so a PNG announced as a JPEG is still stored — and served — as a PNG.
    """
    res = _submit(client, [("files", ("liar.jpg", _png(), "image/jpeg"))])
    assert res.status_code == 200, res.text

    stored = res.json()["image_paths"]
    assert stored.endswith(".png"), f"stored under the client's claim instead: {stored}"
    assert client.get(f"/{stored}").headers["content-type"] == "image/png"


# ─── The async contract shares the same edge ────────────────────────────────

def test_the_v1_route_enforces_the_same_caps(client, monkeypatch):
    """
    Two submission contracts exist during the migration. A cap enforced on one of them is
    not a cap — it is a detour sign.
    """
    from platform_backend.config import settings
    monkeypatch.setattr(settings, "MAX_UPLOAD_FILES", 1)

    files = [("files", (f"s{i}.png", _png(), "image/png")) for i in range(2)]
    res = client.post(
        "/api/v1/claims",
        data={"user_id": "user_002", "user_claim": "Dented.", "claim_object": "car"},
        files=files,
    )
    assert res.status_code == 413


def test_the_v1_route_persists_evidence_too(client):
    res = client.post(
        "/api/v1/claims",
        data={"user_id": "user_002", "user_claim": "Dented.", "claim_object": "car"},
        files=[("files", ("e.png", _png(), "image/png"))],
    )
    assert res.status_code == 202, res.text

    from platform_backend.db.models import Job
    from platform_backend.db.session import SessionLocal
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == res.json()["job_id"]).first()
        stored = job.submitted_payload["image_paths"]
    finally:
        db.close()

    assert stored.startswith("uploads/")
    assert client.get(f"/{stored}").status_code == 200
