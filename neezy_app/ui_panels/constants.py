"""Shared constants for the desktop window."""

RESEARCH_CONTROLS = [
    ("ml_history_candles", "Fetched history candles", 400, 50000, 100, "ML RESEARCH"),
    ("ml_epochs", "Training epochs", 1, 500, 1, "ML RESEARCH"),
    ("ml_horizon", "Prediction horizon (bars)", 1, 100, 1, "ML RESEARCH"),
    ("ml_deadband_atr", "ATR neutral deadband", 0.0, 5.0, 0.05, "ML RESEARCH"),
    ("ml_min_samples", "Minimum labelled examples", 60, 10000, 20, "ML RESEARCH"),
    ("ml_seed", "Reproducibility seed", 0, 2147483647, 1, "ML RESEARCH"),
    (
        "ml_probability",
        "Advisory probability threshold",
        0.51,
        0.99,
        0.01,
        "ML RESEARCH",
    ),
    (
        "ml_fetch_timeout",
        "Public API timeout (seconds)",
        2.0,
        120.0,
        1.0,
        "ML RESEARCH",
    ),
    ("insights_max_rows", "Insight table row limit", 5, 200, 5, "ML RESEARCH"),
    ("pair_lookback", "Lagged z-score window", 20, 1000, 10, "PAIR RESEARCH"),
    ("pair_min_overlap", "Minimum aligned candles", 100, 20000, 50, "PAIR RESEARCH"),
    ("pair_entry_z", "Entry z threshold", 0.5, 6.0, 0.1, "PAIR RESEARCH"),
    ("pair_exit_z", "Exit z threshold", 0.0, 3.0, 0.1, "PAIR RESEARCH"),
    ("pair_stop_z", "Stop z threshold", 1.0, 10.0, 0.1, "PAIR RESEARCH"),
    ("pair_cost_bps", "Turnover cost (bps)", 0.0, 100.0, 0.1, "PAIR RESEARCH"),
    ("pair_max_holding", "Maximum holding bars", 1, 2000, 1, "PAIR RESEARCH"),
    (
        "pair_min_correlation",
        "Minimum train |correlation|",
        0.0,
        1.0,
        0.05,
        "PAIR RESEARCH",
    ),
]


NAV = [
    "CHAT",
    "SYMBOLS",
    "CHART",
    "SIGNALS",
    "INSIGHTS",
    "TOOLS",
    "ALERTS",
    "HISTORY",
    "SETTINGS",
]
