# File Path Corrections - Output Folder Management

## Issue
Files were being generated in the project root directory instead of the designated `output/` folder:
- `chart_data.csv`
- `tv_export_error.log`
- `trading.log`

## Solution

### 1. Created Centralized Logging Configuration
**File**: `core/logging_config.py`

```python
def setup_logging(log_filename='trading.log'):
    """Set up logging with output directory."""
    output_dir = os.path.join(..., 'output')
    os.makedirs(output_dir, exist_ok=True)
    log_path = os.path.join(output_dir, log_filename)
    # ... configure logging
    
def get_output_dir():
    """Get the output directory path."""
    # ... returns/creates output directory
```

### 2. Fixed chart_data.csv Path
**File**: `charts/ns_tvchart.py` - `_export()` method

**Before**:
```python
df.to_csv("chart_data.csv")
```

**After**:
```python
output_dir = os.path.join(os.path.dirname(...), 'output')
os.makedirs(output_dir, exist_ok=True)
chart_data_path = os.path.join(output_dir, 'chart_data.csv')
df.to_csv(chart_data_path)
```

### 3. Fixed tv_export_error.log Path
**File**: `charts/ns_tvchart.py` - Exception handler

**Before**:
```python
with open('tv_export_error.log', 'a', encoding='utf-8') as f:
```

**After**:
```python
output_dir = os.path.join(os.path.dirname(...), 'output')
os.makedirs(output_dir, exist_ok=True)
error_log_path = os.path.join(output_dir, 'tv_export_error.log')
with open(error_log_path, 'a', encoding='utf-8') as f:
```

### 4. Updated Trade Journal Logging
**File**: `core/journal.py`

**Before**:
```python
logging.basicConfig(filename='trading.log', ...)
self.trades_csv = trades_csv
```

**After**:
```python
from core.logging_config import setup_logging, get_output_dir

output_dir = get_output_dir()
self.trades_csv = os.path.join(output_dir, trades_csv)
setup_logging()
```

## Files Fixed

| File | Issue | Solution |
|------|-------|----------|
| `charts/ns_tvchart.py` | chart_data.csv in root | Save to output/ |
| `charts/ns_tvchart.py` | tv_export_error.log in root | Save to output/ |
| `core/journal.py` | trading.log in root | Use output/ + centralized config |

## Output Directory Structure

```
output/
├── __init__.py              # Package marker
├── chart_data.csv           # ✅ Chart data (now here!)
├── trading.log              # ✅ Trading logs (now here!)
├── tv_export_error.log      # ✅ Export errors (now here!)
├── nifty_orb.csv            # Trade journal
└── nifty_orb_prices_5_tv.html  # TradingView chart
```

## Benefits

1. ✅ **Clean Root Directory** - No generated files in project root
2. ✅ **Organized Output** - All generated files in one place
3. ✅ **Centralized Logging** - Easy to manage logging configuration
4. ✅ **Consistent Paths** - All files follow same pattern
5. ✅ **Easy Cleanup** - Can clear output/ folder easily
6. ✅ **Version Control** - Can safely gitignore output/

## Verification

All fixes have been verified:
- ✅ Logging configuration working
- ✅ Output directory created automatically
- ✅ chart_data.csv saves to output/
- ✅ trading.log saves to output/
- ✅ Error logs save to output/

## Usage

No changes needed for users! The application automatically:
1. Creates the output/ directory if it doesn't exist
2. Saves all generated files to output/
3. Maintains logging in the centralized location

---

**Status**: ✅ Complete
**Tested**: Yes
**Backward Compatible**: Yes
