# Decision V1 Legacy Surfaces

Legacy status: transitional compatibility, not removal-ready.

These files are still imported by the deployed runtime, tests, cron/operator
commands, or app compatibility layer. They must not be deleted until their
callers use the canonical decision package:

```text
services/decision/
  engine.py
  state.py
  trace.py
  authority.py
  gates/
  adapters/
```

## Runtime Authority Rule

No new approval, sizing, blocking, or order-submission authority should be added
to the legacy files listed in `manifest.json`. New authority belongs in
`services/decision/` or a bounded package that is called through
`DecisionEngine`, `AuthorityMatrix`, `GateResult`, and `DecisionTrace`.

## Archive Buckets

- `thin_adapter`: keep temporarily, but reduce to import/delegation wrappers.
- `archive_after_clean_cycles`: keep until one to two clean paper cycles prove
  the replacement path.
- `manual_tool`: keep only as an operator/debug tool, not as a runtime authority
  surface.

## Removal Condition

A listed file can move from the live tree into `legacy_architecture/decision_v1`
only when:

- no live/runtime caller imports it,
- cron/systemd/operator docs reference the replacement command,
- `run_safety_checks.py` passes,
- a paper smoke test covers the replacement path,
- the compatibility manifest is updated.
