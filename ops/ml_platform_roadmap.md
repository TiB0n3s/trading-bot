# ML Platform Roadmap

This bot should become an ML research and decision-support platform before it
becomes an ML-driven trading system.

## Current stance

- Paper trading remains the runtime mode.
- Prediction outputs stay observe-only.
- No model should place orders, loosen risk controls, or override broker/order
  safeguards.
- Any future prediction influence must be paper-only, environment-controlled,
  logged, reversible, and limited to soft risk reduction until validated.

## Near-term foundation

1. Keep deterministic intelligence generation stable.
2. Monitor data collection with `dataset-health`, `feature-health`, and
   `feature-watch`.
3. Track rejected signals with `rejection-summary`.
4. Track order/fill integrity with `order-health`.
5. Preserve clean Tuesday session evidence before structural refactors.

## Research platform layers

1. Dataset layer: versioned feature snapshots, labels, trade outcomes, market
   context, and event context.
2. Evaluation layer: walk-forward validation, calibration, confusion matrices,
   and decision-policy replay.
3. Experiment layer: reproducible configs, dataset hashes, metrics, and reports.
4. Model registry: immutable model artifact path, training window, feature
   version, metrics, and approval status.
5. Serving layer: read-only status/report surfaces first; no live decision
   modification until enough paper evidence exists.

## Refactor sequence after Tuesday

1. Extract signal-processing logic from `app.py` behind tests.
2. Add typed context/result objects around the extracted seam.
3. Move restart-sensitive globals behind a durable state manager.
4. Consolidate SQL access into `db.py` after behavior is covered.
5. Add structured logging/report exports where reporting needs it.

## Promotion rule

A model can only move from observe-only to paper-trading influence after it has:

- enough feature and label coverage,
- matched-trade outcome coverage,
- stable out-of-sample validation,
- an explicit rollback plan,
- an environment flag defaulting off,
- operator-visible reports showing what it would have changed.
