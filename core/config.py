"""
Configuration management module for NS Engine backtesting framework.
Handles application configuration with sensible defaults.
"""


class AppConfig:
    """Application configuration class with all backtesting parameters."""
    
    def __init__(self, **kwargs):
        """
        Initialize AppConfig with provided parameters and defaults.
        
        Args:
            **kwargs: Configuration parameters to override defaults
        """
        default_cfg = dict(
            # Core settings
            db_dir=None,
            symbol=None,
            underlying=None,
            segment=None,
            instrument_type=None,
            
            # Strategy settings
            strategy_type='ema',
            strategy_params=None,
            
            # Data settings
            data_mode='historical',
            initialization_periods=50,
            live=False,
            use_multi_db=False,
            preprocessing_days=3,
            
            # Date/Time settings
            start_date=None,
            end_date=None,
            start_time="09:15",
            end_time="15:00",
            
            # Output settings
            trades_csv='trading_journal.csv',
            export_csv=None,
            
            # Trading parameters
            expiry_index=0,
            pl_percent=0.5,
            
            # Candle settings
            candle_freq='1min',
            
            # Chart settings
            chart_library='mpl',  # 'mpl' or 'tv'
            
            # TradingView specific settings
            tv_autoupdate=False,
            tv_update_every=5,
            tv_refresh_seconds=0,
            tv_auto_open=False,
            tv_pl_padding=2,
            tv_pl_multiline=False,
            tv_pl_color_scale=True,
            tv_pl_separate_panel=False,
            tv_volume_ratio=0.25,
            
            # Display settings
            show_pl_line=True,
            pl_line_hover_only=False,
            
            # Volume settings
            volume_mode='tick_count',  # tick_count | price_range | abs_return | real
        )
        
        for k, v in default_cfg.items():
            setattr(self, k, kwargs.get(k, v))
