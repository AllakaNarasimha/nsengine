# NS Engine - Trading Strategy Runner

A Python-based backtesting engine for running multiple trading strategies (EMA, RSI, Scalper, and ORB) with support for options trading and real-time charting.

## Project Structure

```
ns_engine/
├── main_new_plot.py           # Main application entry point
├── data_manager.py             # Data loading and management
├── trade_manager.py            # Trade execution and management
├── ema_strategy.py             # EMA strategy implementation
├── rsi_strategy.py             # RSI strategy implementation
├── scalper_strategy.py         # Scalper strategy implementation
├── orb_strategy.py             # Opening Range Breakout strategy
├── ns_mplchart.py              # Matplotlib charting library
├── ns_tvchart.py               # TradingView charting library
├── requirements.txt            # Python dependencies
└── README.md                   # This file
```

## Requirements

### Python Version
- Python 3.13.3 or higher

### External Dependencies
The project requires the following Python packages:

- **pandas** - Data manipulation and CSV handling
- **numpy** - Numerical computations
- **numba** - JIT compilation for performance optimization

### Internal Dependencies
- **nslogger** - Custom logging library for historical data management

## Installation & Setup

### Step 1: Install Python Packages

Navigate to the project directory and install all required dependencies:

```powershell
pip install -r requirements.txt
```

This command installs:
- pandas
- numpy
- numba

### Step 2: Install nslogger Package

Install the custom nslogger library:

```powershell
pip install nslogger-0.1.0.tar.gz
```

Or if the tar.gz file is in the current directory:

```powershell
C:/Python313/python.exe -m pip install nslogger-0.1.0.tar.gz
```

## Running the Application

To run the backtesting engine:

```powershell
C:/Python313/python.exe main_new_plot.py
```

Or simply:

```powershell
python main_new_plot.py
```

## Configuration

The application uses the `AppConfig` class to configure the backtesting environment. Key configuration parameters include:

- **db_dir** - Database directory path
- **symbol** - Trading symbol (e.g., 'NIFTY')
- **strategy_type** - Strategy to use: 'ema', 'rsi', 'scalper', or 'orb'
- **strategy_params** - Strategy-specific parameters
- **candle_freq** - Candle frequency (e.g., '5min', '1min')
- **chart_library** - Chart rendering: 'mpl' (Matplotlib) or 'tv' (TradingView)
- **start_date** / **end_date** - Backtest date range
- **start_time** / **end_time** - Trading session hours

### Example Configuration

```python
config = AppConfig(
    db_dir=parent_dir,
    symbol='NIFTY',
    underlying='NIFTY 50',
    segment='INDICES',
    instrument_type='EQ',
    strategy_type='orb',
    strategy_params={'stop_loss_pct': 0.1, 'trailing_stop_pct': 0.2},
    trades_csv='nifty_orb.csv',
    start_date='2025-09-01',
    end_date='2025-09-05',
    candle_freq='5min',
    chart_library='tv'
)
```

## Supported Strategies

### 1. EMA (Exponential Moving Average)
Parameters:
- `short_period` - Short EMA period (default: 5)
- `long_period` - Long EMA period (default: 20)

### 2. RSI (Relative Strength Index)
Parameters:
- `period` - RSI period (default: 14)
- `oversold` - Oversold threshold (default: 30)
- `overbought` - Overbought threshold (default: 70)

### 3. Scalper
Parameters:
- `run_candle` - Running candle identifier (default: 1)
- `ema_min` - Minimum EMA period (default: 5)
- `ema_period` - EMA period (default: 21)
- `stop_loss_pct` - Stop loss percentage
- `trailing_stop_pct` - Trailing stop percentage

### 4. ORB (Opening Range Breakout)
Parameters:
- `range_minutes` - Opening range duration
- `max_trades_per_day` - Maximum trades per session
- `candle_granularity` - Candle granularity: 'minute' or 'hour'
- `opening_range_bars` - Number of bars for opening range
- `stop_loss_pct` - Stop loss percentage
- `trailing_stop_pct` - Trailing stop percentage
- `target_pct` - Profit target percentage

## Chart Library Options

### Matplotlib (MPL)
- Default chart library
- Real-time candlestick charts
- P&L visualization
- Cumulative P&L line

### TradingView (TV)
- HTML-based charts using TradingView Lightweight Charts
- Auto-update capability
- Custom HTML export
- Auto-refresh support

**Configuration Options for TradingView:**
- `tv_autoupdate` - Enable auto-updates (default: False)
- `tv_update_every` - Update frequency in candles (default: 5)
- `tv_refresh_seconds` - Auto-refresh interval (default: 0)
- `tv_auto_open` - Open HTML in browser (default: False)
- `tv_pl_multiline` - Show each P&L on separate line (default: False)
- `tv_pl_color_scale` - Scale color by P&L magnitude (default: True)
- `tv_pl_separate_panel` - Render P&L in separate chart (default: False)

## Output Files

The application generates the following output files:

- **trading.log** - Application logs
- **[trades_csv]** - Trade journal (default: 'trading_journal.csv')
- **[export_csv]** - Price data export
- **[export_csv].png** - Strategy visualization (if applicable)
- **[export_csv].html** - TradingView chart export (if tv chart enabled)

## Features

### Performance Optimization
- JIT compilation using Numba for fast OHLC calculations
- Efficient tick aggregation into higher timeframes
- EMA caching mechanism
- Configurable candle retention (default: 1000 candles)

### Trade Management
- Automated entry and exit signals
- Stop-loss enforcement
- Trailing stop functionality
- Options chain integration
- End-of-day position closing
- Trade journaling with cumulative P&L tracking

### Charting
- Real-time candle updates
- P&L markers on charts
- Trade entry/exit visualization
- Pivot point indicators
- Range highlighting

## Troubleshooting

### Module Import Errors
Ensure all dependencies are installed:
```powershell
pip install -r requirements.txt
pip install nslogger-0.1.0.tar.gz
```

### Database Connection Issues
Verify the `db_dir` path exists and contains the required database files.

### Chart Rendering Issues
- For Matplotlib: Ensure a display environment is available
- For TradingView: Verify HTML export path is writable

## Setup Commands Summary

All commands executed during setup:

1. **Install core dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```
   Status: ✓ Completed (Exit Code: 0)

2. **Install nslogger package:**
   ```powershell
   C:/Python313/python.exe -m pip install nslogger-0.1.0.tar.gz
   ```
   Status: ✓ Completed (Exit Code: 0)
   Output: Successfully installed nslogger-0.1.0

3. **Run the application:**
   ```powershell
   C:/Python313/python.exe main_new_plot.py
   ```

## Development Notes

- The codebase uses type hints and structured logging
- JIT compilation is enabled with caching for performance
- External candles are used for ORB strategy
- Options data is loaded dynamically during execution

## License

[Add your license information here]

## Support

For issues or questions, contact the development team.
