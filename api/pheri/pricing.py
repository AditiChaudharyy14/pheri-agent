"""Model prices in USD per 1M tokens: (input, cached input, output).

Meta Model API prices were checked on https://dev.meta.ai/docs/pricing-rate-limits
on 26 Oct 2026. Partner prices are deliberately conservative placeholders so the
spend cap triggers early rather than late; verify them on the partner's pricing page.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    cached_input: float
    output: float


META_PRICES: dict[str, Price] = {
    "muse-spark-1.3": Price(1.25, 0.15, 4.25),
    "muse-spark-1.2": Price(1.25, 0.15, 4.25),
    "muse-spark-1.1": Price(1.25, 0.15, 4.25),
    "muse-spark-1.3-contributor": Price(0.10, 0.002, 0.20),
    "muse-spark-1.2-contributor": Price(0.10, 0.002, 0.20),
    "muse-wonder-1.0": Price(4.00, 0.20, 20.00),
}

# Conservative stand-ins (open-weight inference is billed by the partner, not Meta).
PARTNER_PRICES: dict[str, Price] = {
    "baseten": Price(1.25, 1.25, 4.25),
    "modal": Price(1.25, 1.25, 4.25),
}

# Per-hour price for speech-to-text (metered in seconds).
TRANSCRIBE_USD_PER_HOUR = 0.18

# Modal GPU prices per second, checked on https://modal.com/pricing on 29 Oct 2026. Glimmer runs on our own
# container there, so a call costs the GPU's wall-clock time, not tokens.
MODAL_GPU_USD_PER_SECOND: dict[str, float] = {
    "L4": 0.000222,
    "A10": 0.000306,
    "L40S": 0.000542,
    "A100-40GB": 0.000583,
    "A100-80GB": 0.000694,
    "H100": 0.001097,
}


def gpu_usd(gpu: str, seconds: float) -> float:
    if gpu not in MODAL_GPU_USD_PER_SECOND:
        raise KeyError(f"No price on file for Modal GPU {gpu!r}; add it to pricing.py first.")
    return MODAL_GPU_USD_PER_SECOND[gpu] * max(0.0, seconds)


def price_for(provider: str, model: str) -> Price:
    if provider == "meta":
        if model not in META_PRICES:
            # Unknown Meta model: refuse rather than guess, so nothing is ever unpriced.
            raise KeyError(f"No price on file for Meta model {model!r}; add it to pricing.py first.")
        return META_PRICES[model]
    return PARTNER_PRICES[provider]


def cost_usd(price: Price, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    cached = min(cached_tokens, input_tokens)
    fresh = input_tokens - cached
    return (fresh * price.input + cached * price.cached_input + output_tokens * price.output) / 1_000_000
