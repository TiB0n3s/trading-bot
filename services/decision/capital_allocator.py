"""Capital allocation helpers for canonical decision sizing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CapitalAllocation:
    requested_size_pct: float
    allocated_size_pct: float
    max_risk_pct: float
    confidence_multiplier: float
    stress_multiplier: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CapitalAllocator:
    """Bound requested size by confidence and stress without approving trades."""

    def __init__(self, *, max_risk_pct: float = 2.0):
        self.max_risk_pct = max(0.0, float(max_risk_pct))

    @staticmethod
    def _confidence_multiplier(confidence: str | None) -> float:
        value = str(confidence or "").strip().lower()
        if value in {"high", "strong", "auto_buy_manager"}:
            return 1.0
        if value == "medium":
            return 0.75
        if value == "low":
            return 0.35
        return 0.5

    @staticmethod
    def _stress_multiplier(stress: str | None) -> float:
        value = str(stress or "").strip().lower()
        if value in {"toxic", "extreme", "block"}:
            return 0.0
        if value in {"high", "elevated", "caution"}:
            return 0.5
        return 1.0

    def allocate(
        self,
        *,
        requested_size_pct: float | int | None,
        confidence: str | None,
        liquidity_stress: str | None = None,
    ) -> CapitalAllocation:
        try:
            requested = float(requested_size_pct or 0.0)
        except Exception:
            requested = 0.0
        confidence_multiplier = self._confidence_multiplier(confidence)
        stress_multiplier = self._stress_multiplier(liquidity_stress)
        capped = min(requested, self.max_risk_pct)
        allocated = max(0.0, capped * confidence_multiplier * stress_multiplier)
        return CapitalAllocation(
            requested_size_pct=round(requested, 6),
            allocated_size_pct=round(allocated, 6),
            max_risk_pct=self.max_risk_pct,
            confidence_multiplier=confidence_multiplier,
            stress_multiplier=stress_multiplier,
            reason=(
                "capital allocation applied: "
                f"requested={requested:.4f}; cap={self.max_risk_pct:.4f}; "
                f"confidence_multiplier={confidence_multiplier:.2f}; "
                f"stress_multiplier={stress_multiplier:.2f}"
            ),
        )
