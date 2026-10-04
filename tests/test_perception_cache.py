"""
The perception cache key must be the same in every process.

It was built with Python's builtin `hash()` over the claim text. CPython salts string hashes
per process (PYTHONHASHSEED), so the same claim produced a different key in every process:
a cached perception could only be found by the process that wrote it, and a shared Redis
cache could never hit. Run in two subprocesses with different hash seeds to prove it now
does not depend on the seed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_KEY_SCRIPT = """
import agent_core.agents.perception as p
from PIL import Image
seen = {}
def capture(**kw):
    seen['key'] = kw['cache_key']
    raise SystemExit(0)
p.call_gemini_multimodal = capture
claim = p.PreparedClaim(claim_id='C1', claim_object='car', claim_text='front bumper dented',
                        images=[Image.new('RGB', (8, 8), (90, 90, 90))], raw={})
try:
    p.run_batch_perception([claim])
except SystemExit:
    print(seen['key'])
"""


def test_the_perception_cache_key_is_identical_in_every_process():
    """
    Was built with the builtin `hash()`, which Python salts per process — so the same claim
    produced a different key in every process and a shared cache could never hit.
    """
    keys = set()
    for seed in ("1", "2"):
        out = subprocess.run(
            [sys.executable, "-c", _KEY_SCRIPT], cwd=REPO_ROOT, capture_output=True, text=True,
            env={"PYTHONHASHSEED": seed, "PATH": "", "PYTHONPATH": str(REPO_ROOT)},
            timeout=120,
        )
        assert out.returncode == 0, out.stderr
        keys.add(out.stdout.strip().splitlines()[-1])
    assert len(keys) == 1


