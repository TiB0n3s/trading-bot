"""Shared feature registry types."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    dtype: str
    nullable: bool
    default: Any
    runtime_source: str
    offline_source: str
    point_in_time_cutoff: str
    staleness_rule: str
    semantic_version: str
    authority_eligibility: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
