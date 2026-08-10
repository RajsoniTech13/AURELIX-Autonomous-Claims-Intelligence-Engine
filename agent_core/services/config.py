"""
Config loader for AURELIX.

Single source of truth for quota, retry, and evidence-policy numbers. Loaded once at
import; no magic numbers in the call path.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "limits.yaml"


@lru_cache(maxsize=1)
def load_config(path: str | None = None) -> Dict[str, Any]:
    """Load limits.yaml. `AURELIX_CONFIG` overrides the default location."""
    cfg_path = Path(path or os.getenv("AURELIX_CONFIG") or _DEFAULT_CONFIG_PATH)
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"AURELIX config not found at {cfg_path}. "
            f"Set AURELIX_CONFIG to point at a limits.yaml."
        )
    with cfg_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def active_tier() -> str:
    """`AURELIX_TIER` env var wins over the file, so deploys can switch without editing config."""
    return os.getenv("AURELIX_TIER") or load_config().get("active_tier", "free")


def model_limits(model: str) -> Dict[str, int]:
    """Per-model RPM/TPM/RPD for the active tier, falling back to the tier default."""
    tiers = load_config()["tiers"]
    tier = tiers.get(active_tier()) or tiers["free"]
    return tier["models"].get(model) or tier["default"]


def model_config() -> Dict[str, Any]:
    """Primary model plus the fallback ladder. Each rung has its own free daily budget."""
    return load_config()["models"]


def batching_config() -> Dict[str, Any]:
    return load_config()["batching"]


def retry_config() -> Dict[str, Any]:
    return load_config()["retry"]


def circuit_breaker_config() -> Dict[str, Any]:
    return load_config()["circuit_breaker"]


# `evidence_config()` and the `evidence:` block it read are gone.
#
# They controlled `allow_text_only_inference`: an opt-in that let the old graph analyse a
# claim from its text when no image loaded. The batched pipeline never asks. A claim with
# no usable image short-circuits at preflight to not_enough_information, because a finding
# invented from a filename is a guess wearing the costume of an observation — which is
# precisely how the pre-Phase-0.5 pipeline produced 44 rows of hallucinated damage.
#
# The option was left in place through Phase 2/4 and read by nobody. A configuration knob
# that silently does nothing is worse than no knob, so it is removed rather than preserved.
