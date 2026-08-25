"""Research backtests built from the Trading Core event ledger."""

from research.backtest.setup03 import (
    ExecutionStatus,
    Setup03ResearchReport,
    Setup03ParameterArtifacts,
    Setup03TradeOutcome,
    decision_gate_diagnostic_rows,
    decision_gate_summary_row,
    parameter_sensitivity_artifacts,
    parameter_sensitivity_rows,
    research_funnel_counts,
    research_trade_outcomes,
)

__all__ = [
    "ExecutionStatus",
    "Setup03ResearchReport",
    "Setup03ParameterArtifacts",
    "Setup03TradeOutcome",
    "decision_gate_diagnostic_rows",
    "decision_gate_summary_row",
    "parameter_sensitivity_artifacts",
    "parameter_sensitivity_rows",
    "research_funnel_counts",
    "research_trade_outcomes",
]
