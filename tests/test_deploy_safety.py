"""
Things that are only wrong once the product is deployed.

Each of these passes locally by accident and fails a real claimant in production,
so they are asserted rather than remembered.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_the_deployed_build_does_not_seed_the_duplicate_detector_with_test_data():
    """
    `build_index` fingerprints whatever claims file it is given, and the default is
    the **synthetic benchmark**. Running it unguarded during the Render build loads
    46 procedurally generated test renders into the live duplicate index.

    The failure mode is specific and bad: a real claimant's photograph matches a
    test render, `R030_duplicate_image_reuse` fires, and the justification handed
    to that claimant names claim `SYN-014` — a claim that exists in no production
    database and that no reviewer can open.

    The detector must start empty and learn from real submissions.
    """
    render = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
    build_lines = [ln for ln in render.splitlines() if "build_index" in ln and not ln.strip().startswith("#")]
    assert build_lines, "render.yaml no longer builds the index"
    for line in build_lines:
        assert "--no-image-index" in line, (
            "the deployed build must pass --no-image-index, or synthetic benchmark "
            "images seed the production duplicate detector"
        )


def test_the_no_image_index_flag_exists():
    """The guard above is worthless if the flag it depends on is renamed away."""
    src = (REPO_ROOT / "agent_core/tools/build_index.py").read_text(encoding="utf-8")
    assert "--no-image-index" in src


def test_no_api_key_is_committed():
    """
    A key in the tree is a key on GitHub. `.env` is gitignored; `.env.example`
    must stay a template.
    """
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert not re.search(r"AIza[0-9A-Za-z_\-]{10,}", example)
    assert re.search(r"^GEMINI_API_KEY=\s*$", example, re.MULTILINE), \
        "GEMINI_API_KEY in .env.example must be blank"


def test_env_is_not_tracked():
    import subprocess
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".env"],
        cwd=REPO_ROOT, capture_output=True,
    ).returncode == 0
    assert not tracked, ".env must never be committed"


def test_render_health_check_path_is_served():
    """
    Render restarts a container whose health check 404s. The path in render.yaml
    must be a route the app actually defines.
    """
    render = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
    match = re.search(r"healthCheckPath:\s*(\S+)", render)
    assert match, "render.yaml declares no healthCheckPath"
    path = match.group(1)

    from platform_backend.main import app
    routes = {getattr(r, "path", None) for r in app.routes}
    assert path in routes, f"{path} is not a route this app serves"


def test_the_deployed_start_command_targets_the_real_app():
    render = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "platform_backend.main:app" in render


@pytest.mark.parametrize("name", ["GEMINI_API_KEY", "CORS_ORIGINS"])
def test_secrets_are_prompted_not_committed(name):
    """Both must be `sync: false` so Render asks rather than reading a literal."""
    render = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
    block = render.split(f"key: {name}", 1)
    assert len(block) == 2, f"{name} is not declared in render.yaml"
    assert "sync: false" in block[1][:120], f"{name} must be sync: false"


def test_document_limits_are_documented_for_operators():
    """A cap nobody can find is a cap nobody can raise when a claimant hits it."""
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "MAX_DOCUMENT_FILES" in example
    assert "MAX_DOCUMENT_BYTES" in example
