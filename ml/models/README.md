# Model Registry Conventions

Future model artifacts should be registered before any runtime or reporting
surface consumes them.

Current expected local artifact paths:

- `similarity_v0/`: metadata-only research placeholder.
- `supervised_entry_v1/model.joblib`: optional sklearn supervised entry
  artifact from `train_supervised_predictions.py`.
- `supervised_entry_v1/model.metadata.json`: training metadata, feature/target
  context, and dependency/runtime details for the supervised artifact.
- `regime_hmm_v1/model.joblib`: optional hmmlearn GaussianHMM regime artifact
  from `train_regime_model.py`.
- `regime_hmm_v1/model.metadata.json`: training metadata and regime-feature
  context for the HMM artifact.

The supervised and HMM paths can be created locally for smoke tests and offline
review. They are not live runtime dependencies and do not have authority to
approve trades, block trades, increase sizing, submit orders, or override risk
controls.

Suggested fields:

```json
{
  "model_id": "example",
  "status": "research",
  "artifact_path": "ml/models/example/model.pkl",
  "feature_version": "v1",
  "target": "ret_fwd_15m_positive",
  "training_window": "YYYY-MM-DD..YYYY-MM-DD",
  "validation_window": "YYYY-MM-DD..YYYY-MM-DD",
  "metrics_path": "ml/experiments/.../metrics.json",
  "created_at": "ISO-8601",
  "last_trained_date": "YYYY-MM-DD",
  "retraining_policy": "manual_reviewed_batch_retraining",
  "next_retraining_review_after": "20 trading sessions or drift/performance alert",
  "training_data_end_date": "YYYY-MM-DD",
  "notes": "observe-only"
}
```

Every model card must also state:

- This model does not place orders.
- This model does not override hard risk controls.
- This model does not increase position size unless explicitly promoted later.
- This model is invalid outside listed symbols, regimes, and date ranges.
- This model must abstain on stale or missing features.
- This model must demote when rolling performance, calibration, drift, or fill
  quality breaches its status thresholds.

Model output should include abstention:

```json
{
  "prediction": "avoid_entry",
  "confidence": 0.61,
  "abstain": false,
  "abstain_reason": null
}
```

Allowed statuses:

- `research`
- `observe_only`
- `warn_only`
- `paper_gate`
- `live_candidate`
- `shadow`
- `paper_soft`
- `retired`

Anything beyond `research` requires explicit operator approval and code review.
Promotion requires a matching demotion path and rollback plan.
Automatic retraining is disabled by default; after-close learning should create
readiness evidence for manual review first.

Before promoting either `supervised_entry_v1` or `regime_hmm_v1`, require at
minimum a model card, dataset manifest, point-in-time feature audit,
out-of-sample validation, calibration/drift review, replay decision-delta
report, default-off runtime flag, explicit demotion trigger, and rollback
procedure.

## Policy Artifacts

Some runtime-influencing artifacts are not predictive models but still need
registry discipline:

- `strategy_memory.json`
- `portfolio_replacement_memory.json`
- `excursion_memory.json`
- `missed_opportunity_memory.json`
- `policy_backtest_summary.json`

Longer term, register these as `policy_artifact` entries with hash, source
script, generated timestamp, rollback target, and runtime effect.
`POLICY_ARTIFACTS_ENABLED=false` is the live kill switch for learned policy
artifact influence.

Use the registry CLI for local metadata:

```bash
python3 -m ml_platform.cli list-models
python3 -m ml_platform.cli model-card-template --model-id similarity_v0
```
