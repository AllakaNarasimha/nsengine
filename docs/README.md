# nslogger - Financial Data Logging & Management Library

A Python library for managing financial instrument data, including options chains, futures contracts, and tick data with intelligent caching and SQLite storage.

## Features

- **Unified Instrument Caching**: Cache instrument info, futures, options, and expiries per symbol
- **Tick Data Management**: Efficient tick price and volume aggregation with resample support
- **Option Chain Analysis**: ATM strike computation, moneyness classification, and option pricing
- **Future Contracts**: Retrieve futures by expiry index (current month, next month, etc.)
- **Volume Aggregation**: Optional volume substitution from future contracts
- **Smart Caching**: LRU cache for time ranges, aggregations, and option subsets
- **CSV to SQLite**: Batch convert feather/pickle files to CSV and ingest into SQLite

## Installation

### From Local Source (Development)

```bash
cd nssqllogger
pip install -e .
```

### From PyPI (when published)

```bash
pip install nslogger
```

## Dependencies

- **pandas** >= 1.5.0 — DataFrame operations
- **setuptools** >= 65.0 — Package management
- Python 3.8+

Install all requirements:

```bash
pip install -r requirements.txt
```

## Quick Start

```python
from nslogger.history_data_manager import HistoryDataManager

# Initialize manager
hdm = HistoryDataManager(db_dir='./csv', db_date='2025-09-05')

# Get instrument info (uses unified cache)
inst_df = hdm.get_instrument_info('NIFTY')

# Get future contract by expiry index (0=current month)
fut_row = hdm.get_future_info(symbol='NIFTY', segment='INDICES', future_index=0)

# Get option chain with ATM strikes
options = hdm.get_option_info(
    timestamp='2025-09-05 09:30:00',
    underlying='NIFTY 50',
    symbol='NIFTY',
    segment='INDICES',
    atm_strike=19500,
    expiry_index=0,
    strike_count=5
)

# Get aggregated tick data with optional future volume
agg_ticks = hdm.get_aggregated_tick_data(
    underlying='NIFTY 50',
    symbol='NIFTY',
    segment='INDICES',
    interval=5,
    unit='seconds',
    enable_volume=True,
    fut_index=0
)

# Clear caches when data changes
hdm.clear_all_caches()
```

## Package Creation & Distribution

### Create Source Distribution (tar.gz)

#### Using Modern Build Tool (Recommended)

```bash
# Install build tool
pip install --upgrade build

# Build sdist (source) and wheel
python -m build

# Output: dist/nslogger-*.tar.gz and dist/nslogger-*.whl
```

#### Using Legacy setuptools

```bash
python setup.py sdist bdist_wheel

# Output: dist/nslogger-*.tar.gz in dist/ folder
```

### Create tar.gz Manually

```bash
# Clean previous builds
Remove-Item -Path "build", "dist", "*.egg-info" -Recurse -Force

# Create source tarball
tar -czf nslogger-1.0.0.tar.gz --exclude='.venv' --exclude='.git' --exclude='__pycache__' nslogger/

# or use Python
python -m tarfile -c -z nslogger-1.0.0.tar.gz -C .. nslogger/
```

### Create tar.gz Archive (Quick Command)

```powershell
# Navigate to project root
cd D:\NSLearn\copy_trader\client\nssqllogger

# Create tar.gz with build output
python -m build
# Result: dist/nslogger-*.tar.gz

# Or create manually (Windows PowerShell)
tar -czf nslogger-1.0.0.tar.gz --exclude='.venv' --exclude='.git' --exclude='__pycache__' nslogger/

# Or use Python tarfile
python -c "import tarfile; t = tarfile.open('nslogger-1.0.0.tar.gz', 'w:gz'); t.add('nslogger', arcname='nslogger'); t.close(); print('Created nslogger-1.0.0.tar.gz')"
```

### Extract tar.gz Archive

```bash
# Extract to current directory
tar -xzf nslogger-1.0.0.tar.gz

# Extract to specific directory
tar -xzf nslogger-1.0.0.tar.gz -C /path/to/extract
```

### Distribution to PyPI

```bash
# Install twine
pip install twine

# Upload to PyPI (requires credentials)
twine upload dist/*

# Upload to Test PyPI first
twine upload --repository testpypi dist/*
```

## Development

### Running Tests

```bash
python -m pytest tests/
```

### Running Modules Directly (in-source)

```bash
# Use package-aware execution to ensure imports work
python -m nslogger.data_reader
python -m nslogger.history_data_manager
```

**Note**: Do NOT run files directly as scripts:
```bash
# ❌ This can cause import issues
python nslogger/data_reader.py

# ✅ Do this instead
python -m nslogger.data_reader
```

### Cache Management

```python
# Clear specific caches
hdm._instrument_cache.clear()
hdm._tick_cache.clear()

# Clear all caches
hdm.clear_all_caches()
```

## File Structure

```
nslogger/
├── __init__.py
├── sql_script.py              # SQL table creation schemas
├── sql_manager.py             # SQLite connection & queries
├── history_data_manager.py    # Main data manager with caching
├── data_reader.py             # CSV/feather ingestion
├── file_util.py               # File utilities
├── tick_manager.py            # Tick data logging
└── option_chain_manager.py    # Option chain analysis
```

## Caching Strategy

- **Instrument Cache**: Stores instrument_df, future_df, option_df, expiries per symbol
- **Tick Cache**: Caches full tick data per instrument token (datetime indexed)
- **Aggregation Cache**: LRU cache for OHLC results by (instrument, time range, interval)
- **Option Subset Cache**: Caches filtered options by (symbol, expiry)
- **ATM Strike Cache**: Caches strike calculations by (symbol, underlying_price)

Caches are automatically cleared when data is inserted.

## Performance Tips

1. Use `enable_volume=True` with `get_aggregated_tick_data()` to substitute future volume
2. Reuse HistoryDataManager instance to leverage caching across calls
3. Call `clear_all_caches()` only when underlying data changes
4. Index datetime in tick_data for O(1) lookups

## Troubleshooting

### Import Errors After Edits

Clear Python cache and reimport:

```bash
Get-ChildItem -Recurse -Include __pycache__ | Remove-Item -Recurse -Force
Get-ChildItem -Recurse -Include "*.pyc" | Remove-Item -Force
```

### Database Locking

Ensure only one HistoryDataManager instance writes to a database at a time.

### Missing Tick Data

Check that tick data exists for the requested instrument and time range before aggregation.

## License

MIT

## Author

narasimharao.allaka

## Version

1.0.0
