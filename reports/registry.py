"""Registry for operator report commands."""

from __future__ import annotations

from collections.abc import Mapping

from reports.command import (
    FunctionReportCommand,
    ReportCommand,
    ReportRequest,
    ScriptReportCommand,
)


def _date_flag(request: ReportRequest) -> list[str]:
    return ["--date", request.target_date]


def _date_positional(request: ReportRequest) -> list[str]:
    return [request.target_date]


def _no_date(request: ReportRequest) -> list[str]:
    return []


def _filter_args(request: ReportRequest) -> list[str]:
    args = _date_flag(request)
    if request.options.get("week"):
        args.append("--week")
    return args


def _strong_day_args(request: ReportRequest) -> list[str]:
    args = _date_flag(request)
    if request.options.get("write_db"):
        args.append("--write-db")
    return args


def _run_auto_buy_outcomes(request: ReportRequest) -> bool:
    import auto_buy_outcome_report as report

    db_path = request.options.get("db_path") or report.DB_PATH
    rows = report.candidate_outcomes(request.target_date, db_path)
    tv_summary = report.tradingview_signal_summary(request.target_date, db_path)
    return report.render(request.target_date, rows, tv_summary)


def _run_prediction_validation(request: ReportRequest) -> bool:
    import prediction_validation_report as report

    target_date = request.target_date
    print("=" * 72)
    print(f"Prediction Validation - {target_date}")
    print("=" * 72)
    print("Read-only: predictions remain observe-only and do not affect trading.")

    payload = report._service().payload(target_date)
    predictions = payload.predictions
    signals = payload.signals
    matched = payload.matched
    strong_days = payload.strong_days
    agreement_rows = payload.agreement_rows

    print()
    print(f"Predictions          : {len(predictions)}")
    print(f"Symbols with signals : {len(signals)}")
    print(f"Symbols with matches : {len(matched)}")
    print(f"Strong-day rows      : {len(strong_days)}")

    if not predictions:
        print("[FAIL] No daily_symbol_predictions rows found for this date.")
        return False

    if not signals and not matched:
        print("[OK] Pre-session readiness mode: predictions exist; outcomes are not populated yet.")

    report.render_distribution(predictions)
    report.render_top_bottom(predictions)
    report.render_outcome_buckets(predictions, signals, matched)
    report.render_strong_day_buckets(predictions, strong_days)
    report.render_gate_ml_agreement(agreement_rows)

    print()
    print("[OK] prediction validation report completed")
    return True


REPORT_COMMANDS: Mapping[str, ReportCommand] = {
    "alignment": ScriptReportCommand("alignment", "market_alignment_report", _no_date),
    "adaptive": ScriptReportCommand("adaptive", "adaptive_confirmation_report", _no_date),
    "adaptive_impact": ScriptReportCommand(
        "adaptive_impact", "adaptive_impact_report", _date_positional
    ),
    "strategy_intelligence": ScriptReportCommand(
        "strategy_intelligence", "strategy_intelligence_report", _date_positional
    ),
    "blocked": ScriptReportCommand("blocked", "blocked_signal_outcome_report", _date_flag),
    "filters": ScriptReportCommand("filters", "filter_report", _filter_args),
    "drawdown": ScriptReportCommand("drawdown", "drawdown_report", _date_positional),
    "event-attribution": ScriptReportCommand(
        "event-attribution", "event_attribution_report", _date_flag
    ),
    "intelligence": ScriptReportCommand("intelligence", "intelligence_context_report", _date_flag),
    "context": ScriptReportCommand("context", "context_trade_join_report", _date_flag),
    "learning": ScriptReportCommand("learning", "intelligence_learning_report", _date_flag),
    "predictions": ScriptReportCommand("predictions", "intelligence_prediction_report", _date_flag),
    "signal-lessons": ScriptReportCommand(
        "signal-lessons", "signal_timing_lesson_report", _date_flag
    ),
    "trends": ScriptReportCommand("trends", "trend_context_report", _date_flag),
    "prediction-validation": FunctionReportCommand(
        "prediction-validation", _run_prediction_validation
    ),
    "auto-buy-outcomes": FunctionReportCommand("auto-buy-outcomes", _run_auto_buy_outcomes),
    "strong-days": ScriptReportCommand(
        "strong-days", "strong_day_participation_report", _strong_day_args
    ),
    "decision-trace": ScriptReportCommand("decision-trace", "decision_trace_report", _date_flag),
    "gate-impact": ScriptReportCommand("gate-impact", "gate_impact_report", _date_flag),
    "counterfactual-replay": ScriptReportCommand(
        "counterfactual-replay",
        "counterfactual_replay_report",
        _date_flag,
    ),
    "model-authority": ScriptReportCommand("model-authority", "model_authority_report", _date_flag),
}


def get_report_commands() -> Mapping[str, ReportCommand]:
    return REPORT_COMMANDS


def run_report(command_name: str, target_date: str, **options: object) -> bool:
    command = REPORT_COMMANDS[command_name]
    return command.run(ReportRequest(target_date=target_date, options=options))
