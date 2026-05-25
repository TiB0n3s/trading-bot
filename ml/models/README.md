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
  "notes": "observe-only"
}
```

Allowed statuses:

- `research`
- `shadow`
- `paper_soft`
- `retired`

Anything beyond `research` requires explicit operator approval and code review.

Use the registry CLI for local metadata:

```bash
python3 -m ml_platform.cli list-models
```
