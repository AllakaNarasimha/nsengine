import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.signal_generator import SignalGeneratorInterface
from .orbutils import CandleAggregator
from .orbsignal import ORBSignal
from .orbpivots import ORBPivots
from .orbtrademanager import ORBTradeManager
import logging

logging.basicConfig(filename='trading.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ORBStrategy(SignalGeneratorInterface):
    def __init__(self, range_minutes=15, max_trades_per_day=3, candle_granularity: str = 'minute', opening_range_bars: int | None = None, external_candles: bool = False, stop_loss_pct=None, trailing_stop_pct=None, target_pct=None, require_boundary_touch: bool = True):
        self.external_candles = external_candles  # Now used to choose path
        self.candle_granularity = candle_granularity.lower()
        if self.candle_granularity not in ('minute', 'hour'):
            raise ValueError("candle_granularity must be 'minute' or 'hour'")
        # Opening range definition (bars-based now). Keep original range_minutes for backward compatibility (minute mode)
        if opening_range_bars is None:
            if self.candle_granularity == 'minute':
                opening_range_bars = range_minutes  # same behaviour as before
            else:
                opening_range_bars = 1  # one hour by default for hourly mode
        self.opening_range_bars = opening_range_bars
        # Preserve original attribute for external code relying on it (minute-specific semantics)
        self.range_minutes = range_minutes
        self.max_trades_per_day = max_trades_per_day
        # Logging / storage
        self.logger = logging.getLogger(__name__)
        # Initialize components
        self.orbsignal = ORBSignal(require_boundary_touch=require_boundary_touch)
        self.orbpivots = ORBPivots(self.orbsignal, self.opening_range_bars, self.candle_granularity, self.max_trades_per_day)
        self.orbtrademanager = ORBTradeManager(self.orbpivots, stop_loss_pct, trailing_stop_pct, target_pct)
        # Candle aggregator for tick-based updates
        self.candle_aggregator = CandleAggregator(self.candle_granularity) if not self.external_candles else None
        # Daily control
        self.current_trade_day = None
        # Percentage-based risk management (stored in components)
        self.stop_loss_pct = stop_loss_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.target_pct = target_pct
        self.require_boundary_touch = require_boundary_touch
        self.logger.debug(f"ORBStrategy initialized with stop_loss_pct={self.stop_loss_pct}% trailing_stop_pct={self.trailing_stop_pct}%")

    def reset(self):
        self.orbpivots.reset()
        self.orbtrademanager.reset()
        if self.candle_aggregator:
            self.candle_aggregator.reset()
        self.current_trade_day = None

    def update(self, price, current_datetime):
        """Tick/stream update. Aggregates ticks into candles if not external_candles."""
        # Detect day change
        trade_day = current_datetime.date()
        if self.current_trade_day is None:
            self.current_trade_day = trade_day
        elif trade_day != self.current_trade_day:
            self.logger.info(f"New trading day detected: {trade_day}. Resetting ORB state.")
            self.reset()
            self.current_trade_day = trade_day

        if self.external_candles:
            raise ValueError("update() called but external_candles=True; use update_with_candle() instead")

        # Aggregate ticks into candles
        finalized_candle = self.candle_aggregator.update(price, current_datetime)
        if finalized_candle:
            return self._process_candle(finalized_candle)
        return None

    def update_with_candle(self, candle_dt, candle):
        """Direct candle update."""
        # Day change detection
        trade_day = candle_dt.date()
        if self.current_trade_day is None:
            self.current_trade_day = trade_day
        elif trade_day != self.current_trade_day:
            self.logger.info(f"New trading day detected (external candles): {trade_day}. Resetting ORB state.")
            self.reset()
            self.current_trade_day = trade_day

        return self._process_candle(candle)

    def _process_candle(self, candle):
        """Process a finalized candle through pivots and trade manager."""
        return self.orbtrademanager.update_candle(candle)

    def get_indicators(self):
        # Gather from components
        pivots = self.orbpivots
        trade = self.orbtrademanager
        # Provisional pivot time
        provisional_pivot_time = None
        if pivots.open_range_completed and pivots.pivot_candle_time is None and pivots.orb_end:
            provisional_pivot_time = pivots.orb_end
        return {
            'range_high': pivots.range_high,
            'range_low': pivots.range_low,
            'open_range_completed': pivots.open_range_completed,
            'pivot_time': pivots.pivot_candle_time or provisional_pivot_time,
            'pivot_high': pivots.pivot_high if pivots.pivot_candle_time else (pivots.range_high if provisional_pivot_time else None),
            'pivot_low': pivots.pivot_low if pivots.pivot_candle_time else (pivots.range_low if provisional_pivot_time else None),
            'pivot_direction': pivots.pivot_direction if pivots.pivot_candle_time else None,
            'entry_taken': trade.in_position,  # Simplified
            'daily_trade_taken': pivots.trades_taken_today > 0,  # Legacy
            'trades_taken_today': pivots.trades_taken_today,
            'max_trades_per_day': self.max_trades_per_day,
            'in_position': trade.in_position,
            'stop_loss': trade.stop_loss,
            'stop_loss_pct': self.stop_loss_pct,
            'trailing_stop_pct': self.trailing_stop_pct,
            'entry_price': trade.entry_price,
            'trailing_anchor': trade.trailing_anchor,
            'target_pct': self.target_pct,
            'target_price': trade.target_price,
            'target_locked': trade.target_locked,
            'in_entry_window': pivots.in_entry_window,
            'require_range_retouch': pivots.require_range_retouch,
            'require_boundary_touch': self.require_boundary_touch
        }
