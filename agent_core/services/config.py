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


def retry_config() -> Dict[str, Any]:
    return load_config()["retry"]


def circuit_breaker_config() -> Dict[str, Any]:
    return load_config()["circuit_breaker"]


def evidence_config() -> Dict[str, Any]:
    cfg = dict(load_config()["evidence"])
    # Env override so a CLI flag can turn text-only inference on for one run without
    # editing the file (and without it silently persisting).
    override = os.getenv("AURELIX_ALLOW_TEXT_ONLY")
    if override is not None:
        cfg["allow_text_only_inference"] = override.strip().lower() in ("1", "true", "yes")
    return cfg
