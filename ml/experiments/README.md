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

The scaffold command creates ignored local experiment directories:

```bash
python3 -m ml_platform.cli create-experiment setup_baseline --dataset-start 2026-05-20 --dataset-end 2026-05-26
```
