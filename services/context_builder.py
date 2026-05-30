"""Context-building stage interfaces.

The current app still owns most context construction. This adapter gives the
pipeline a typed seam so those blocks can move out of app.py incrementally.
"""

from __future__ import annotations

from services.signal_models import DecisionContext, SignalContext


class ContextBuilder:
    def build(self, signal: SignalContext) -> DecisionContext:
        return DecisionContext(signal=signal)
