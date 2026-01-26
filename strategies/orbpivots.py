import pandas as pd
from .orbsignal import ORBSignal

class ORBPivots:
    """
    Manages pivot detection using ORBSignal.
    Detects pivot candles and manages entry windows.
    """
    def __init__(self, orbsignal, opening_range_bars, granularity='minute', max_trades_per_day=3):
        self.orbsignal = orbsignal
        self.opening_range_bars = opening_range_bars
        self.granularity = granularity.lower()
        self.max_trades_per_day = max_trades_per_day
        # Opening range tracking
        self.range_high = None
        self.range_low = None
        self.orb_start = None
        self.orb_end = None
        self.open_range_completed = False
        # Pivot detection
        self.pivot_candle_time = None
        self.pivot_high = None
        self.pivot_low = None
        self.pivot_direction = None
        self.entry_window_start = None
        self.in_entry_window = False
        self.require_range_retouch = False
        self.trades_taken_today = 0

    def update_candle(self, candle):
        """
        Update with a new candle. Handles ORB range collection, pivot detection, entry windows, and retouch.
        Returns dict with pivot or entry info if applicable.
        """
        ct = candle['time']
        # Initialize ORB window
        if self.orb_start is None:
            self.orb_start = ct
            if self.granularity == 'minute':
                self.orb_end = self.orb_start + pd.Timedelta(minutes=self.opening_range_bars)
            else:
                self.orb_end = self.orb_start + pd.Timedelta(hours=self.opening_range_bars)

        # Collect opening range
        if ct < self.orb_end:
            self.range_high = max(self.range_high, candle['high']) if self.range_high is not None else candle['high']
            self.range_low = min(self.range_low, candle['low']) if self.range_low is not None else candle['low']
            return None

        if not self.open_range_completed:
            self.open_range_completed = True

        # Pivot detection
        if (
            self.pivot_candle_time is None and
            self.trades_taken_today < self.max_trades_per_day and
            not self.require_range_retouch
        ):
            direction = self.orbsignal.check_breakout(candle, self.range_high, self.range_low)
            if direction:
                self.pivot_candle_time = ct
                self.pivot_high = self.range_high
                self.pivot_low = self.range_low
                self.pivot_direction = direction
                self.entry_window_start = ct + pd.Timedelta(minutes=1)
                self.in_entry_window = True
                return {
                    'pivot_detected': True,
                    'direction': direction,
                    'pivot_time': ct,
                    'pivot_high': self.pivot_high,
                    'pivot_low': self.pivot_low
                }

        # Entry window check
        if (
            self.in_entry_window and
            self.entry_window_start and
            ct >= self.entry_window_start and
            self.trades_taken_today < self.max_trades_per_day
        ):
            if self.pivot_direction == 'bull' and candle['high'] >= self.pivot_high:
                self.trades_taken_today += 1
                self.in_entry_window = False
                self.require_range_retouch = True
                return {
                    'entry_signal': 'buy',
                    'pivot_high': self.pivot_high,
                    'pivot_low': self.pivot_low,
                    'pivot_time': self.pivot_candle_time,
                    'trade_number': self.trades_taken_today
                }
            elif self.pivot_direction == 'bear' and candle['low'] <= self.pivot_low:
                self.trades_taken_today += 1
                self.in_entry_window = False
                self.require_range_retouch = True
                return {
                    'entry_signal': 'sell',
                    'pivot_high': self.pivot_high,
                    'pivot_low': self.pivot_low,
                    'pivot_time': self.pivot_candle_time,
                    'trade_number': self.trades_taken_today
                }

        # Range retouch
        if (
            not self.in_entry_window and
            self.require_range_retouch and
            self.open_range_completed and
            self.range_low <= candle['close'] <= self.range_high
        ):
            self.pivot_candle_time = None
            self.pivot_high = None
            self.pivot_low = None
            self.pivot_direction = None
            self.entry_window_start = None
            self.in_entry_window = False
            self.require_range_retouch = False

        return None

    def reset(self):
        """Reset pivot state."""
        self.range_high = None
        self.range_low = None
        self.orb_start = None
        self.orb_end = None
        self.open_range_completed = False
        self.pivot_candle_time = None
        self.pivot_high = None
        self.pivot_low = None
        self.pivot_direction = None
        self.entry_window_start = None
        self.in_entry_window = False
        self.require_range_retouch = False
        self.trades_taken_today = 0