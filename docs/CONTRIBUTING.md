# NS Engine - Development & Contributing Guide

## Overview

This document provides guidelines for developers working with the NS Engine backtesting framework.

## Project Organization

The project is organized into clear, maintainable modules:

```
config.py      → Configuration management (AppConfig)
utils.py       → Performance utilities (JIT, caching)
journal.py     → Trade journaling and CSV persistence
runner.py      → Main backtesting orchestration (StrategyRunner)
main.py        → Application entry point
```

## Key Principles

### 1. Single Responsibility
Each module should have one clear purpose. If you find a module doing multiple things, consider splitting it.

### 2. Dependency Injection
Pass dependencies through constructors, not global variables:
```python
# Good
runner = StrategyRunner(config)

# Avoid
import main_new_plot
runner = StrategyRunner()  # implicitly uses main_new_plot.config
```

### 3. Error Handling
Always handle errors gracefully:
```python
# Good
try:
    self.mpl_chart.update(...)
except Exception:
    self.logger.exception("Chart update failed")
    # Continue execution

# Avoid
self.mpl_chart.update(...)  # Will crash entire backtest
```

### 4. Logging
Use appropriate log levels:
- `DEBUG`: Detailed state information
- `INFO`: Key events (signals, trades, milestones)
- `WARNING`: Recoverable issues
- `ERROR`: Unrecoverable issues (still caught)

### 5. Documentation
- Add docstrings to all public methods
- Include Args and Returns sections
- Explain complex algorithms

## Code Examples

### Adding a New Configuration Parameter

**Step 1: Update config.py**
```python
class AppConfig:
    def __init__(self, **kwargs):
        default_cfg = dict(
            # ... existing parameters ...
            my_new_param='default_value',  # Add here
        )
        for k, v in default_cfg.items():
            setattr(self, k, kwargs.get(k, v))
```

**Step 2: Use in runner.py**
```python
class StrategyRunner:
    def __init__(self, config: AppConfig):
        self.my_param = getattr(config, 'my_new_param', 'default')
```

**Step 3: Set in main.py**
```python
config = AppConfig(
    my_new_param='custom_value',
    # ... other params ...
)
```

### Adding a New Trading Signal

**Step 1: Strategy Update**
```python
# In your strategy module
def update(self, price, current_datetime):
    # Calculate signal
    if buy_condition:
        return {'signal': 'buy', 'indicator_value': value}
    return None
```

**Step 2: Signal Processing**
```python
# runner.py handles the signal automatically
# No changes needed if following standard signal format
```

### Adding Chart Feature

**Step 1: Update chart module**
```python
# In ns_mplchart.py or ns_tvchart.py
def add_feature(self, data):
    # Implement feature
    pass
```

**Step 2: Call from runner**
```python
# In StrategyRunner._update_charts()
self.mpl_chart.add_feature(data)
```

## Testing Strategy

### Unit Testing Example

```python
# test_config.py
from config import AppConfig

def test_default_config():
    config = AppConfig()
    assert config.candle_freq == '1min'
    assert config.strategy_type == 'ema'

def test_config_override():
    config = AppConfig(candle_freq='5min')
    assert config.candle_freq == '5min'
```

### Integration Testing Example

```python
# test_runner.py
from runner import StrategyRunner
from config import AppConfig

def test_strategy_runner_init():
    config = AppConfig(symbol='TEST', db_dir='/tmp')
    runner = StrategyRunner(config)
    assert runner.cfg.symbol == 'TEST'
    assert runner.lot_size >= 0
```

## Performance Optimization

### Profiling

```python
import cProfile
import pstats

# Profile backtest execution
profiler = cProfile.Profile()
profiler.enable()

runner.run()

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 functions
```

### Memory Usage

```python
import tracemalloc

tracemalloc.start()
runner.run()
current, peak = tracemalloc.get_traced_memory()
print(f"Current: {current / 1024 / 1024:.2f} MB")
print(f"Peak: {peak / 1024 / 1024:.2f} MB")
```

### Optimization Techniques

1. **JIT Compilation**: Use Numba for compute-heavy loops
```python
from numba import jit

@jit(nopython=True, cache=True)
def fast_calculation(array):
    # This runs in compiled machine code
    return np.sum(array)
```

2. **Caching**: Store expensive computations
```python
self.ema_cache = {'last_update': 0}
if candle_dt > self.ema_cache.get('last_update'):
    result = calculate_expensive_value()
    self.ema_cache['value'] = result
    self.ema_cache['last_update'] = candle_dt
else:
    result = self.ema_cache.get('value')
```

3. **Lazy Loading**: Defer initialization until needed
```python
if self.tv_chart is None and config.chart_library == 'tv':
    self.tv_chart = TvChart(config)
```

## Debugging

### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Add Breakpoints

```python
import pdb

def _handle_candle_close(self, next_candle_start):
    pdb.set_trace()  # Execution stops here
    # Use 'n' for next, 's' for step into, 'c' for continue
    self._process_candle_signals(...)
```

### Print Debugging

```python
self.logger.debug(f"Signal: {sig_val}, Price: {price}, Time: {candle_dt}")
```

## Common Issues & Solutions

### Issue: "unable to open database file"
**Solution**: Verify `db_dir` path is correct
```python
import os
print(f"DB dir: {os.path.abspath(config.db_dir)}")
print(f"DB exists: {os.path.exists(config.db_dir)}")
```

### Issue: "No option data available"
**Solution**: Check data_manager cache and option chain loading
```python
self.logger.info(f"Option chain: {self.option_chain_cache}")
self.logger.info(f"Cache size: {len(self.option_chain_cache)}")
```

### Issue: "Module not found" error
**Solution**: Ensure all imports are correct
```python
# Check file exists
import os
print(os.path.exists('strategy_name.py'))

# Try importing
try:
    from strategy_name import StrategyClass
except ImportError as e:
    print(f"Import error: {e}")
```

## Version Control Guidelines

### Commit Messages
```
Format: Type(Scope): Subject

Example:
feat(runner): add trailing stop logging
fix(journal): handle duplicate trades correctly
docs(readme): update installation instructions
```

### Branching
```
feature/new-strategy
bugfix/signal-processing
docs/add-examples
```

## Code Review Checklist

- [ ] Single responsibility principle followed
- [ ] No hardcoded values (use config)
- [ ] Error handling present
- [ ] Logging at appropriate levels
- [ ] Docstrings complete
- [ ] No unused imports
- [ ] Consistent naming conventions
- [ ] Tests pass (if applicable)
- [ ] Performance acceptable
- [ ] Documentation updated

## Running Tests

```bash
# Run all tests
pytest

# Run specific test
pytest test_config.py::test_default_config

# With coverage
pytest --cov=. --cov-report=html

# With verbose output
pytest -v
```

## Documentation Standards

### Function Documentation
```python
def calculate_profit_loss(entry_price, exit_price, position_type, lot_size):
    """
    Calculate profit or loss for a trade.
    
    Args:
        entry_price (float): Entry price
        exit_price (float): Exit price
        position_type (str): 'long' or 'short'
        lot_size (int): Number of lots
        
    Returns:
        float: Profit (positive) or loss (negative)
        
    Example:
        >>> calculate_profit_loss(100, 105, 'long', 10)
        500
    """
    # Implementation
```

### Class Documentation
```python
class StrategyRunner:
    """
    Main strategy runner that orchestrates backtesting execution.
    
    Aggregates ticks into higher timeframe candles and executes signals
    on candle close. Manages trade lifecycle and chart updates.
    
    Attributes:
        cfg (AppConfig): Application configuration
        strategy: Active strategy instance
        trade_manager: Trade execution manager
        
    Example:
        >>> config = AppConfig(symbol='NIFTY')
        >>> runner = StrategyRunner(config)
        >>> runner.run()
    """
```

## Performance Targets

- **Backtest Startup**: < 5 seconds
- **Per-Candle Processing**: < 100ms
- **Memory Usage**: < 500MB for typical backtest
- **Signal Latency**: < 1 second from close to execution

## Future Enhancement Areas

1. **Async/Parallel Processing**: Run multiple backtests in parallel
2. **Machine Learning**: Integrate sklearn/torch for strategy optimization
3. **Live Trading**: Real-time position management
4. **REST API**: HTTP interface for remote backtests
5. **Database Backend**: Replace CSV with PostgreSQL
6. **Distributed Computing**: Use Dask for large-scale backtests
7. **Web Dashboard**: Visualization and monitoring UI
8. **Plugin System**: Third-party strategy/indicator support

## Getting Help

- Check existing documentation in README.md and STRUCTURE.md
- Review similar features in the codebase
- Add logging to understand execution flow
- Profile to identify bottlenecks
- Review strategy class implementations for patterns

## Continuous Improvement

- Keep modules small and focused
- Reduce duplication
- Improve test coverage
- Optimize performance hot paths
- Maintain clear documentation
- Regular code reviews
