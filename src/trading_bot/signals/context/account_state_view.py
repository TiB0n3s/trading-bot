"""Immutable typed read-view over the legacy ``account_state`` dict.

This is the seed for retiring the mutable ``account_state`` god-dict that is
threaded through (and mutated in place by) the live signal path. ``AccountStateView``
wraps an existing ``account_state`` mapping **without copying or mutating it** and
exposes typed, read-only accessors.

Note: this is intentionally distinct from ``services.signal_models.DecisionContext``,
which is the *pipeline input DTO* (SignalContext + upstream observation sections).
``AccountStateView`` is a read-only lens over the separate, mutable ``account_state``
dict that downstream gates accumulate fields into.

Design rules (so adoption is provably behavior-preserving):

* Every accessor mirrors the exact semantics callers already rely on. The
  dominant idiom in the codebase is ``account_state.get("section") or {}`` for
  nested-dict sections, so the section accessors return ``{}`` for a missing or
  falsy value. Scalar accessors mirror plain ``account_state.get(key)`` and may
  return ``None``.
* The wrapper is frozen and holds a reference (not a copy) to the underlying
  mapping, so it stays consistent with the dict during the migration period.
* ``get`` / ``__contains__`` / ``raw`` provide an escape hatch for fields not yet
  modelled, so a consumer can migrate incrementally without losing access.

New *read-only* consumers should accept an ``AccountStateView``. Writers continue
to use the dict until later phases migrate the in-place mutation sites.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AccountStateView:
    raw: Mapping[str, Any]

    @classmethod
    def from_account_state(
        cls, account_state: Mapping[str, Any] | None
    ) -> "AccountStateView":
        """Wrap an account_state mapping (or ``None``) as a read-only view."""
        return cls(raw=account_state if account_state is not None else {})

    # -- escape hatch: behave like the underlying mapping for un-modelled keys --
    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def __contains__(self, key: object) -> bool:
        return key in self.raw

    # -- scalar accessors (mirror account_state.get(key)) --
    @property
    def symbol(self) -> str | None:
        return self.raw.get("symbol")

    @property
    def action(self) -> str | None:
        return self.raw.get("action")

    @property
    def max_position_size_pct_override(self) -> Any:
        return self.raw.get("max_position_size_pct_override")

    # -- section accessors (nested dicts; default {} to match the `... or {}` idiom) --
    @property
    def setup_quality(self) -> dict[str, Any]:
        return self.raw.get("setup_quality") or {}

    @property
    def buy_opportunity(self) -> dict[str, Any]:
        return self.raw.get("buy_opportunity") or {}

    @property
    def prediction_gate(self) -> dict[str, Any]:
        return self.raw.get("prediction_gate") or {}

    @property
    def session_momentum_gate(self) -> dict[str, Any]:
        return self.raw.get("session_momentum_gate") or {}

    @property
    def momentum(self) -> dict[str, Any]:
        return self.raw.get("momentum") or {}

    @property
    def tape(self) -> dict[str, Any]:
        return self.raw.get("tape") or {}

    @property
    def conviction_stack(self) -> dict[str, Any]:
        return self.raw.get("conviction_stack") or {}

    @property
    def market_alignment(self) -> dict[str, Any]:
        return self.raw.get("market_alignment") or {}

    @property
    def setup_observation(self) -> dict[str, Any]:
        return self.raw.get("setup_observation") or {}
