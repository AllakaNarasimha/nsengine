"""
NS Engine - Trading Strategy Backtesting Framework
Main entry point for running backtests with different strategies.
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import AppConfig
from core.runner import StrategyRunner


def main():
    """Main entry point for backtesting."""
    
    # Calculate database directory (relative to ns_engine folder)
    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', "csv"))
    
    # Configure backtesting parameters
    config = AppConfig(
        # Database and symbol configuration
        db_dir=parent_dir,
        symbol='NIFTY',
        underlying='NIFTY 50',
        segment='INDICES',
        instrument_type='EQ',
        
        # Strategy configuration
        strategy_type='orb',  # Options: 'ema', 'rsi', 'scalper', 'orb'
        strategy_params={
            'stop_loss_pct': 0.1,
            'trailing_stop_pct': 0.2,
            'pl_percent': 0.5
        },
        
        # Output files
        trades_csv='nifty_orb.csv',
        export_csv='nifty_orb_prices_5.csv',
        
        # Data settings
        use_multi_db=True,
        preprocessing_days=3,
        
        # Backtest date range
        start_date='2025-09-01',
        end_date='2025-09-05',
        
        # Trading session hours
        start_time="09:30",
        end_time="15:00",
        
        # Position sizing
        pl_percent=0.5,
        
        # Candle settings
        candle_freq='5min',
        
        # Chart library: 'mpl' for Matplotlib, 'tv' for TradingView
        chart_library='tv',
        
        # TradingView chart settings
        tv_autoupdate=True,
        tv_update_every=1,
        tv_refresh_seconds=3,
        tv_auto_open=True,
        tv_pl_multiline=True,
        tv_pl_color_scale=True,
        tv_pl_padding=1,
        show_pl_line=True,
        pl_line_hover_only=True,
        tv_pl_separate_panel=True
    )
    
    # Run the backtest
    runner = StrategyRunner(config)
    runner.run()


if __name__ == "__main__":
    main()
