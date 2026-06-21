"""Per-signal evaluation context shared by every gate in the live signal path.

``GateContext`` and ``DecisionTrace`` are the typed successors to the mutable
``account_state`` god-dict and the ad-hoc per-signal locals threaded through
``processor.process()`` today.  They are introduced additively: in this phase
the processor builds them alongside the existing locals with no gate-signature
changes.  Later phases route writes through ``DecisionTrace`` (Phase 4) and
migrate gate calls to ``evaluate(ctx)`` (Phase 6).

See ``ops/account_state_decomposition_plan.md`` for the full migration plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trading_bot.signals.context.account_state_view import AccountStateView


@dataclass
class DecisionTrace:
    """Append-only decision-output accumulator.

    Replaces the pattern where any gate writes any key onto the shared
    ``account_state`` dict.  During migration, the processor mirrors each write
    here *and* onto the dict so un-migrated readers remain unaffected.
    Last write wins within a single signal lifecycle.
    """

    _outputs: dict[str, Any] = field(default_factory=dict, repr=False)

    def record(self, name: str, payload: Any) -> None:
        self._outputs[name] = payload

    def as_dict(self) -> dict[str, Any]:
        """Return a snapshot of all recorded outputs."""
        return dict(self._outputs)

    def __len__(self) -> int:
        return len(self._outputs)

    def __contains__(self, name: object) -> bool:
        return name in self._outputs


@dataclass
class GateContext:
    """Per-signal evaluation context shared by every gate.

    Fields
    ------
    intelligence:
        Immutable read-view over the live ``account_state`` dict (zero-copy).
        Writers not yet migrated keep mutating the underlying dict; reads through
        ``intelligence`` stay consistent because ``intelligence.raw IS account_state``.
    trace:
        Append-only decision-output accumulator.  Empty in Phase 3; populated
        gate-by-gate as Phase 4 routes writes through ``DecisionTrace``.

    The remaining fields correspond to the interleaved per-signal locals that
    ``process()`` threads between gate calls today.  They start as ``None``/``{}``
    defaults and are filled in as each local is populated during the signal lifecycle.
    """

    intelligence: "AccountStateView"
    trace: DecisionTrace
    symbol: str
    action: str
    price: float | None
    dedupe_key: str | None
    current_et: Any | None = None
    existing_position: dict[str, Any] | None = None
    macro_risk: dict[str, Any] = field(default_factory=dict)
    bias_entry: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    rejection_adapter: Any | None = None
