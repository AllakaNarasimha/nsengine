"""
Utility functions module for NS Engine backtesting framework.
Contains JIT-compiled performance-critical functions and helper utilities.
"""

import numpy as np
from numba import jit


@jit(nopython=True, cache=True)
def calculate_ohlc_fast(prices):
    """
    Fast OHLC (Open, High, Low, Close) calculation using Numba JIT compilation.
    
    Args:
        prices (np.array): Array of price values
        
    Returns:
        tuple: (open, high, low, close) prices
    """
    if len(prices) == 0:
        return 0.0, 0.0, 0.0, 0.0
    elif len(prices) == 1:
        price = prices[0]
        return price, price, price, price
    else:
        return prices[0], np.max(prices), np.min(prices), prices[-1]


@jit(nopython=True, cache=True)
def should_throttle_plot(current_time, last_plot_time, ticks_count, min_interval, min_ticks):
    """
    Fast throttling check using JIT compilation.
    Determines if plotting should be throttled based on time and tick count.
    
    Args:
        current_time (float): Current time
        last_plot_time (float): Last time plot was updated
        ticks_count (int): Number of ticks since last plot
        min_interval (float): Minimum time interval between plots
        min_ticks (int): Minimum ticks required before plotting
        
    Returns:
        bool: True if should plot, False otherwise
    """
    return (current_time - last_plot_time >= min_interval and ticks_count >= min_ticks)


@jit(nopython=True, cache=True)
def validate_cache_size(cache_len, data_len):
    """
    Fast cache validation using JIT compilation.
    Validates that cache size matches expected data length.
    
    Args:
        cache_len (int): Current cache length
        data_len (int): Expected data length
        
    Returns:
        bool: True if cache is valid, False otherwise
    """
    return cache_len == data_len and cache_len > 0
