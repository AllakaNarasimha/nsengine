"""
NS Engine - Project Structure & Architecture Documentation
"""

# PROJECT STRUCTURE
# =================

The project has been reorganized into maintainable, modular components:

## Core Modules

### config.py
- **Purpose**: Configuration management
- **Classes**: AppConfig
- **Responsibility**: Centralized configuration with sensible defaults
- **Key Features**:
  - All backtesting parameters in one place
  - Easy to override defaults
  - Type-safe configuration handling

### utils.py
- **Purpose**: Utility functions and performance optimization
- **Functions**: 
  - calculate_ohlc_fast() - JIT-compiled OHLC calculation
  - should_throttle_plot() - Plot throttling logic
  - validate_cache_size() - Cache validation
- **Key Features**:
  - Numba JIT compilation for performance
  - Reusable utility functions
  - Cached compilation for faster execution

### journal.py
- **Purpose**: Trade journaling and persistence
- **Classes**: TradeJournal
- **Responsibility**: 
  - Save and update trades
  - Maintain trade history CSV
  - Calculate cumulative P&L
  - Generate backtest summary
- **Key Features**:
  - CSV persistence with auto-update
  - Duplicate trade detection
  - Cumulative P&L tracking
  - Comprehensive logging

### runner.py
- **Purpose**: Main backtesting orchestration
- **Classes**: StrategyRunner
- **Responsibility**:
  - Tick aggregation into candles
  - Strategy signal execution
  - Trade management coordination
  - Chart updates and exports
- **Key Features**:
  - Clean separation of concerns
  - Well-documented methods
  - Comprehensive error handling
  - Modular, testable functions

### main.py
- **Purpose**: Application entry point
- **Functions**: main()
- **Responsibility**: 
  - Configuration setup
  - Application startup
- **Key Features**:
  - Simple, readable configuration
  - Single entry point
  - Easy to modify for different backtests

## External Dependencies (Already Exist)

### Strategy Modules
- **ema_strategy.py** - EMA crossover strategy
- **rsi_strategy.py** - RSI-based strategy
- **scalper_strategy.py** - Scalping strategy
- **orb_strategy.py** - Opening range breakout strategy

### Data Management
- **data_manager.py** - Data loading and caching
- **trade_manager.py** - Trade execution logic
- **nslogger.history_data_manager** - Historical data access

### Charting
- **ns_mplchart.py** - Matplotlib charting
- **ns_tvchart.py** - TradingView HTML charting

## File Organization

```
ns_engine/
├── core/                    # Core framework modules
│   ├── config.py           # Configuration management
│   ├── utils.py            # Utility functions
│   ├── journal.py          # Trade journaling
│   └── runner.py           # Strategy runner
│
├── strategies/             # Strategy implementations (external)
│   ├── ema_strategy.py
│   ├── rsi_strategy.py
│   ├── scalper_strategy.py
│   └── orb_strategy.py
│
├── data/                   # Data management (external)
│   ├── data_manager.py
│   └── trade_manager.py
│
├── charts/                 # Chart rendering (external)
│   ├── ns_mplchart.py
│   └── ns_tvchart.py
│
├── main.py                 # Entry point
├── requirements.txt        # Python dependencies
├── README.md              # Setup & usage guide
└── STRUCTURE.md           # This file
```

## Architecture Patterns

### 1. Separation of Concerns
Each module has a single, well-defined responsibility:
- Configuration → AppConfig
- Utilities → utils
- Journaling → TradeJournal
- Orchestration → StrategyRunner
- Entry point → main

### 2. Dependency Injection
- StrategyRunner receives AppConfig as dependency
- All components initialized in runner.__init__
- Easy to mock/test individual components

### 3. Error Handling
- Comprehensive try-except blocks
- Logging at appropriate levels
- Graceful degradation (e.g., chart failures don't crash backtest)

### 4. Performance Optimization
- JIT compilation for OHLC calculations
- Caching mechanisms for expensive operations
- Efficient data structures (deque for tick buffer)

## Data Flow

```
main.py
  ↓
runner.py (StrategyRunner)
  ├─→ loads data_manager
  ├─→ initializes strategy (ema/rsi/scalper/orb)
  ├─→ aggregates ticks into candles
  ├─→ executes strategy signals
  ├─→ manages trades via trade_manager
  ├─→ updates charts (mpl/tv)
  └─→ persists trades via journal.py

journal.py
  └─→ writes to CSV (trades_csv)
```

## Configuration Flow

```
AppConfig (config.py)
  ├─→ Default values
  ├─→ User overrides
  ├─→ Validation
  └─→ StrategyRunner initialization
```

## Key Methods in StrategyRunner

| Method | Purpose |
|--------|---------|
| `_get_strategy()` | Initialize strategy based on type |
| `build_candle_from_ticks()` | Aggregate ticks into OHLCV |
| `run_backtest()` | Main execution loop |
| `_handle_candle_close()` | Process candle close signals |
| `_process_trade_for_signal()` | Execute trade for signal |
| `update_trade_data()` | Track and journal trades |
| `get_option_data()` | Fetch option chain data |
| `close_trade_on_endtime()` | EOD position closing |

## Extensibility

### Adding a New Strategy
1. Create strategy class with `update()` and `get_indicators()` methods
2. Add strategy_type check in `_get_strategy()`
3. Update configuration docs

### Adding a New Chart Library
1. Create chart class with `update()` and `export()` methods
2. Add chart_library check in StrategyRunner.__init__
3. Call chart methods in `_update_charts()`

### Adding Performance Metrics
1. Add fields to `performance_stats` dict
2. Update in appropriate methods
3. Log in `_finalize_backtest()`

## Maintenance Guidelines

### Code Organization
- Keep methods focused and small (<50 lines ideal)
- Use clear, descriptive names
- Add docstrings to all public methods
- Comment complex logic

### Testing
- Test individual modules (config, utils, journal)
- Mock external dependencies
- Test strategy integration with dummy data

### Performance
- Profile hot paths with cProfile
- Use JIT compilation for compute-heavy loops
- Monitor memory with large datasets
- Cache expensive computations

### Logging
- Use appropriate log levels (DEBUG, INFO, WARNING, ERROR)
- Include context in log messages
- Avoid logging in tight loops

## Migration Notes

### From main_new_plot.py to Modular Structure

**Moved to config.py:**
- AppConfig class
- Default configuration parameters

**Moved to utils.py:**
- JIT-compiled functions
- Performance utility functions

**Moved to journal.py:**
- TradeJournal class
- CSV persistence logic
- P&L calculations

**Moved to runner.py:**
- StrategyRunner class
- Backtesting orchestration
- Signal processing logic

**New entry point:**
- main.py - Simple, readable configuration setup

## Running the Application

### Using new modular structure:
```python
python main.py
```

### Old structure still works:
```python
python main_new_plot.py
```

Both entry points are compatible. Choose based on your needs.

## Future Improvements

1. **Async Processing**: Support parallel strategy evaluation
2. **Walk-Forward Analysis**: Implement rolling window backtests
3. **Monte Carlo Simulation**: Estimate statistical significance
4. **Parameter Optimization**: Systematic parameter tuning
5. **Live Trading**: Add live trading mode alongside backtesting
6. **Machine Learning**: Integrate ML-based strategies
7. **Database Backend**: Replace CSV with proper database
8. **REST API**: HTTP interface for remote execution
9. **Dashboard**: Web-based visualization and monitoring
10. **Plugin System**: Allow custom strategy/chart plugins
