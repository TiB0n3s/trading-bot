# Experiments

Experiment outputs should be reproducible and never overwrite prior results.

Suggested future layout:

```text
ml/experiments/
  YYYYMMDD_HHMMSS_experiment_name/
    config.json
    metrics.json
    feature_columns.txt
    dataset_summary.json
    notes.md
```

Each experiment should record:

- dataset query/date range,
- feature version,
- label target,
- train/test split,
- model type,
- metrics,
- calibration summary,
- known caveats.

No experiment result is automatically approved for runtime use.
