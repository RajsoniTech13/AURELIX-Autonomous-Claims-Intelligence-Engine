"""
List prices for model calls, read from `config/pricing.yaml`.

Why a price table in a project that pays nothing. Every call AURELIX makes runs on a free
tier, so the *billed* cost is $0 and recording that would teach nothing. What is worth
knowing is what the same traffic would cost on a paid tier — that is the number that
decides whether a design survives contact with real volume. So telemetry records the
**list-price equivalent**, and the price file carries the date it was read, because a price
without a date is a guess.

An unknown model prices as `None`, not `0.0`. Zero would claim the call was free; `None`
says honestly that we do not know.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

_PRICING_PATH = Path(__file__).resolve().parents[2] / "config" / "pricing.yaml"


@lru_cache(maxsize=1)
def load_pricing(path: Optional[str] = None) -> Dict[str, Any]:
    p = Path(path) if path else _PRICING_PATH
    if not p.exists():
        return {"providers": {}}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {"providers": {}}


def price_of(provider: str, model: str) -> Optional[Dict[str, float]]:
    """`{"input": usd_per_1m, "output": usd_per_1m}`, or None when the model is not listed."""
    providers = load_pricing().get("providers", {})
    return (providers.get(provider, {}).get("models", {}) or {}).get(model)


def cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    """List-price cost of one call. None when the price is unknown."""
    price = price_of(provider, model)
    if price is None:
        return None
    total = (input_tokens * float(price["input"]) + output_tokens * float(price["output"])) / 1_000_000
    # Rounded to a billionth of a dollar. A millionth sounds fine until a single cheap call
    # costs $0.0000225 and rounding throws away half of it.
    return round(total, 9)


def as_of() -> Optional[str]:
    value = load_pricing().get("as_of")
    return str(value) if value is not None else None
