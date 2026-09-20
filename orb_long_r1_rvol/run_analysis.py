#!/usr/bin/env python3
"""CLI entry point: run the Section 9 validation pipeline over a CSV exported
from TradingView ("Export chart data" with the indicator's data-window plots
enabled).

Example:
    python run_analysis.py --csv path/to/export.csv --risk-per-trade 200
"""

from __future__ import annotations

from analysis.cli import main

if __name__ == "__main__":
    main()
