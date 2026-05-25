# Model Registry Conventions

Future model artifacts should be registered before any runtime or reporting
surface consumes them.

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

Use the registry CLI for local metadata:

```bash
python3 -m ml_platform.cli list-models
python3 -m ml_platform.cli model-card-template --model-id similarity_v0
```
