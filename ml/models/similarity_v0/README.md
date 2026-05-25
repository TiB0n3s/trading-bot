# similarity_v0

Versioned placeholder for the first similarity-style observe-only model.

Status: `research`

Runtime effect: `none`

This directory intentionally contains metadata only. It does not contain a
trained artifact, does not load in `app.py`, and must not influence orders,
broker calls, position sizing, or hard risk controls.

Before this model can move beyond research:

- dataset manifests must identify source DB, query version, label version,
  feature version, override hashes, and policy-artifact hashes;
- retraining readiness must clear its blockers;
- replay decisions must compare against current no-ML bot behavior;
- walk-forward validation, calibration, and rollback evidence must exist;
- an operator must explicitly promote it through review.
