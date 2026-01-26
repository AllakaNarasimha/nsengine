# Organized Folder Structure - Complete Guide

## Final Structure

```
ns_engine/
├── core/                          # Framework core modules
│   ├── __init__.py               # Package initialization
│   ├── main.py                   # Application entry point
│   ├── config.py                 # Configuration management
│   ├── runner.py                 # Strategy runner orchestration
│   ├── utils.py                  # Utility functions & JIT
│   └── journal.py                # Trade journaling
│
├── strategies/                    # Trading strategy implementations
│   ├── __init__.py
│   ├── ema_strategy.py           # EMA crossover strategy
│   ├── rsi_strategy.py           # RSI-based strategy
│   ├── scalper_strategy.py       # Scalping strategy
│   └── orb_strategy.py           # Opening range breakout
│
├── data/                          # Data management modules
│   ├── __init__.py
│   ├── data_manager.py           # Data loading & caching
│   ├── trade_manager.py          # Trade execution logic
│   ├── multi_day_db.py           # Multi-day database manager
│   └── signal_generator.py       # Signal generation interface
│
├── charts/                        # Chart rendering modules
│   ├── __init__.py
│   ├── ns_mplchart.py            # Matplotlib charting
│   └── ns_tvchart.py             # TradingView charting
│
├── output/                        # Generated output files
│   ├── __init__.py
│   ├── nifty_orb.csv             # Trade journal
│   ├── nifty_orb_prices_5_tv.html # Chart exports
│   ├── chart_data.csv            # Chart data
│   └── trading.log               # Application logs
│
├── templates/                     # HTML templates
│   ├── __init__.py
│   ├── tv_chart_template.html    # TradingView template
│   └── tv_placeholder.html       # Chart placeholder
│
├── docs/                          # Documentation
│   ├── README.md                 # Setup & usage guide
│   ├── STRUCTURE.md              # Architecture documentation
│   ├── CONTRIBUTING.md           # Development guidelines
│   └── ORGANIZATION.md           # Organization summary
│
├── main_new_plot.py              # Legacy entry point (backward compatible)
├── requirements.txt              # Python dependencies
└── nslogger-0.1.0.tar.gz        # nslogger package
```

## Directory Responsibilities

### core/
**Purpose**: Framework core and orchestration
- `main.py`: Application entry point with configuration
- `config.py`: Centralized configuration management
- `runner.py`: Backtesting orchestration engine
- `utils.py`: JIT-compiled utilities and helpers
- `journal.py`: Trade journaling and CSV persistence

### strategies/
**Purpose**: Trading strategy implementations
- Each strategy inherits from `SignalGeneratorInterface`
- Implements `update()` and `get_indicators()` methods
- Strategy selection via `AppConfig.strategy_type`

### data/
**Purpose**: Data management and trade handling
- `data_manager.py`: Data loading, caching, option chains
- `trade_manager.py`: Trade execution and position tracking
- `multi_day_db.py`: Multi-day database aggregation
- `signal_generator.py`: Strategy interface base class

### charts/
**Purpose**: Visualization and chart rendering
- `ns_mplchart.py`: Real-time Matplotlib charts
- `ns_tvchart.py`: TradingView Lightweight Charts

### output/
**Purpose**: Generated files and exports
- CSV files from backtests
- HTML chart exports
- Trading logs and journals

### templates/
**Purpose**: HTML templates for charting
- TradingView chart templates
- HTML placeholder for initialization

### docs/
**Purpose**: Documentation and guides
- README.md: Setup and usage
- STRUCTURE.md: Architecture details
- CONTRIBUTING.md: Development guidelines
- ORGANIZATION.md: Organization summary

## Running the Application

### Method 1: New Modular Structure (Recommended)
```bash
python core/main.py
```

### Method 2: Legacy Entry Point (Still Works)
```bash
python main_new_plot.py
```

Both methods work identically.

## Import Patterns

### In core modules:
```python
from core.config import AppConfig
from core.runner import StrategyRunner
from core.utils import calculate_ohlc_fast
```

### In strategy modules:
```python
from data.signal_generator import SignalGeneratorInterface
```

### In data modules:
```python
from data.multi_day_db import MultiDayDatabaseManager
```

### In chart modules:
No special imports needed for basic functionality.

## Key Benefits of Organization

1. **Separation of Concerns**: Each module has single responsibility
2. **Maintainability**: Easy to locate and modify code
3. **Scalability**: Simple to add new strategies, charts, etc.
4. **Testing**: Modules can be tested independently
5. **Reusability**: Components can be used in other projects

## File Distribution

| Category | Count | Location |
|----------|-------|----------|
| Core Framework | 5 | core/ |
| Strategies | 4 | strategies/ |
| Data Management | 4 | data/ |
| Charting | 2 | charts/ |
| Documentation | 4 | docs/ |
| Output Files | 4 | output/ |
| Templates | 2 | templates/ |
| Legacy | 1 | ns_engine/ |

## Configuration File Locations

```python
# Output locations
trades_csv='output/nifty_orb.csv'
export_csv='output/nifty_orb_prices_5.csv'

# Template locations
tv_template='templates/tv_chart_template.html'
tv_placeholder='templates/tv_placeholder.html'

# Log location
logging_file='output/trading.log'
```

## Adding New Features

### Add New Strategy
1. Create `strategies/new_strategy.py`
2. Inherit from `SignalGeneratorInterface`
3. Implement `update()` and `get_indicators()` methods
4. Add to strategy selection in `runner.py._get_strategy()`

### Add New Chart Library
1. Create `charts/new_chart.py`
2. Implement `update()` and `export()` methods
3. Add initialization in `runner.py.__init__()`

### Add New Data Source
1. Create `data/new_data_manager.py`
2. Implement data loading interface
3. Integrate with `runner.py`

## Performance Considerations

- JIT compilation in `core/utils.py` provides 2-10x speedup
- Caching in `data/data_manager.py` reduces I/O
- DataFrame operations optimized in `core/runner.py`
- Memory efficient tick buffering in `deque`

## Testing Strategy

```bash
# Test individual modules
python -m pytest core/ -v
python -m pytest strategies/ -v

# Test full integration
python core/main.py
```

## Backward Compatibility

The original `main_new_plot.py` still works and maintains full functionality. It's automatically updated with new imports but kept for compatibility.

## Migration Checklist

- [x] Directory structure created
- [x] Files moved to appropriate folders
- [x] Imports updated in all modules
- [x] __init__.py files created
- [x] Legacy entry point updated
- [x] All tests passing
- [x] Documentation updated
- [x] Application running successfully

## Version Information

- **Organization Date**: November 7, 2025
- **Python Version**: 3.13.3+
- **Status**: ✓ Complete and tested
- **Backward Compatibility**: ✓ Fully maintained

---

**Note**: All imports automatically handle relative/absolute paths. No additional configuration needed.
