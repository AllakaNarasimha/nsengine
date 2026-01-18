class CandleAggregator:
    """
    Handles candle construction logic based on tick data.
    Aggregates price ticks into OHLC candles based on specified granularity.
    """
    def __init__(self, granularity='minute'):
        self.granularity = granularity.lower()
        if self.granularity not in ('minute', 'hour'):
            raise ValueError("granularity must be 'minute' or 'hour'")
        self.current_bucket = None
        self.ohlc = None  # {'time', 'open', 'high', 'low', 'close'}

    def update(self, price, dt):
        """
        Update with a new price tick at given datetime.
        Returns finalized candle if bucket changes, else None.
        """
        # Determine bucket timestamp
        if self.granularity == 'minute':
            bucket_ts = dt.replace(second=0, microsecond=0)
        else:  # hour
            bucket_ts = dt.replace(minute=0, second=0, microsecond=0)

        if self.current_bucket is None or bucket_ts != self.current_bucket:
            # Finalize previous candle if exists
            finalized = self.ohlc.copy() if self.ohlc else None
            # Start new candle
            self.ohlc = {
                'time': bucket_ts,
                'open': price,
                'high': price,
                'low': price,
                'close': price
            }
            self.current_bucket = bucket_ts
            return finalized
        else:
            # Update current candle
            self.ohlc['high'] = max(self.ohlc['high'], price)
            self.ohlc['low'] = min(self.ohlc['low'], price)
            self.ohlc['close'] = price
            return None

    def finalize_current(self):
        """Manually finalize and return the current candle."""
        if self.ohlc:
            finalized = self.ohlc.copy()
            self.ohlc = None
            self.current_bucket = None
            return finalized
        return None

    def reset(self):
        """Reset the aggregator state."""
        self.current_bucket = None
        self.ohlc = None