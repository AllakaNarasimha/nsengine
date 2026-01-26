import pandas as pd
import numpy as np
import datetime
import logging
import sys
import os
from functools import lru_cache
from typing import Optional, Tuple, List, Union

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.multi_day_db import MultiDayDatabaseManager
from nslogger.history_data_manager import HistoryDataManager

try:
    from numba import jit, njit
    NUMBA_AVAILABLE = True
except ImportError:
    def jit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    def njit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    NUMBA_AVAILABLE = False

logging.basicConfig(filename='trading.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# JIT-compiled utility functions for performance
@njit(cache=True)
def find_closest_strike_jit(strikes, underlying_price):
    """JIT-compiled function to find closest strike price."""
    if len(strikes) == 0:
        return 0.0
    
    min_diff = abs(strikes[0] - underlying_price)
    closest_strike = strikes[0]
    
    for i in range(1, len(strikes)):
        diff = abs(strikes[i] - underlying_price)
        if diff < min_diff:
            min_diff = diff
            closest_strike = strikes[i]
    
    return closest_strike

@njit(cache=True)
def validate_prices_jit(prices):
    """JIT-compiled price validation."""
    valid_count = 0
    for price in prices:
        if not np.isnan(price) and price > 0:
            valid_count += 1
    return valid_count

@njit(cache=True)
def calculate_price_stats_jit(prices):
    """Fast price statistics calculation."""
    if len(prices) == 0:
        return 0.0, 0.0, 0.0, 0.0
    
    min_price = prices[0]
    max_price = prices[0]
    sum_price = 0.0
    valid_count = 0
    
    for price in prices:
        if not np.isnan(price):
            sum_price += price
            valid_count += 1
            if price < min_price:
                min_price = price
            if price > max_price:
                max_price = price
    
    mean_price = sum_price / valid_count if valid_count > 0 else 0.0
    return min_price, max_price, mean_price, float(valid_count)

class DataManager:
    # Class-level cache for HistoryDataManager objects
    _hdm_cache = {}
    # Cache for option chains to avoid repeated loading
    _option_chain_cache = {}
    _cache_stats = {'hits': 0, 'misses': 0}
    
    def __init__(self, db_dir, symbol, underlying, segment, instrument_type, multi_db_base_path=None, interval=1, unit='minutes'):
        self.db_dir = db_dir
        self.symbol = symbol.upper()
        self.underlying = underlying
        self.segment = segment
        self.instrument_type = instrument_type
        self.multi_db_manager = MultiDayDatabaseManager(multi_db_base_path) if multi_db_base_path else None
        
        # Optimized data structures
        self.data_cache = None
        self.current_index = 0
        self.current_date = None
        self.interval = interval
        self.unit = unit
        
        # Performance tracking
        self._data_stats = {'total_points': 0, 'nan_count': 0, 'last_update': None}
        self._batch_size = 1000  # For batch processing
        self._use_jit = NUMBA_AVAILABLE
        
        # Pre-allocated arrays for frequently used operations
        self._price_buffer = np.empty(10000, dtype=np.float64)
        self._time_buffer = np.empty(10000, dtype='datetime64[ns]')
        
        self.logger = logging.getLogger(__name__)
        if self._use_jit:
            self.logger.debug("DataManager initialized with Numba JIT optimization")
        else:
            self.logger.debug("DataManager initialized without JIT (install numba for better performance)")
    
    @lru_cache(maxsize=128)
    def _get_cached_hdm(self, db_date: str) -> HistoryDataManager:
        """Get or create a cached HistoryDataManager instance with LRU caching."""
        cache_key = f"{self.db_dir}:{db_date}"
        if cache_key not in self.__class__._hdm_cache:
            # Implement LRU eviction if cache gets too large
            if len(self.__class__._hdm_cache) > 50:
                # Remove 10 oldest entries
                keys_to_remove = list(self.__class__._hdm_cache.keys())[:10]
                for key in keys_to_remove:
                    del self.__class__._hdm_cache[key]
                    
            self.__class__._hdm_cache[cache_key] = HistoryDataManager(
                db_file=f'{db_date}-history.db'
            )

            self.logger.debug(f"Created cached HDM for {cache_key}")
        return self.__class__._hdm_cache[cache_key]
    
    @classmethod
    def clear_hdm_cache(cls):
        """Clear the HDM cache (useful for memory management)."""
        cls._hdm_cache.clear()
    
    def load_data(self, start_date=None, end_date=None, use_multi_db=False, preprocessing_days=0):
        if not self.current_date:
            self.current_date = start_date
            
        if use_multi_db and self.multi_db_manager:           
            self.data_cache = self._load_multi_db_data(self.current_date, end_date, preprocessing_days)
        else:
            self.data_cache = self._load_single_db_data(self.current_date, end_date)
        self.logger.info(f"Loaded {len(self.data_cache)} data points for {self.symbol}")
        return self.data_cache

    def save_data_csv(self, path):
        """Save currently loaded data cache to CSV for plotting or analysis."""
        if self.data_cache is None or self.data_cache.empty:
            self.logger.warning("No data to save. Call load_data() first.")
            return False
        self.data_cache.to_csv(path, index=False)
        self.logger.info(f"Saved data cache to {path}")
        return True
    
    def _load_single_db_data(self, start_date: datetime.datetime, end_date: datetime.datetime) -> pd.DataFrame:
        try:
            self.hdm = self._get_cached_hdm(start_date.strftime('%Y-%m-%d'))
            df = self.hdm.get_aggregated_tick_data(
                symbol=self.symbol,
                underlying=self.underlying,
                segment=self.segment,
                start_time=start_date,
                end_time=end_date,
                interval=self.interval,
                unit=self.unit
            )
            
            # Optimize data processing with pre-allocated structures
            if isinstance(df, tuple):
                # Directly create DataFrame with required columns (assumed order)
                result_df = pd.DataFrame([df], columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
                result_df['price'] = result_df['close'].astype('float64')
                return result_df[['datetime', 'price', 'volume']].copy()
            elif isinstance(df, pd.DataFrame) and not df.empty:
                # Keep volume if present
                if 'volume' not in df.columns:
                    df = df.copy()
                    df['volume'] = 0
                result_df = df.assign(price=df['close'].astype('float64'))
                if self._use_jit and len(result_df) > 100:
                    prices = result_df['price'].values
                    valid_count = validate_prices_jit(prices)
                    if valid_count < len(prices) * 0.8:
                        self.logger.warning(f"Data quality warning: only {valid_count}/{len(prices)} valid prices")
                return result_df[['datetime', 'price', 'volume']].copy()
            else:
                # Empty frame
                return pd.DataFrame(columns=['datetime', 'price', 'volume']).astype({'datetime': 'datetime64[ns]', 'price': 'float64', 'volume': 'float64'})
        except Exception as e:
            self.logger.error(f"Error loading single DB data: {e}")
            return pd.DataFrame(columns=['datetime', 'price', 'volume']).astype({'datetime': 'datetime64[ns]', 'price': 'float64', 'volume': 'float64'})
    
    def _load_multi_db_data(self, start_date, end_date, preprocessing_days):
        db_files = self.multi_db_manager.get_date_range_db_files(start_date, end_date) if start_date and end_date else \
                   self.multi_db_manager.get_latest_n_days(preprocessing_days)
        
        # Pre-allocate list with expected size for better performance
        all_data = []
        # Python lists don't have reserve, but we can pre-allocate if we know the size
        expected_size = len(db_files)
        
        for date, db_path in db_files:
            try:
                self.hdm = self._get_cached_hdm(date.strftime('%Y-%m-%d'))
                df = self.hdm.get_aggregated_tick_data(
                    symbol=self.symbol,
                    underlying=self.underlying,
                    segment=self.segment,
                    start_time=None,
                    end_time=None,
                    interval=self.interval,
                    unit=self.unit
                )
                
                # Optimize data processing similar to single db
                if isinstance(df, tuple):
                    daily_df = pd.DataFrame([df], columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
                    daily_df['price'] = daily_df['close']
                    daily_df = daily_df[['datetime', 'price', 'volume']]
                elif isinstance(df, pd.DataFrame) and not df.empty:
                    if 'volume' not in df.columns:
                        df = df.copy(); df['volume'] = 0
                    daily_df = df.assign(price=df['close'])[['datetime', 'price', 'volume']]
                else:
                    continue  # Skip empty data
                    
                if not daily_df.empty:
                    all_data.append(daily_df)
            except Exception as e:
                self.logger.error(f"Failed to load data from {db_path}: {e}")
        
        if not all_data:
            return pd.DataFrame(columns=['datetime', 'price', 'volume']).astype({'datetime': 'datetime64[ns]', 'price': 'float64', 'volume': 'float64'})
        
        # Use concat with copy=False for better performance, then sort once
        result = pd.concat(all_data, ignore_index=True, copy=False)
        return result.sort_values('datetime', kind='mergesort').reset_index(drop=True)
    
    def load_option_chain(self, date_str: str, underlying_price: Union[int, float]) -> pd.DataFrame:
        # Create cache key for option chain
        date_part = date_str.split(' ')[0]
        price_rounded = int(np.round(float(underlying_price) / 50.0) * 50) if not pd.isna(underlying_price) else 25000
        cache_key = f"{date_part}:{price_rounded}:{self.symbol}"
        
        # Check cache first
        if cache_key in self.__class__._option_chain_cache:
            self.__class__._cache_stats['hits'] += 1
            return self.__class__._option_chain_cache[cache_key]
        
        self.__class__._cache_stats['misses'] += 1
        
        # Fast path for common case - already numeric
        if isinstance(underlying_price, (int, float)) and not pd.isna(underlying_price):
            price = float(underlying_price)
            # Use numpy for faster rounding
            atm_strike = int(np.round(price / 50.0) * 50) - 50
        else:
            try:
                price = float(underlying_price)
                if pd.isna(price):
                    self.logger.warning(f"NaN price in load_option_chain, using fallback")
                    atm_strike = 25000
                else:
                    atm_strike = int(np.round(price / 50.0) * 50) - 50
            except (ValueError, TypeError) as e:
                self.logger.warning(f"Invalid underlying_price {underlying_price}: {e}, using fallback")
                atm_strike = 25000  # Default fallback ATM strike for NIFTY
                
        hdm = self._get_cached_hdm(date_part)
        df = hdm.get_option_info(
            timestamp=date_str,
            underlying=self.underlying,
            symbol=self.symbol,
            segment=self.segment,
            atm_strike=atm_strike,
            expiry_index=0,
            strike_count=20  # Load more strikes for better caching
        )
        
        if isinstance(df, (list, tuple)):
            df = pd.DataFrame(df)
            
        # Cache the result (limit cache size) update cache when data is there only
        if df is not None and not df.empty:
            if len(self.__class__._option_chain_cache) > 100:
                # Remove oldest entries
                keys_to_remove = list(self.__class__._option_chain_cache.keys())[:20]
                for key in keys_to_remove:
                    del self.__class__._option_chain_cache[key]

            self.__class__._option_chain_cache[cache_key] = df
        return df
    
    def find_atm_option(self, underlying_price: float, option_chain: pd.DataFrame, option_type: str) -> Optional[pd.Series]:
        if option_chain.empty:
            return None
            
        # Cache column name check
        symbol_col = 'tradingsymbol' if 'tradingsymbol' in option_chain.columns else 'symbol'
        
        # Pre-filter by option type with optimized string matching
        if option_type == 'CE':
            mask = option_chain[symbol_col].str.endswith('CE', na=False)
        elif option_type == 'PE':
            mask = option_chain[symbol_col].str.endswith('PE', na=False)
        else:
            # Fallback to regex for other cases
            mask = option_chain[symbol_col].str.contains(f'.*{option_type}', na=False, regex=True)
            
        filtered_options = option_chain[mask]
        
        if filtered_options.empty:
            return None
            
        # Use numpy for faster array operations
        strikes = filtered_options['strike'].dropna().values
        if strikes.size == 0:
            return None
        
        # Use JIT-compiled function for large datasets
        if self._use_jit and len(strikes) > 20:
            closest_strike = find_closest_strike_jit(strikes, underlying_price)
        else:
            # Vectorized absolute difference calculation
            strike_diffs = np.abs(strikes - underlying_price)
            closest_idx = np.argmin(strike_diffs)
            closest_strike = strikes[closest_idx]
        
        # Use optimized filtering
        if len(filtered_options) > 100:
            # Use query for large datasets
            result = filtered_options.query(f'strike == {closest_strike}')
            return result.iloc[0] if not result.empty else None
        else:
            # Direct boolean indexing for smaller datasets
            mask = filtered_options['strike'] == closest_strike
            result = filtered_options[mask]
            return result.iloc[0] if not result.empty else None
    
    def get_initialization_data(self, look_back_periods):
        if self.data_cache is None:
            self.load_data()
        look_back_periods = min(look_back_periods, len(self.data_cache))
        init_data = self.data_cache.head(look_back_periods)
        self.current_index = look_back_periods
        return init_data['price'].tolist(), init_data['datetime'].tolist()
    
    def get_next_data_point(self) -> Tuple[Optional[float], Optional[datetime.datetime], Optional[float]]:
        if self.data_cache is None or self.current_index >= len(self.data_cache):
            return None, None, None
            
        # Batch validation for better performance
        max_retries = 10  # Prevent infinite recursion
        retries = 0
        
        while retries < max_retries:
            try:
                # Use direct array access for better performance
                if self.current_index < len(self.data_cache):
                    row = self.data_cache.iloc[self.current_index]
                    self.current_index += 1
                    
                    # Fast validation using numpy
                    price = row['price']
                    datetime_val = row['datetime']
                    volume = row.get('volume', 0.0)
                    # Use numpy's faster NaN check
                    if not np.isnan(price) and price > 0:
                        self._data_stats['total_points'] += 1
                        return float(price), datetime_val, volume
                    else:
                        self._data_stats['nan_count'] += 1
                        retries += 1
                        # Skip NaN/invalid values and try next
                        continue
                else:
                    return None, None, None
                    
            except (IndexError, KeyError) as e:
                self.logger.error(f"Error accessing data at index {self.current_index}: {e}")
                return None, None, None
                
        # If we've hit max retries, log warning and return None
        self.logger.warning(f"Skipped {retries} invalid data points, returning None")
        return None, None, None

    def get_next_data_point_with_volume(self) -> Tuple[Optional[float], Optional[datetime.datetime], Optional[float]]:
        """Return price, datetime, volume (volume 0 if not present)."""
        price, dt, volume = self.get_next_data_point()
        if price is None:
            return None, None, None
        try:
            volume = float(self.data_cache.iloc[self.current_index - 1].get('volume', 0))
        except Exception:
            volume = 0.0
        return price, dt, volume

    def get_live_data(self, current_minute):
        start_time = current_minute.strftime('%Y-%m-%d %H:%M:%S')
        end_time = (current_minute + datetime.timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S')
        hdm = self._get_cached_hdm(current_minute.strftime('%Y-%m-%d'))
        df = hdm.get_aggregated_tick_data(
            symbol=self.symbol,
            underlying=self.underlying,
            segment=self.segment,
            start_time=None,
            end_time=None,
            interval=self.interval,
            unit=self.unit
        )
        if isinstance(df, (list, tuple)) and df:
            return df[0]['price'], current_minute
        return None, None
    
    def get_batch_data_points(self, batch_size: int = None) -> List[Tuple[float, datetime.datetime]]:
        """Get multiple data points at once for batch processing."""
        batch_size = batch_size or self._batch_size
        batch_data = []
        
        for _ in range(batch_size):
            price, dt = self.get_next_data_point()
            if price is None:
                break
            batch_data.append((price, dt))
            
        return batch_data
    
    def get_data_statistics(self) -> dict:
        """Get performance statistics for the data manager."""
        cache_hit_rate = (self._cache_stats['hits'] / 
                         (self._cache_stats['hits'] + self._cache_stats['misses']) * 100 
                         if (self._cache_stats['hits'] + self._cache_stats['misses']) > 0 else 0)
        
        return {
            'total_data_points': self._data_stats['total_points'],
            'nan_count': self._data_stats['nan_count'],
            'cache_hit_rate': f"{cache_hit_rate:.2f}%",
            'hdm_cache_size': len(self._hdm_cache),
            'option_cache_size': len(self._option_chain_cache),
            'jit_enabled': self._use_jit,
            'current_index': self.current_index,
            'data_cache_size': len(self.data_cache) if self.data_cache is not None else 0
        }
    
    @classmethod
    def clear_all_caches(cls):
        """Clear all caches for memory management."""
        cls._hdm_cache.clear()
        cls._option_chain_cache.clear()
        cls._cache_stats = {'hits': 0, 'misses': 0}
    
    def reset(self):
        """Reset data manager state."""
        self.current_index = 0
        self._data_stats['last_update'] = datetime.datetime.now()